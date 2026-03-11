# Nginx Live Routing Architecture

This document describes the intended live Nginx layout for CalendarDIFF when hosted on a shared machine with other projects.

## Read This Before Editing

If you are an agent or operator changing live Nginx config for CalendarDIFF, read this file first.

Do **not** merge CalendarDIFF routing back into a catch-all `default` site unless you are intentionally reworking the whole host layout.

## Ownership Model

CalendarDIFF owns only the `cal.shehao.app` site.

It does **not** own:

- `rpg.shehao.app`
- other unrelated sites on the same host
- shared TLS material outside the normal certificate paths

Live host file ownership is expected to look like this:

- `/etc/nginx/sites-available/cal-shehao-app`
- `/etc/nginx/sites-enabled/cal-shehao-app`
- `/etc/nginx/conf.d/websocket-upgrade-map.conf`

`/etc/nginx/sites-available/default` may still exist for other projects, but CalendarDIFF should not depend on it.

## Why CalendarDIFF Uses Split Routing

CalendarDIFF is a split frontend/backend app:

- Next.js frontend listens on `127.0.0.1:3000`
- FastAPI public backend listens on `127.0.0.1:8000`

So the reverse proxy must route by path, not just by domain.

### Required routing rules

For `cal.shehao.app`:

- `/` and normal app pages -> `127.0.0.1:3000`
- `/oauth/callbacks/*` -> `127.0.0.1:8000`
- `/health` -> `127.0.0.1:8000/health`

This preserves three distinct concerns:

1. frontend page rendering
2. backend OAuth callback handling
3. backend health checks

## Why This Site Must Stay Separate

Keeping `cal.shehao.app` in its own Nginx site file prevents several classes of mistakes:

- accidental edits to another project's domain
- accidental loss of the OAuth callback route
- confusion about whether `/` should go to frontend or backend
- future agents editing `default` and breaking multiple apps at once

## Shared HTTP Upgrade Map

The websocket/upgrade map is intentionally stored in:

- `/etc/nginx/conf.d/websocket-upgrade-map.conf`

That file is shared infrastructure, not CalendarDIFF business routing. Keep it outside the per-site file so multiple domains can reuse it safely.

## Expected Live Environment Variables

CalendarDIFF live env should align with the single-domain setup:

```env
APP_BASE_URL=https://cal.shehao.app
FRONTEND_APP_BASE_URL=https://cal.shehao.app
OAUTH_PUBLIC_BASE_URL=https://cal.shehao.app
PUBLIC_WEB_ORIGINS=https://cal.shehao.app
```

If those values point at `localhost` or another domain, OAuth and absolute URL generation can break.

## Change Rules For Future Agents

Before editing live Nginx:

1. read this file
2. confirm CalendarDIFF still owns only `cal.shehao.app`
3. preserve `3000` for frontend page traffic unless the app architecture changed
4. preserve `8000` for `public-service` unless the backend exposure changed
5. preserve `/oauth/callbacks/*` direct routing to backend
6. preserve `/health` direct routing to backend
7. avoid moving CalendarDIFF back into `default`
8. run `sudo nginx -t` before reload
9. validate externally after reload

## Minimal Validation Checklist

After any Nginx change, verify:

```bash
curl -I https://cal.shehao.app
curl -I https://cal.shehao.app/login
curl -s https://cal.shehao.app/health
```

Expected results:

- root redirects to `/login` or renders the app shell
- `/login` returns `200`
- `/health` returns backend JSON with `status: ok`

## When This Document Must Be Updated

Update this document if any of the following change:

- CalendarDIFF stops using `3000` for frontend
- CalendarDIFF stops using `8000` for `public-service`
- OAuth callback path changes
- host/domain ownership changes
- the shared upgrade map moves
- `cal.shehao.app` is split again behind another gateway
