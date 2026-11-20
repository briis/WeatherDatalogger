#!/usr/bin/env bash
# deploy.sh — Pull the latest web/ from GitHub, build it, and switch the live
#             site over atomically. Installed as /usr/local/sbin/weather-web-deploy.
#
# Usage (as root in the LXC):
#   weather-web-deploy              # branch from /etc/weather-web/env (default main)
#   weather-web-deploy my-branch    # try a feature branch
#
# Each build lands in /var/www/weather/releases/<timestamp>-<sha>; the
# `current` symlink is swapped only after a successful build, so a failed
# build never takes the site down. The last 5 releases are kept for rollback:
#   ln -sfn /var/www/weather/releases/<older> /var/www/weather/current

set -euo pipefail

ENV_FILE=/etc/weather-web/env
WEB_ROOT=/var/www/weather
SRC_DIR=/opt/weather-web/src
KEEP=5

# shellcheck disable=SC1090
[[ -f "$ENV_FILE" ]] && source "$ENV_FILE"
BRANCH="${1:-${WEATHER_BRANCH:-main}}"

echo "==> Updating source ($BRANCH)"
git -C "$SRC_DIR" fetch --depth 1 origin "$BRANCH"
git -C "$SRC_DIR" checkout -q -B "$BRANCH" FETCH_HEAD
SHA=$(git -C "$SRC_DIR" rev-parse --short HEAD)

echo "==> Building $SHA"
cd "$SRC_DIR/web"
npm ci --no-audit --no-fund --loglevel=error
npm run build

# Keep Caddyfile in sync with the repo; reload only if it changed
if ! cmp -s deploy/Caddyfile /etc/caddy/Caddyfile; then
  install -m 0644 deploy/Caddyfile /etc/caddy/Caddyfile
  caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile >/dev/null
  RELOAD_CADDY=1
fi
install -m 0755 deploy/deploy.sh /usr/local/sbin/weather-web-deploy

RELEASE="$WEB_ROOT/releases/$(date +%Y%m%d-%H%M%S)-$SHA"
rsync -a --delete dist/ "$RELEASE/"
VERSION=$(cat package.json | grep -m1 '"version"' | cut -d'"' -f4)
echo "$VERSION ($SHA, $BRANCH) $(date -Iseconds)" >"$RELEASE/VERSION.txt"

ln -sfn "$RELEASE" "$WEB_ROOT/current.tmp"
mv -T "$WEB_ROOT/current.tmp" "$WEB_ROOT/current"
[[ "${RELOAD_CADDY:-}" == 1 ]] && systemctl reload caddy

# Prune old releases
ls -1dt "$WEB_ROOT"/releases/*/ | tail -n +$((KEEP + 1)) | xargs -r rm -rf

echo "==> Live: $(cat "$WEB_ROOT/current/VERSION.txt")"
