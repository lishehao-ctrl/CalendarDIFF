---
name: aws-release
description: Use when changing GitHub remotes, deploying CalendarDIFF to the AWS host, syncing repo state to the server, or editing live host config such as nginx/.env. Read this before any GitHub→AWS release or host-level runtime change.
---

# AWS Release Skill

Use this skill for CalendarDIFF release and live-ops work.

## Scope

This repo owns the CalendarDIFF app running on:

- domain: `cal.shehao.app`
- AWS host: `ec2-user@54.197.37.63`
- app dir: `/home/ec2-user/apps/CalendarDIFF`
- SSH key: `~/.ssh/aws-main.pem`
- canonical GitHub remote: `git@github.com:lishehao/CalendarDIFF.git`

Read these first when relevant:

- `docs/nginx_live_routing_architecture.md`
- `docs/deploy_three_layer_runtime.md`

## Default release workflow

1. Make repo changes locally.
2. Run required checks:
   - `cd frontend && npm run typecheck && npm run lint && npm run build`
3. Commit locally.
4. Push to `origin main`.
5. Sync AWS checkout from the local pushed commit.
6. Verify remote runtime health.

Preferred command from the repo root:

```bash
scripts/release_aws_main.sh
```

## Guardrails

- Do not deploy uncommitted changes.
- Do not push to any repo other than `lishehao/CalendarDIFF` unless the user explicitly asks.
- The current AWS host does not assume a GitHub deploy key. The repo is synced from the local machine via a temporary `git bundle`.
- Treat host-level files as separate from repo-tracked files:
  - `/home/ec2-user/apps/CalendarDIFF/.env`
  - `/etc/nginx/conf.d/cal-shehao-app.conf`
  - `/etc/nginx/conf.d/websocket-upgrade-map.conf`
- If you change host-level runtime config, also update repo docs so future agents know the intended state.
- CalendarDIFF owns only `cal.shehao.app`; do not modify unrelated domains unless explicitly asked.

## Current live runtime assumptions

- `cal.shehao.app` pages -> frontend on `127.0.0.1:3000`
- `cal.shehao.app/oauth/callbacks/*` -> `public-service` on `127.0.0.1:8000`
- `cal.shehao.app/health` -> `public-service` on `127.0.0.1:8000/health`
- Gmail OAuth client secrets live outside the repo and are mounted into compose via `HOST_SECRETS_DIR`
- AWS repo checkout lives at `/home/ec2-user/apps/CalendarDIFF`
- Reserve `/home/ec2-user/apps/rpg-demo` and a separate nginx server block for `rpg.shehao.app`; do not collapse CalendarDIFF and RPG into one site config.

## Remote verification checklist

After syncing the server, verify at minimum:

```bash
ssh -i ~/.ssh/aws-main.pem ec2-user@54.197.37.63 '
  cd /home/ec2-user/apps/CalendarDIFF && \
  git rev-parse --short HEAD && \
  sudo nginx -t && \
  sudo docker compose ps && \
  curl -sS https://cal.shehao.app/health && \
  curl -I -sS https://cal.shehao.app/login | head -n 12
'
```

## When host-level config changes are needed

If a task requires nginx, `.env`, secrets mounts, or server-only overrides:

1. apply the host change on AWS
2. verify the host runtime
3. mirror the intended architecture or deployment rule back into repo docs
4. prefer turning successful one-off fixes into repo-tracked defaults when safe
