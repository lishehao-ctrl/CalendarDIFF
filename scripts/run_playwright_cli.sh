#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
export CODEX_HOME="${CODEX_HOME:-$HOME/.codex}"
export NPM_CONFIG_CACHE="${NPM_CONFIG_CACHE:-$ROOT_DIR/.cache/npm-playwright}"
export npm_config_cache="$NPM_CONFIG_CACHE"
export PLAYWRIGHT_LOCAL_HOME="${PLAYWRIGHT_LOCAL_HOME:-$ROOT_DIR/.cache/playwright-home}"
export PLAYWRIGHT_BROWSERS_PATH="${PLAYWRIGHT_BROWSERS_PATH:-$ROOT_DIR/.cache/ms-playwright}"
export XDG_CACHE_HOME="${XDG_CACHE_HOME:-$ROOT_DIR/.cache}"
mkdir -p "$NPM_CONFIG_CACHE" "$PLAYWRIGHT_LOCAL_HOME" "$PLAYWRIGHT_BROWSERS_PATH" "$XDG_CACHE_HOME"
export HOME="$PLAYWRIGHT_LOCAL_HOME"

PWCLI="$CODEX_HOME/skills/playwright/scripts/playwright_cli.sh"
DEFAULT_CONFIG="$ROOT_DIR/.playwright/cli.config.json"
DEFAULT_BROWSER="${PLAYWRIGHT_BROWSER:-firefox}"

if [ ! -x "$PWCLI" ]; then
  echo "Playwright CLI wrapper not found at $PWCLI" >&2
  exit 1
fi

if [ "${1:-}" = "bootstrap" ]; then
  shift || true
  exec npx --yes playwright install "$DEFAULT_BROWSER" "$@"
fi

args=("$@")
has_browser="false"
has_config="false"
for arg in "${args[@]}"; do
  case "$arg" in
    --browser|--browser=*) has_browser="true" ;;
    --config|--config=*) has_config="true" ;;
  esac
done

cmd=("$PWCLI")
if [ "$has_browser" != "true" ]; then
  cmd+=(--browser "$DEFAULT_BROWSER")
fi
if [ "$has_config" != "true" ]; then
  cmd+=(--config "$DEFAULT_CONFIG")
fi
cmd+=("${args[@]}")

exec "${cmd[@]}"
