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

echo "==> Checking prerequisites"
if pct status "$CTID" >/dev/null 2>&1; then
  echo "CT $CTID already exists — pick another ID (pct list)"; exit 1
fi
if ! pvesm status --content rootdir 2>/dev/null | awk 'NR>1 {print $1}' | grep -qx "$STORAGE"; then
  echo "Storage '$STORAGE' can't hold containers. Available:"
  pvesm status --content rootdir | awk 'NR>1 {print "  " $1}'
  echo "Re-run with STORAGE=<name>"; exit 1
fi
if ! pvesm status --content vztmpl 2>/dev/null | awk 'NR>1 {print $1}' | grep -qx "$TEMPLATE_STORAGE"; then
  echo "Storage '$TEMPLATE_STORAGE' can't hold templates. Available:"
  pvesm status --content vztmpl | awk 'NR>1 {print "  " $1}'
  echo "Re-run with TEMPLATE_STORAGE=<name>"; exit 1
fi
SSH_ARGS=()
if [[ -s "$SSH_KEY_FILE" ]]; then
  SSH_ARGS=(--ssh-public-keys "$SSH_KEY_FILE")
else
  echo "    (no $SSH_KEY_FILE — creating without SSH keys; add yours to /root/.ssh/authorized_keys in the CT later)"
fi
echo "    CT $CTID on $STORAGE, template from $TEMPLATE_STORAGE"

echo "==> Finding latest Debian 13 template"
pveam update >/dev/null
# pveam lists every architecture — pick the host's (amd64/arm64), never "the
# last one", or the CT fails to start with "Exec format error"
ARCH="$(dpkg --print-architecture)"
TEMPLATE="$(pveam available --section system | awk -v a="_${ARCH}.tar" '/debian-13-standard/ && index($2, a) {print $2}' | sort -V | tail -1)"
[[ -n "$TEMPLATE" ]] || { echo "No debian-13-standard template for $ARCH found"; exit 1; }
echo "    $TEMPLATE"
if ! pveam list "$TEMPLATE_STORAGE" | grep -q "$TEMPLATE"; then
  pveam download "$TEMPLATE_STORAGE" "$TEMPLATE"
fi

NET="name=eth0,bridge=$BRIDGE,ip=$IP"
[[ "$IP" != "dhcp" && -n "$GW" ]] && NET="$NET,gw=$GW"

echo "==> Creating CT $CTID ($HOSTNAME)"
trap 'echo "!! Failed at line $LINENO — see the error above"' ERR
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
  "${SSH_ARGS[@]}"

pct start "$CTID"
echo "==> Waiting for network"
for _ in $(seq 1 30); do
  pct exec "$CTID" -- getent hosts deb.debian.org >/dev/null 2>&1 && break
  sleep 2
done

echo "==> Bootstrapping"
pct exec "$CTID" -- bash -c "apt-get update -qq && apt-get install -y -qq curl ca-certificates"
pct exec "$CTID" -- bash -c \
  "curl -fsSL https://raw.githubusercontent.com/briis/WeatherDatalogger/$BRANCH/web/deploy/install.sh -o /root/install.sh"

cat <<EOF

CT $CTID is running. Finish setup inside it:

  pct enter $CTID
  BRANCH=$BRANCH bash /root/install.sh

EOF
