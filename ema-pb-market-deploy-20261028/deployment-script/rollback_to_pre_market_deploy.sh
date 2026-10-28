#!/bin/bash
#
# EMA Pullback → rollback to pre-market-deploy baseline.
# Reverses the controlled-demo deployment of cff4718, restoring the
# source tree captured in /opt/ema_pullback/backups/pre-market-deploy-20261029T190000Z.
#
# USAGE
#   sudo -u autobot /opt/ema_pullback/venv/bin/bash \
#       rollback_to_pre_market_deploy.sh [--restart]
#
# The script DOES NOT auto-cancel broker positions or working orders.
# The user's instruction is explicit: "Do not cancel or close existing
# broker positions merely to complete rollback." If positions are open,
# the operator reviews them separately via the inventory_tool CLI and
# IG dealing endpoints.
#
set -euo pipefail

readonly BACKUP=/opt/ema_pullback/backups/pre-market-deploy-20261029T190000Z
readonly DST=/opt/ema_pullback
readonly EXPECTED_BACKUP_LIST_HASH="9f331107f96bd0aade042fe605e71c09190fbf9ee41b0110601f721daae80c91"

OPT_RESTART=false
for arg in "$@"; do
    case "$arg" in
        --restart) OPT_RESTART=true ;;
        *) echo "unknown arg: $arg" >&2; exit 2 ;;
    esac
done

log() { printf '%s %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$*"; }
die() { printf 'ABORT: %s\n' "$*" >&2; exit 1; }

[[ "$(whoami)" == "autobot" ]] || die "run as autobot"
[[ -d "$BACKUP/ema_pullback" ]] || die "backup tree not found at $BACKUP"

# Verify the backup is intact (same file set + hashes as recorded).
tmp=$(mktemp)
find "$BACKUP" -type f -not -path '*__pycache__*' | sort | xargs sha256sum > "$tmp"
backup_list_hash=$(sha256sum "$tmp" | awk '{print $1}')
rm -f "$tmp"
[[ "$backup_list_hash" == "$EXPECTED_BACKUP_LIST_HASH" ]] \
    || die "backup composite hash mismatch\n  wanted: $EXPECTED_BACKUP_LIST_HASH\n  actual: $backup_list_hash"
log "backup integrity verified ($backup_list_hash)"

# Restore source tree.
log "Restoring source: rsync $BACKUP/ema_pullback/ → $DST/ema_pullback/"
rsync -a "$BACKUP/ema_pullback/" "$DST/ema_pullback/" --exclude '__pycache__'

# The .env is NOT part of the backup (classifier blocked copy). The live
# .env is left in place. Operator decides whether to also roll back the
# .env's MARKET-mode addendum (comment the MECHANICAL_ENTRY_MODE line
# or set it back to working_order).
log "NOTE: /opt/ema_pullback/.env was NOT touched. If the deployment"
log "      appended the MARKET-mode addendum you want to revert, either"
log "      comment out MECHANICAL_ENTRY_MODE= or set it back to"
log "      working_order before the restart."

if [[ "$OPT_RESTART" == "true" ]]; then
    log "systemctl restart ema-pullback.service"
    sudo systemctl restart ema-pullback.service
    sleep 5
    systemctl show ema-pullback.service -p ActiveState -p MainPID
else
    log "Skipping restart. Code reverted on disk; running process still"
    log "runs whichever code was loaded at service-start time. Trigger a"
    log "restart in a window outside active trading hours to activate."
fi

log "Rollback complete."
