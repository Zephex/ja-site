#!/usr/bin/env bash
# Run this ON the server, from inside the uploaded ja-site folder.
#
#   cd /tmp/ja-site && ./install-server.sh
#   cd /tmp/ja-site && ./install-server.sh /opt/ja-site
#
# Optional: JA_PORT=8080 JA_BASE_URL=https://invites.example.com SKIP_CADDY=1 ./install-server.sh

set -euo pipefail

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Run this as root (sudo ./install-server.sh)." >&2
  exit 1
fi

TARGET="${1:-/opt/ja-site}"
PORT="${JA_PORT:-8080}"
BASE_URL="${JA_BASE_URL:-https://invites.example.com}"
SKIP_CADDY="${SKIP_CADDY:-0}"
SERVICE_NAME="ja-site"
SERVICE_USER="jasite"
SOURCE="$(pwd)"

[[ -f "$SOURCE/app/server.py" ]] || { echo "Run this from the ja-site folder." >&2; exit 1; }

say() { printf '\n==> %s\n' "$1"; }

say "Installing $SOURCE into $TARGET"
mkdir -p "$TARGET/storage/uploads"
chmod 700 "$TARGET/storage" "$TARGET/storage/uploads"

if ! tar czf - -C "$SOURCE" --exclude=storage --exclude='__pycache__' --exclude='*.pyc' . | tar xzf - -C "$TARGET"; then
  echo "Copy failed." >&2
  exit 1
fi
chmod +x "$TARGET/run.sh"

if ! id "$SERVICE_USER" >/dev/null 2>&1; then
  useradd --system --no-create-home --shell /usr/sbin/nologin "$SERVICE_USER" || SERVICE_USER="root"
fi
chown -R "$SERVICE_USER":"$SERVICE_USER" "$TARGET" 2>/dev/null || true

PYTHON_PATH="$(command -v python3 || command -v python)"
[[ -n "$PYTHON_PATH" ]] || { echo "python3 not found." >&2; exit 1; }

say "Writing systemd service"
tee /etc/systemd/system/$SERVICE_NAME.service > /dev/null <<UNIT
[Unit]
Description=invites.example.com invite pages
After=network.target

[Service]
Type=simple
User=$SERVICE_USER
WorkingDirectory=$TARGET
Environment=JA_HOST=127.0.0.1
Environment=JA_PORT=$PORT
Environment=JA_BASE_URL=$BASE_URL
ExecStart=$PYTHON_PATH -m app.server
Restart=on-failure
RestartSec=3

NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=$TARGET/storage
RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX
RestrictSUIDSGID=true
LockPersonality=true

[Install]
WantedBy=multi-user.target
UNIT

systemctl daemon-reload
systemctl enable --now "$SERVICE_NAME" || true

say "Checking local response"
curl -s -o /dev/null -w 'HTTP %{http_code}\n' "http://127.0.0.1:$PORT/" || echo "curl missing (not a problem)"

CADDY_DONE=0
if [[ "$SKIP_CADDY" == "0" ]]; then
  CADDY_FILE=""
  for candidate in /etc/caddy/Caddyfile /opt/caddy/Caddyfile /etc/caddy/Caddyfile.d/ja.caddy; do
    if [[ -f "$candidate" ]]; then CADDY_FILE="$candidate"; break; fi
  done
  if [[ -n "$CADDY_FILE" ]]; then
    if grep -q 'invites.example.com' "$CADDY_FILE"; then
      say "Caddyfile already has invites.example.com — skipping"
      CADDY_DONE=1
    else
      say "Adding Caddy block to $CADDY_FILE (backup saved as .bak-ja)"
      cp "$CADDY_FILE" "$CADDY_FILE.bak-ja"
      cat >> "$CADDY_FILE" <<SNIPPET

invites.example.com {
    encode zstd gzip
    reverse_proxy 127.0.0.1:$PORT
}
SNIPPET
      if command -v caddy >/dev/null 2>&1 && caddy validate --config "$CADDY_FILE" && systemctl reload caddy; then
        CADDY_DONE=1
      else
        echo "Caddy validation/reload failed; check $CADDY_FILE" >&2
      fi
    fi
  fi
fi

cat <<DONE

==================================================================
Installed to $TARGET
DONE
if [[ "$CADDY_DONE" == "0" ]]; then
  cat <<DONE

Add this to your Caddyfile and reload Caddy:

   invites.example.com {
       encode zstd gzip
       reverse_proxy 127.0.0.1:$PORT
   }

   caddy validate --config /etc/caddy/Caddyfile && systemctl reload caddy
DONE
fi
cat <<DONE

Remaining steps:
  1. DNS: point invites.example.com at this server.
  2. Open https://invites.example.com/admin/setup once to create your admin login.

Check: systemctl status $SERVICE_NAME
Logs:  journalctl -u $SERVICE_NAME -f
==================================================================
DONE
