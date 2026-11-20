#!/usr/bin/env bash
# push_from_mac.sh — Build locally and push straight to the weather-web LXC,
#                    bypassing GitHub. Handy for trying changes before a PR.
#
# Usage (from the repo's web/ directory or anywhere inside the repo):
#   web/deploy/push_from_mac.sh root@192.168.1.215
#
# Requires SSH key access to the LXC. Uses the same release/symlink layout
# as deploy.sh, so `weather-web-deploy` on the LXC afterwards returns the
# site to what's on GitHub.

set -euo pipefail

TARGET="${1:?usage: push_from_mac.sh user@host}"
cd "$(dirname "$0")/.."

SHA=$(git rev-parse --short HEAD 2>/dev/null || echo local)
git diff --quiet 2>/dev/null || SHA="$SHA-dirty"
RELEASE="/var/www/weather/releases/$(date +%Y%m%d-%H%M%S)-$SHA"

echo "==> Building ($SHA)"
npm ci --no-audit --no-fund --loglevel=error
npm run build
VERSION=$(grep -m1 '"version"' package.json | cut -d'"' -f4)
echo "$VERSION ($SHA, pushed from $(hostname -s)) $(date -Iseconds)" >dist/VERSION.txt

echo "==> Uploading to $TARGET:$RELEASE"
ssh "$TARGET" "mkdir -p '$RELEASE'"
rsync -az --delete dist/ "$TARGET:$RELEASE/"
ssh "$TARGET" "ln -sfn '$RELEASE' /var/www/weather/current.tmp && mv -T /var/www/weather/current.tmp /var/www/weather/current && cat /var/www/weather/current/VERSION.txt"
