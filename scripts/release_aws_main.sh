#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
AWS_USER="${AWS_USER:-ubuntu}"
AWS_HOST="${AWS_HOST:-54.152.242.119}"
AWS_SSH_KEY="${AWS_SSH_KEY:-$HOME/.ssh/aws-main.pem}"
AWS_APP_DIR="${AWS_APP_DIR:-/home/ubuntu/apps/CalendarDIFF}"
REMOTE_GIT_URL="${REMOTE_GIT_URL:-git@github.com:lishehao/CalendarDIFF.git}"
DOMAIN="${DOMAIN:-cal.shehao.app}"
BUNDLE_PATH="${BUNDLE_PATH:-/tmp/calendardiff-release.bundle}"
DEPLOY_SERVICES="${DEPLOY_SERVICES:-frontend public-service}"

cd "$ROOT_DIR"

if [[ -n "$(git status --short)" ]]; then
  echo "Working tree is not clean. Commit or stash changes before release." >&2
  exit 1
fi

LOCAL_HEAD="$(git rev-parse --short HEAD)"
echo "Pushing $LOCAL_HEAD to origin main..."
git push origin main

echo "Creating release bundle..."
rm -f "$BUNDLE_PATH"
git bundle create "$BUNDLE_PATH" HEAD

echo "Uploading release bundle to $AWS_USER@$AWS_HOST..."
scp -i "$AWS_SSH_KEY" -o StrictHostKeyChecking=accept-new "$BUNDLE_PATH" "$AWS_USER@$AWS_HOST:/tmp/calendardiff-release.bundle"

echo "Syncing AWS checkout on $AWS_USER@$AWS_HOST..."
ssh -i "$AWS_SSH_KEY" -o StrictHostKeyChecking=accept-new "$AWS_USER@$AWS_HOST" bash -s -- "$AWS_APP_DIR" "$REMOTE_GIT_URL" /tmp/calendardiff-release.bundle <<'REMOTE_SYNC'
set -euo pipefail
APP_DIR="$1"
REMOTE_GIT_URL="$2"
REMOTE_BUNDLE="$3"
cd "$APP_DIR"
git remote remove origin >/dev/null 2>&1 || true
git remote add origin "$REMOTE_GIT_URL"
git fetch "$REMOTE_BUNDLE" HEAD
git reset --hard FETCH_HEAD
printf 'REMOTE_HEAD=%s\n' "$(git rev-parse --short HEAD)"
rm -f "$REMOTE_BUNDLE"
REMOTE_SYNC

rm -f "$BUNDLE_PATH"

echo "Rebuilding remote services on $AWS_USER@$AWS_HOST..."
ssh -i "$AWS_SSH_KEY" -o StrictHostKeyChecking=accept-new "$AWS_USER@$AWS_HOST" bash -s -- "$AWS_APP_DIR" "$DEPLOY_SERVICES" <<'REMOTE_DEPLOY'
set -euo pipefail
APP_DIR="$1"
DEPLOY_SERVICES="$2"
cd "$APP_DIR"
sudo docker compose up -d --build $DEPLOY_SERVICES
REMOTE_DEPLOY

echo "Verifying remote runtime..."
ssh -i "$AWS_SSH_KEY" -o StrictHostKeyChecking=accept-new "$AWS_USER@$AWS_HOST" bash -s -- "$AWS_APP_DIR" "$DOMAIN" <<'REMOTE_VERIFY'
set -euo pipefail
APP_DIR="$1"
DOMAIN="$2"
cd "$APP_DIR"
sudo nginx -t >/tmp/nginx-check.out 2>&1
cat /tmp/nginx-check.out
sudo docker compose ps
echo HEALTH
curl -sS "https://$DOMAIN/health"
echo
echo LOGIN
curl -I -sS "https://$DOMAIN/login" | head -n 12
REMOTE_VERIFY
