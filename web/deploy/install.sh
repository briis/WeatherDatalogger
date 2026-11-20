#!/usr/bin/env bash
# install.sh — One-time setup inside the weather-web LXC (Debian 13).
#
# Run as root inside the container:
#   bash install.sh
#
# Installs Caddy + Node.js (Debian packages — Node 20.19 meets Vite's
# requirement), creates /etc/weather-web/env with the API upstream and key,
# installs the Caddyfile, and runs the first deploy from GitHub.
# Re-running is safe: existing env values are kept.

set -euo pipefail

ENV_DIR=/etc/weather-web
ENV_FILE="$ENV_DIR/env"
WEB_ROOT=/var/www/weather
SRC_DIR=/opt/weather-web/src
REPO_URL="${REPO_URL:-https://github.com/briis/WeatherDatalogger.git}"
BRANCH="${BRANCH:-main}"

[[ $EUID -eq 0 ]] || { echo "Run as root"; exit 1; }

echo "==> Installing packages"
apt-get update -qq
apt-get install -y -qq caddy nodejs npm git rsync curl ca-certificates

# `pct enter` passes the host's LANG (usually en_US.UTF-8) into the CT, where
# it isn't generated → "Can't set locale" warnings from apt/perl. Generate it.
apt-get install -y -qq locales
sed -i 's/^# *\(en_US.UTF-8\)/\1/; s/^# *\(da_DK.UTF-8\)/\1/' /etc/locale.gen
locale-gen >/dev/null
update-locale LANG=en_US.UTF-8

echo "==> Directories"
install -d -m 0755 "$WEB_ROOT/releases" /opt/weather-web
install -d -m 0750 -o root -g caddy "$ENV_DIR"

if [[ ! -f "$ENV_FILE" ]]; then
  read -rp "WeatherDatalogger API host:port (e.g. 192.168.1.50:8000): " UPSTREAM
  read -rsp "API key ([api] api_key in the datalogger's config.ini): " KEY; echo
  cat >"$ENV_FILE" <<EOF
# Read by Caddy (systemd EnvironmentFile) — see web/deploy/Caddyfile
WEATHER_API_UPSTREAM=$UPSTREAM
WEATHER_API_KEY=$KEY
WEATHER_SITE_ADDRESS=:80
# Branch deploy.sh builds from
WEATHER_BRANCH=$BRANCH
EOF
  chown root:caddy "$ENV_FILE"
  chmod 0640 "$ENV_FILE"
fi

echo "==> Caddy environment drop-in"
install -d /etc/systemd/system/caddy.service.d
cat >/etc/systemd/system/caddy.service.d/weather-web.conf <<EOF
[Service]
EnvironmentFile=$ENV_FILE
EOF
systemctl daemon-reload

echo "==> Fetching source"
if [[ -d "$SRC_DIR/.git" ]]; then
  git -C "$SRC_DIR" fetch --depth 1 origin "$BRANCH"
  git -C "$SRC_DIR" reset --hard "origin/$BRANCH"
else
  git clone --depth 1 --branch "$BRANCH" --filter=blob:none --sparse "$REPO_URL" "$SRC_DIR"
  git -C "$SRC_DIR" sparse-checkout set web VERSION
fi

install -m 0644 "$SRC_DIR/web/deploy/Caddyfile" /etc/caddy/Caddyfile
install -m 0755 "$SRC_DIR/web/deploy/deploy.sh" /usr/local/sbin/weather-web-deploy
# `pct enter` gives a minimal PATH without /usr/local/sbin — link it into /usr/sbin too
ln -sf /usr/local/sbin/weather-web-deploy /usr/sbin/weather-web-deploy

echo "==> First deploy"
/usr/local/sbin/weather-web-deploy

systemctl enable --now caddy
systemctl reload-or-restart caddy

IP=$(hostname -I | awk '{print $1}')
cat <<EOF

Done. Open http://$IP/ on your LAN.

  Update later:     weather-web-deploy               (from GitHub, branch in $ENV_FILE)
  Or from your Mac: web/deploy/push_from_mac.sh root@$IP
  Logs:             journalctl -u caddy -f
EOF
