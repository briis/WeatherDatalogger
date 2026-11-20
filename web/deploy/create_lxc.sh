#!/usr/bin/env bash
# create_lxc.sh — Create the weather-web LXC on the Proxmox host.
#
# Run as root on the Proxmox host (not inside a container):
#   bash create_lxc.sh [CTID] [HOSTNAME]
#
# Defaults: unprivileged Debian 13, 1 vCPU, 512 MB RAM, 4 GB disk, DHCP on
# vmbr0, started on boot. Override any of the variables below via the
# environment, e.g.  CTID=215 IP=192.168.1.215/24 GW=192.168.1.1 bash create_lxc.sh
#
# Building the frontend (npm ci + vite build) peaks at ~400 MB; 512 MB is
# enough, the site itself idles at ~30 MB.

set -euo pipefail

CTID="${1:-${CTID:-$(pvesh get /cluster/nextid)}}"
HOSTNAME="${2:-${HOSTNAME_CT:-weather-web}}"
STORAGE="${STORAGE:-local-lvm}"
TEMPLATE_STORAGE="${TEMPLATE_STORAGE:-local}"
BRIDGE="${BRIDGE:-vmbr0}"
IP="${IP:-dhcp}"           # or e.g. 192.168.1.215/24
GW="${GW:-}"               # required when IP is static
CORES="${CORES:-1}"
MEMORY="${MEMORY:-512}"
SWAP="${SWAP:-512}"
DISK_GB="${DISK_GB:-4}"
SSH_KEY_FILE="${SSH_KEY_FILE:-/root/.ssh/authorized_keys}"
BRANCH="${BRANCH:-main}"   # e.g. BRANCH=feature/web-phase1 before the PR is merged

echo "==> Finding latest Debian 13 template"
pveam update >/dev/null
TEMPLATE="$(pveam available --section system | awk '/debian-13-standard/ {print $2}' | sort -V | tail -1)"
[[ -n "$TEMPLATE" ]] || { echo "No debian-13-standard template found"; exit 1; }
if ! pveam list "$TEMPLATE_STORAGE" | grep -q "$TEMPLATE"; then
  pveam download "$TEMPLATE_STORAGE" "$TEMPLATE"
fi

NET="name=eth0,bridge=$BRIDGE,ip=$IP"
[[ "$IP" != "dhcp" && -n "$GW" ]] && NET="$NET,gw=$GW"

echo "==> Creating CT $CTID ($HOSTNAME)"
pct create "$CTID" "$TEMPLATE_STORAGE:vztmpl/$TEMPLATE" \
  --hostname "$HOSTNAME" \
  --unprivileged 1 \
  --features nesting=1 \
  --cores "$CORES" \
  --memory "$MEMORY" \
  --swap "$SWAP" \
  --rootfs "$STORAGE:$DISK_GB" \
  --net0 "$NET" \
  --onboot 1 \
  --timezone Europe/Copenhagen \
  --description "Vejret — WeatherDatalogger web frontend (Caddy). See web/README.md in briis/WeatherDatalogger." \
  ${SSH_KEY_FILE:+--ssh-public-keys "$SSH_KEY_FILE"}

pct start "$CTID"
sleep 5

echo "==> Bootstrapping"
pct exec "$CTID" -- bash -c "apt-get update -qq && apt-get install -y -qq curl ca-certificates"
pct exec "$CTID" -- bash -c \
  "curl -fsSL https://raw.githubusercontent.com/briis/WeatherDatalogger/$BRANCH/web/deploy/install.sh -o /root/install.sh"

cat <<EOF

CT $CTID is running. Finish setup inside it:

  pct enter $CTID
  BRANCH=$BRANCH bash /root/install.sh

EOF
