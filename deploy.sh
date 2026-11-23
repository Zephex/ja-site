#!/usr/bin/env bash
# Upload ja-site to your server over SSH and install it.
#
# Usage:
#   ./deploy.sh [ssh-target] [remote-directory]
#
# The SSH target comes from argument 1 or JA_SSH in a local .deploy.env file
# (copy .deploy.env.example; .deploy.env is gitignored). Optional overrides:
#   JA_REMOTE_DIR       remote folder (default /opt/ja-site)
#   JA_BASE_URL=https://invites.example.com
#   JA_PORT=8080
#   SKIP_CADDY=1        (do not touch the Caddyfile automatically)

set -euo pipefail

LOCAL_DIR="$(cd "$(dirname "$0")" && pwd)"
if [[ -f "$LOCAL_DIR/.deploy.env" ]]; then
  # shellcheck disable=SC1091
  set -a
  . "$LOCAL_DIR/.deploy.env"
  set +a
fi

SERVER="${1:-${JA_SSH:-}}"
REMOTE_DIR="${2:-${JA_REMOTE_DIR:-/opt/ja-site}}"
BASE_URL="${JA_BASE_URL:-https://invites.example.com}"
PORT="${JA_PORT:-8080}"
SKIP_CADDY="${SKIP_CADDY:-0}"
SERVICE_NAME="ja-site"
SERVICE_USER="jasite"

if [[ "$SERVER" == "-h" || "$SERVER" == "--help" ]]; then
  cat <<'USAGE'
Usage: ./deploy.sh [ssh-target] [remote-directory]

ssh-target: an alias from ~/.ssh/config, or user@host.
            Set JA_SSH in .deploy.env to make it the default.

Defaults:
  remote folder:  /opt/ja-site
  public URL:     https://invites.example.com
  local port:     8080

Examples:
  cp .deploy.env.example .deploy.env   # then set JA_SSH
  ./deploy.sh
  ./deploy.sh user@server /opt/ja-site
  JA_PORT=8090 ./deploy.sh

It copies the app over SSH, creates a dedicated service user, installs and
starts the systemd service, and adds the Caddy block if it finds the Caddyfile.
USAGE
  exit 0
fi

if [[ -z "$SERVER" ]]; then
  echo "No SSH target. Set JA_SSH in .deploy.env or pass one: ./deploy.sh user@server" >&2
  exit 1
fi

say() { printf '\n==> %s\n' "$1"; }

if command -v git >/dev/null 2>&1 && git -C "$LOCAL_DIR" rev-parse --git-dir >/dev/null 2>&1; then
  if [[ -n "$(git -C "$LOCAL_DIR" status --porcelain)" ]]; then
    say "Warning: $LOCAL_DIR has uncommitted changes — deploying the working tree, not the last commit"
  else
    say "Deploying $(git -C "$LOCAL_DIR" rev-parse --short HEAD) from $LOCAL_DIR"
  fi
fi

say "Connecting to $SERVER"
if ! ssh -o BatchMode=yes -o ConnectTimeout=10 "$SERVER" 'echo ok' >/dev/null 2>&1; then
  echo "Could not log in as $SERVER without a password." >&2
  echo "Fix SSH key access first, e.g.: ssh-copy-id $SERVER" >&2
  exit 1
fi

REMOTE_USER="$(ssh "$SERVER" 'whoami' | tr -d '\r')"
if [[ "$REMOTE_USER" == "root" ]]; then SUDO=""; else SUDO="sudo"; fi
say "Logged in as $REMOTE_USER; installing into $REMOTE_DIR"

say "Preparing directories and service user"
ssh "$SERVER" "mkdir -p '$REMOTE_DIR/storage/uploads' && chmod 700 '$REMOTE_DIR/storage' '$REMOTE_DIR/storage/uploads'"
if [[ "$SERVICE_USER" != "$REMOTE_USER" ]]; then
  ssh "$SERVER" "id '$SERVICE_USER' >/dev/null 2>&1 || useradd --system --no-create-home --shell /usr/sbin/nologin '$SERVICE_USER'" || \
    echo "Could not create $SERVICE_USER; will run the service as $REMOTE_USER." >&2
fi

say "Uploading files (existing storage/ is preserved)"
if command -v rsync >/dev/null 2>&1; then
  rsync -avz \
    --exclude 'storage/' \
    --exclude '.git/' \
    --exclude '.gitignore' \
    --exclude '.env' \
    --exclude '.env.*' \
    --exclude '.deploy.env' \
    --exclude '.venv/' \
    --exclude 'venv/' \
    --exclude '__pycache__/' \
    --exclude '*.pyc' \
    --exclude '*.log' \
    "$LOCAL_DIR/" "$SERVER:$REMOTE_DIR/"
else
  echo "rsync not available locally; using tar over SSH."
  tar czf - -C "$LOCAL_DIR" \
    --exclude=storage --exclude=.git --exclude=.gitignore \
    --exclude=.env --exclude='.env.*' --exclude=.deploy.env --exclude=.venv --exclude=venv \
    --exclude='__pycache__' --exclude='*.pyc' --exclude='*.log' . \
    | ssh "$SERVER" "tar xzf - -C '$REMOTE_DIR'"
fi

ssh "$SERVER" "chmod +x '$REMOTE_DIR/run.sh' && chown -R '$SERVICE_USER':'$SERVICE_USER' '$REMOTE_DIR' 2>/dev/null || true"

PYTHON_PATH="$(ssh "$SERVER" 'command -v python3 || command -v python' | tail -n 1 | tr -d '\r')"
[[ -n "$PYTHON_PATH" ]] || { echo "python3 not found on the server." >&2; exit 1; }

say "Installing systemd service"
ssh -t "$SERVER" "$SUDO tee /etc/systemd/system/$SERVICE_NAME.service > /dev/null" <<UNIT
[Unit]
Description=invites.example.com invite pages
After=network.target

[Service]
Type=simple
User=$SERVICE_USER
WorkingDirectory=$REMOTE_DIR
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
ReadWritePaths=$REMOTE_DIR/storage
RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX
RestrictSUIDSGID=true
LockPersonality=true

[Install]
WantedBy=multi-user.target
UNIT

ssh -t "$SERVER" "$SUDO systemctl daemon-reload && $SUDO systemctl enable --now $SERVICE_NAME && systemctl status $SERVICE_NAME --no-pager -l" || true

say "Checking the app locally on the server"
ssh "$SERVER" "curl -s -o /dev/null -w 'HTTP %{http_code}\n' http://127.0.0.1:$PORT/ || echo 'curl not installed (not a problem)'"

CADDY_DONE=0
if [[ "$SKIP_CADDY" == "0" ]]; then
  CADDY_FILE="$(ssh "$SERVER" "for f in /etc/caddy/Caddyfile /opt/caddy/Caddyfile /etc/caddy/Caddyfile.d/ja.caddy; do [ -f \"\$f\" ] && echo \"\$f\" && break; done" | head -n 1 | tr -d '\r')"
  if [[ -n "$CADDY_FILE" ]]; then
    if ssh "$SERVER" "grep -q 'invites.example.com' '$CADDY_FILE'"; then
      say "Caddyfile already mentions invites.example.com — leaving it alone"
      CADDY_DONE=1
    else
      say "Adding Caddy block to $CADDY_FILE (backup saved)"
      ssh "$SERVER" "cat > /tmp/ja-caddy-snippet" <<SNIPPET

invites.example.com {
    encode zstd gzip
    reverse_proxy 127.0.0.1:$PORT
}
SNIPPET
      if ssh -t "$SERVER" "$SUDO cp '$CADDY_FILE' '$CADDY_FILE.bak-ja' && $SUDO tee -a '$CADDY_FILE' < /tmp/ja-caddy-snippet > /dev/null && $SUDO caddy validate --config '$CADDY_FILE' && $SUDO systemctl reload caddy"; then
        CADDY_DONE=1
      else
        echo "Caddy update failed; add the block manually (see below)." >&2
      fi
    fi
  fi
fi

cat <<DONE

==================================================================
Deploy finished.
DONE
if [[ "$CADDY_DONE" == "0" ]]; then
  cat <<DONE

Add this to your Caddyfile yourself, then reload Caddy:

   invites.example.com {
       encode zstd gzip
       reverse_proxy 127.0.0.1:$PORT
   }

   caddy validate --config /etc/caddy/Caddyfile
   systemctl reload caddy
DONE
fi
cat <<DONE

Remaining steps:
  1. DNS: point invites.example.com at $SERVER (same IP as your main site is fine).
  2. Open https://invites.example.com/admin/setup once to create your admin login.
  3. Then create accounts and invite links in /admin.

On the server:
   systemctl status $SERVICE_NAME
   systemctl restart $SERVICE_NAME
   journalctl -u $SERVICE_NAME -f
==================================================================
DONE
