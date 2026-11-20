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
# `pct enter` gives a minimal PATH without /usr/local/sbin — link it into /usr/sbin too
ln -sf /usr/local/sbin/weather-web-deploy /usr/sbin/weather-web-deploy

# ── Radar worker (DMI radar → PNG frames) ────────────────────────────────
echo "==> Radar worker"
dpkg -s python3-venv >/dev/null 2>&1 || apt-get install -y -qq python3-venv
id weatherradar >/dev/null 2>&1 || useradd --system --no-create-home --shell /usr/sbin/nologin weatherradar
install -d -m 0755 -o weatherradar -g weatherradar /var/lib/weather-web/radar
install -d -m 0755 /opt/weather-web/radar
install -m 0644 radar/radar_worker.py radar/requirements.txt /opt/weather-web/radar/
[[ -f /etc/weather-web/radar.ini ]] || install -m 0644 radar/radar.example.ini /etc/weather-web/radar.ini
if [[ ! -x /opt/weather-web/radar-venv/bin/python3 ]]; then
  python3 -m venv /opt/weather-web/radar-venv
fi
REQ_HASH=$(sha256sum radar/requirements.txt | cut -d' ' -f1)
if [[ "$(cat /opt/weather-web/radar-venv/.req-hash 2>/dev/null)" != "$REQ_HASH" ]]; then
  /opt/weather-web/radar-venv/bin/pip install -q --upgrade pip
  /opt/weather-web/radar-venv/bin/pip install -q -r radar/requirements.txt
  echo "$REQ_HASH" >/opt/weather-web/radar-venv/.req-hash
fi
UNITS_CHANGED=0
for u in deploy/systemd/weather-radar.service deploy/systemd/weather-radar.timer; do
  if ! cmp -s "$u" "/etc/systemd/system/$(basename "$u")"; then
    install -m 0644 "$u" /etc/systemd/system/
    UNITS_CHANGED=1
  fi
done
[[ $UNITS_CHANGED == 1 ]] && systemctl daemon-reload
systemctl enable --now weather-radar.timer >/dev/null
# Render once now so the map has a frame right after a fresh install
systemctl start --no-block weather-radar.service

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
