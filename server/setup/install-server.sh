#!/usr/bin/env bash
##############################################################################
# install-server.sh — Bootstrap AlleycaTV inside the LXC container
#
# Installs: nginx, Python 3 venv, FastAPI/uvicorn, paho-mqtt, protobuf
# Creates:  /opt/alleycatv/ directory structure
# Deploys:  systemd service + nginx config
#
# Run as root inside the container.
##############################################################################
set -euo pipefail

INSTALL_DIR="/opt/alleycatv"
APP_SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/app"
SERVICE_SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/alleycatv-server.service"
NGINX_SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/nginx/alleycatv.conf"

echo "=== AlleycaTV Server Install ==="

# ── System packages ───────────────────────────────────────────────────────────
apt-get update -qq
apt-get install -y --no-install-recommends \
    nginx python3 python3-pip python3-venv curl

# ── Create system user ────────────────────────────────────────────────────────
if ! id alleycatv &>/dev/null; then
    useradd --system --no-create-home --shell /usr/sbin/nologin alleycatv
fi

# ── Directory structure ───────────────────────────────────────────────────────
mkdir -p "$INSTALL_DIR"/{media/{videos,photos,announcements},server,venv}
chown -R alleycatv:alleycatv "$INSTALL_DIR"

# ── Python venv + dependencies ────────────────────────────────────────────────
python3 -m venv "$INSTALL_DIR/venv"
"$INSTALL_DIR/venv/bin/pip" install --upgrade pip -q
"$INSTALL_DIR/venv/bin/pip" install -r "$APP_SRC/requirements.txt" -q

# Copy proto bindings to where the server can import them
cp "$(dirname "$APP_SRC")/../proto/alleycatv_pb2.py" "$INSTALL_DIR/server/"

# ── Copy application files ────────────────────────────────────────────────────
cp -r "$APP_SRC" "$INSTALL_DIR/server/"
chown -R alleycatv:alleycatv "$INSTALL_DIR/server"

# ── nginx ─────────────────────────────────────────────────────────────────────
cp "$NGINX_SRC" /etc/nginx/sites-available/alleycatv
ln -sf /etc/nginx/sites-available/alleycatv /etc/nginx/sites-enabled/alleycatv
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl enable --now nginx

# ── systemd service ───────────────────────────────────────────────────────────
cp "$SERVICE_SRC" /etc/systemd/system/alleycatv-server.service
systemctl daemon-reload
systemctl enable alleycatv-server
systemctl start alleycatv-server

echo ""
echo "=== Done ==="
echo "Service status:"
systemctl status alleycatv-server --no-pager || true
echo ""
echo "Edit MQTT broker IP in: $INSTALL_DIR/server/app/config.py"
echo "Then restart: systemctl restart alleycatv-server"
