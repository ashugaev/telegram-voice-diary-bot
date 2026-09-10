#!/bin/bash
# Pull the new version from origin/main and restart the systemd user service.
# Run by cron. Cron has no shell env: PATH, HOME and DBUS are set explicitly.

set -u

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERVICE=diary-bot.service

export HOME="${HOME:-$(getent passwd "$(id -un)" | cut -d: -f6)}"
export PATH="/usr/local/bin:/usr/bin:/bin"
export XDG_RUNTIME_DIR="/run/user/$(id -u)"
export DBUS_SESSION_BUS_ADDRESS="unix:path=$XDG_RUNTIME_DIR/bus"
export GIT_SSH_COMMAND="ssh -o BatchMode=yes -i $HOME/.ssh/id_ed25519"

cd "$APP_DIR" || exit 1

log() { echo "[$(date -u +%FT%TZ)] $*"; }

branch="$(git rev-parse --abbrev-ref HEAD)"
if [ "$branch" != "main" ]; then
  log "skip: on branch $branch, not main"
  exit 0
fi

if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
  log "skip: working tree dirty"
  exit 0
fi

git fetch --quiet origin main || { log "FAIL: fetch"; exit 1; }

local_sha="$(git rev-parse HEAD)"
remote_sha="$(git rev-parse origin/main)"
[ "$local_sha" = "$remote_sha" ] && exit 0

req_before="$(sha256sum requirements.txt | awk '{print $1}')"
git merge --ff-only origin/main || { log "FAIL: ff-only merge $local_sha -> $remote_sha"; exit 1; }
req_after="$(sha256sum requirements.txt | awk '{print $1}')"

if [ "$req_before" != "$req_after" ]; then
  .venv/bin/python -m pip install -q -r requirements.txt || { log "FAIL: pip install"; exit 1; }
  log "deps updated"
fi

if systemctl --user restart "$SERVICE"; then
  log "updated ${local_sha:0:7} -> ${remote_sha:0:7}, service restarted"
else
  log "FAIL: restart after ${local_sha:0:7} -> ${remote_sha:0:7}"
  exit 1
fi
