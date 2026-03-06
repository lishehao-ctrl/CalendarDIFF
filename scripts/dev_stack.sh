#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
FRONTEND_DIR="$ROOT_DIR/frontend"
ENV_FILE="$ROOT_DIR/.env"
LOG_DIR="$ROOT_DIR/output/dev-stack"
TAIL_LINES="${DEV_STACK_TAIL_LINES:-80}"

SERVICES=(frontend input review ingest notification llm)
BACKEND_SERVICES=(input review ingest notification llm)

usage() {
  cat <<'USAGE'
Usage:
  scripts/dev_stack.sh up
  scripts/dev_stack.sh down [--infra]
  scripts/dev_stack.sh status
  scripts/dev_stack.sh logs [frontend|input|review|ingest|notification|llm|all]
USAGE
}

die() {
  printf 'dev_stack: %s\n' "$1" >&2
  exit 1
}

service_port() {
  case "$1" in
    frontend) echo 3000 ;;
    review) echo 8000 ;;
    input) echo 8001 ;;
    ingest) echo 8002 ;;
    notification) echo 8004 ;;
    llm) echo 8005 ;;
    postgres) echo 5432 ;;
    redis) echo 6379 ;;
    *) die "unknown service '$1'" ;;
  esac
}

service_url() {
  case "$1" in
    frontend) echo "http://127.0.0.1:3000" ;;
    *) echo "http://127.0.0.1:$(service_port "$1")/health" ;;
  esac
}

service_pid_file() {
  echo "$LOG_DIR/$1.pid"
}

service_log_file() {
  echo "$LOG_DIR/$1.log"
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || die "required command '$1' is not installed"
}

require_docker_compose() {
  require_command docker
  (cd "$ROOT_DIR" && docker compose version >/dev/null 2>&1) || die "'docker compose' is required to start postgres and redis"
}

load_env() {
  [ -f "$ENV_FILE" ] || die "missing $ENV_FILE"
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
  : "${APP_API_KEY:?APP_API_KEY is required in .env}"
  : "${DATABASE_URL:?DATABASE_URL is required in .env}"
  : "${REDIS_URL:?REDIS_URL is required in .env}"
}

ensure_frontend_ready() {
  [ -d "$FRONTEND_DIR" ] || die "frontend/ does not exist"
  [ -d "$FRONTEND_DIR/node_modules" ] || die "frontend/node_modules is missing; run 'cd frontend && npm install' first"
}

ensure_log_dir() {
  mkdir -p "$LOG_DIR"
}

listening_pid() {
  local port="$1"
  lsof -t -nP -iTCP:"$port" -sTCP:LISTEN 2>/dev/null | head -n 1 || true
}

cleanup_stale_pid() {
  local service="$1"
  local pid_file port expected actual
  pid_file="$(service_pid_file "$service")"
  port="$(service_port "$service")"

  if [ -f "$pid_file" ]; then
    expected="$(cat "$pid_file" 2>/dev/null || true)"
    actual="$(listening_pid "$port")"
    if [ -z "$actual" ] || [ "$expected" != "$actual" ]; then
      rm -f "$pid_file"
    fi
  fi
}

ensure_component_available() {
  local service="$1"
  local port pid_file port_pid
  port="$(service_port "$service")"
  pid_file="$(service_pid_file "$service")"

  cleanup_stale_pid "$service"

  if [ -f "$pid_file" ]; then
    return 1
  fi

  port_pid="$(listening_pid "$port")"
  if [ -n "$port_pid" ]; then
    die "$service cannot start because port $port is already in use by pid $port_pid"
  fi

  return 0
}

wait_for_tcp() {
  local label="$1"
  local attempts="$2"
  local port
  port="$(service_port "$label")"

  for _ in $(seq 1 "$attempts"); do
    if python - <<PY >/dev/null 2>&1
import socket
sock = socket.socket()
sock.settimeout(1)
try:
    sock.connect(("127.0.0.1", $port))
except OSError:
    raise SystemExit(1)
finally:
    sock.close()
PY
    then
      return 0
    fi
    sleep 1
  done

  die "$label did not become reachable on port $port"
}

start_infra() {
  require_docker_compose
  printf 'Starting postgres and redis via docker compose...\n'
  (cd "$ROOT_DIR" && docker compose up -d postgres redis >/dev/null)
  wait_for_tcp postgres 60
  wait_for_tcp redis 60
}

run_migrations() {
  printf 'Applying database migrations...\n'
  (cd "$ROOT_DIR" && python -m alembic upgrade head >/dev/null)
}

launch_detached() {
  local cwd="$1"
  local pid_file="$2"
  local log_file="$3"
  shift 3

  python - "$cwd" "$pid_file" "$log_file" "$@" <<'PY'
import subprocess
import sys

cwd, pid_file, log_file, *cmd = sys.argv[1:]
with open(log_file, 'ab', buffering=0) as log:
    process = subprocess.Popen(
        cmd,
        cwd=cwd,
        stdin=subprocess.DEVNULL,
        stdout=log,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
with open(pid_file, 'w', encoding='utf-8') as handle:
    handle.write(str(process.pid))
PY
}

wait_for_http() {
  local service="$1"
  local attempts="$2"
  local url code
  url="$(service_url "$service")"

  for _ in $(seq 1 "$attempts"); do
    code="$(curl -s -o /dev/null -w '%{http_code}' "$url" || true)"
    if [ "$code" = "200" ]; then
      return 0
    fi
    sleep 1
  done

  printf '\nLast log lines for %s:\n' "$service" >&2
  tail -n 40 "$(service_log_file "$service")" >&2 || true
  die "$service did not become healthy at $url"
}

start_backend_service() {
  local service="$1"
  local port pid_file log_file listener
  port="$(service_port "$service")"
  pid_file="$(service_pid_file "$service")"
  log_file="$(service_log_file "$service")"

  if ! ensure_component_available "$service"; then
    printf '%s is already running and managed by dev_stack (pid=%s)\n' "$service" "$(cat "$pid_file")"
    return 0
  fi

  : > "$log_file"
  launch_detached "$ROOT_DIR" "$pid_file" "$log_file" env SERVICE_NAME="$service" HOST=127.0.0.1 PORT="$port" RUN_MIGRATIONS=false ./scripts/start_service.sh

  wait_for_http "$service" 90
  listener="$(listening_pid "$port")"
  [ -n "$listener" ] || die "$service became healthy but no listening pid was found on port $port"
  echo "$listener" >"$pid_file"
  printf 'Started %-12s http://127.0.0.1:%s\n' "$service" "$port"
}

start_frontend() {
  local service="frontend"
  local port pid_file log_file listener
  port="$(service_port "$service")"
  pid_file="$(service_pid_file "$service")"
  log_file="$(service_log_file "$service")"

  ensure_frontend_ready

  if ! ensure_component_available "$service"; then
    printf 'frontend is already running and managed by dev_stack (pid=%s)\n' "$(cat "$pid_file")"
    return 0
  fi

  : > "$log_file"
  launch_detached "$FRONTEND_DIR" "$pid_file" "$log_file" env INPUT_BACKEND_BASE_URL="http://127.0.0.1:8001" REVIEW_BACKEND_BASE_URL="http://127.0.0.1:8000" BACKEND_API_KEY="$APP_API_KEY" WATCHPACK_POLLING=true CHOKIDAR_USEPOLLING=1 npm run dev -- --hostname 127.0.0.1 --port 3000

  wait_for_http "$service" 120
  listener="$(listening_pid "$port")"
  [ -n "$listener" ] || die "$service became healthy but no listening pid was found on port $port"
  echo "$listener" >"$pid_file"
  printf 'Started %-12s http://127.0.0.1:%s\n' "$service" "$port"
}

stop_component() {
  local service="$1"
  local pid_file pid
  pid_file="$(service_pid_file "$service")"
  cleanup_stale_pid "$service"

  if [ ! -f "$pid_file" ]; then
    printf '%s is not managed by dev_stack\n' "$service"
    return 0
  fi

  pid="$(cat "$pid_file")"
  kill "$pid" >/dev/null 2>&1 || true
  for _ in $(seq 1 20); do
    if [ -z "$(listening_pid "$(service_port "$service")")" ]; then
      break
    fi
    sleep 0.5
  done
  if [ -n "$(listening_pid "$(service_port "$service")")" ]; then
    kill -9 "$pid" >/dev/null 2>&1 || true
  fi

  rm -f "$pid_file"
  printf 'Stopped %s\n' "$service"
}

infra_status() {
  local label port state
  for label in postgres redis; do
    port="$(service_port "$label")"
    if python - <<PY >/dev/null 2>&1
import socket
sock = socket.socket()
sock.settimeout(1)
try:
    sock.connect(("127.0.0.1", $port))
except OSError:
    raise SystemExit(1)
finally:
    sock.close()
PY
    then
      state="reachable"
    else
      state="unreachable"
    fi
    printf '%-12s %-10s port=%-5s\n' "$label" "$state" "$port"
  done
}

component_status() {
  local service="$1"
  local port pid_file log_file pid code port_pid state url
  port="$(service_port "$service")"
  pid_file="$(service_pid_file "$service")"
  log_file="$(service_log_file "$service")"
  cleanup_stale_pid "$service"

  if [ -f "$pid_file" ]; then
    pid="$(cat "$pid_file")"
    url="$(service_url "$service")"
    code="$(curl -s -o /dev/null -w '%{http_code}' "$url" || true)"
    if [ "$code" = "200" ]; then
      state="healthy"
    else
      state="starting($code)"
    fi
    printf '%-12s %-12s pid=%-8s port=%-5s log=%s\n' "$service" "$state" "$pid" "$port" "$log_file"
    return 0
  fi

  port_pid="$(listening_pid "$port")"
  if [ -n "$port_pid" ]; then
    printf '%-12s %-12s pid=%-8s port=%-5s log=%s\n' "$service" "external" "$port_pid" "$port" "$log_file"
    return 0
  fi

  printf '%-12s %-12s pid=%-8s port=%-5s log=%s\n' "$service" "stopped" "-" "$port" "$log_file"
}

show_status() {
  printf 'Infra\n'
  infra_status
  printf '\nApplications\n'
  for service in "${SERVICES[@]}"; do
    component_status "$service"
  done
}

show_logs() {
  local target="${1:-all}"
  ensure_log_dir

  if [ "$target" = "all" ]; then
    find "$LOG_DIR" -maxdepth 1 -name '*.log' | grep -q . || die "no log files exist yet"
    tail -n "$TAIL_LINES" -f "$LOG_DIR"/*.log
    return 0
  fi

  case "$target" in
    frontend|input|review|ingest|notification|llm)
      ;;
    *)
      die "invalid logs target '$target'"
      ;;
  esac

  local log_file
  log_file="$(service_log_file "$target")"
  [ -f "$log_file" ] || die "log file for $target does not exist yet"
  tail -n "$TAIL_LINES" -f "$log_file"
}

start_all() {
  require_command python
  require_command npm
  require_command curl
  ensure_log_dir
  load_env
  start_infra
  run_migrations
  for service in "${BACKEND_SERVICES[@]}"; do
    start_backend_service "$service"
  done
  start_frontend
  printf '\nStack is ready.\n'
  printf 'Frontend:     http://127.0.0.1:3000\n'
  printf 'Review API:   http://127.0.0.1:8000/health\n'
  printf 'Input API:    http://127.0.0.1:8001/health\n'
  printf 'Ingest API:   http://127.0.0.1:8002/health\n'
  printf 'Notify API:   http://127.0.0.1:8004/health\n'
  printf 'LLM API:      http://127.0.0.1:8005/health\n'
}

stop_all() {
  local stop_infra="${1:-false}"
  stop_component frontend
  stop_component llm
  stop_component notification
  stop_component ingest
  stop_component review
  stop_component input

  if [ "$stop_infra" = "true" ]; then
    require_docker_compose
    (cd "$ROOT_DIR" && docker compose stop postgres redis >/dev/null)
    printf 'Stopped postgres and redis\n'
  fi
}

main() {
  local command="${1:-}"
  case "$command" in
    up)
      [ "$#" -eq 1 ] || die "'up' does not accept extra arguments"
      start_all
      ;;
    down)
      if [ "$#" -eq 1 ]; then
        stop_all false
      elif [ "$#" -eq 2 ] && [ "$2" = "--infra" ]; then
        stop_all true
      else
        die "usage: scripts/dev_stack.sh down [--infra]"
      fi
      ;;
    status)
      [ "$#" -eq 1 ] || die "'status' does not accept extra arguments"
      show_status
      ;;
    logs)
      if [ "$#" -eq 1 ]; then
        show_logs all
      elif [ "$#" -eq 2 ]; then
        show_logs "$2"
      else
        die "usage: scripts/dev_stack.sh logs [frontend|input|review|ingest|notification|llm|all]"
      fi
      ;;
    ""|-h|--help|help)
      usage
      ;;
    *)
      die "unknown command '$command'"
      ;;
  esac
}

main "$@"
