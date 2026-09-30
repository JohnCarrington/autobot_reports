#!/usr/bin/env bash
# scripts/init_filesystem.sh — provision autobot output directories
# with correct ownership.
#
# Idempotent. Run once on a fresh droplet, after a restore from backup,
# or after any operation that creates directories under /opt/tradingbot
# as root (e.g. a tarball extracted as root). The autobot service runs
# as the unprivileged 'autobot' user; root-owned output directories
# silently break write paths.
#
# Reads the canonical directory list from filesystem_paths.py so this
# script and autobot.py agree on what counts as an output directory.
#
# Usage:
#   sudo bash /opt/tradingbot/scripts/init_filesystem.sh

set -euo pipefail

ROOT="/opt/tradingbot"
USER_NAME="autobot"
GROUP_NAME="autobot"
DIR_MODE="0775"

if [[ $EUID -ne 0 ]]; then
  echo "must run as root (chown requires it)" >&2
  exit 1
fi

if ! id -u "$USER_NAME" >/dev/null 2>&1; then
  echo "user '$USER_NAME' does not exist on this host" >&2
  exit 1
fi

# Pull the canonical list from filesystem_paths.py — single source of
# truth shared with autobot.py. cd into ROOT so the import resolves.
mapfile -t DIRS < <(
  cd "$ROOT" && "$ROOT/venv/bin/python" -c "
from filesystem_paths import OUTPUT_DIRECTORIES
for d in OUTPUT_DIRECTORIES:
    print(d)
"
)

if [[ ${#DIRS[@]} -eq 0 ]]; then
  echo "filesystem_paths.OUTPUT_DIRECTORIES returned no entries — aborting" >&2
  exit 1
fi

count=0
for d in "${DIRS[@]}"; do
  mkdir -p "$d"
  chown "$USER_NAME:$GROUP_NAME" "$d"
  chmod "$DIR_MODE" "$d"
  count=$((count + 1))
done

echo "filesystem initialized: ${count} directories ready for ${USER_NAME} user"
