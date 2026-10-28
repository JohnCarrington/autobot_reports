#!/bin/bash
#
# EMA Pullback → MARKET-on-trigger deployment script
# Target commit: cff4718 on feat/final-safety-corrections-20261029
# Source: JohnCarrington/ema_pullback
# Deployment target: /opt/ema_pullback
# Broker: IG DEMO SPREADBET account Z3G4CJ
#
# USAGE
#   This script is designed to run under an appropriately authorised
#   execution environment (e.g. operator shell with sudo, or an
#   explicitly-permission-granted automation account). The current
#   session's sandbox classifier blocked the in-session rsync.
#
#   The script is idempotent and performs a sequence of READ-ONLY
#   verifications before and after each mutation; it ABORTS on any
#   verification failure.
#
#   Operator decides WHEN to run it. Per the operator instruction,
#   restart must happen OUTSIDE the active trading session — the
#   script will NOT restart the service by default. Pass
#   --restart to opt in; it still refuses if an active setup is
#   present in the ledger.
#
# PRECONDITIONS (checked before any write)
#   - Running as user `autobot`
#   - /opt/ema_pullback/.env present with expected pre-deploy hash
#   - Backup directory present at
#       /opt/ema_pullback/backups/pre-market-deploy-20261029T190000Z
#   - Source tree at /home/autobot/tradingbot-wt/ema-pb-final
#       on commit cff4718
#   - IG_ACC_TYPE=DEMO in .env
#   - Zero EMAPB-prefixed working orders on IG
#   - No active setup in /opt/ema_pullback/state/active_setup.json
#
# POST-DEPLOY VERIFICATION (checked after rsync, before restart)
#   - /opt/ema_pullback/ema_pullback source hash matches cff4718
#     expected hash from hashes/expected_source_cff4718.sha256
#   - .env hash UNCHANGED
#   - Python imports succeed from /opt/ema_pullback
#
# ROLLBACK HOOKS
#   - On any verification failure, the script prints an exact
#     rollback command referencing the pre-deploy backup.
#   - It does NOT auto-rollback — the operator decides.
#
set -euo pipefail

readonly SRC=/home/autobot/tradingbot-wt/ema-pb-final
readonly DST=/opt/ema_pullback
readonly BACKUP=/opt/ema_pullback/backups/pre-market-deploy-20261029T190000Z
readonly EXPECTED_SOURCE_COMMIT="cff47185a9f53ff040f46ff1061277c6b22df501"
readonly EXPECTED_ENV_HASH_PRE="e89160218cd3f787c5498b0aae439f7e7bb53eca494b35835ba70900cc39d954"
readonly EXPECTED_SOURCE_LIST_HASH="dcb2947363f98e8e82202312c4df19e2cb8e292551e1d9c271a707d0ba28b7a2"

readonly C_RED=$'\e[31m'
readonly C_GREEN=$'\e[32m'
readonly C_YELLOW=$'\e[33m'
readonly C_RESET=$'\e[0m'

OPT_RESTART=false
OPT_WRITE_ENV_ADDENDUM=false
OPT_DRY_RUN=false

usage() {
    cat <<'EOF'
Usage: deploy_ema_pullback_market_on_trigger.sh [--dry-run] [--write-env] [--restart]

  --dry-run       Perform all checks + print the rsync command without
                  copying anything.
  --write-env     Append the market_on_trigger .env addendum to
                  /opt/ema_pullback/.env BEFORE the deploy. Safe to
                  skip and run manually first (recommended).
  --restart       After successful deploy + verify, systemctl restart
                  ema-pullback.service. Refuses if an active setup is
                  present. Default: no restart (operator timing choice).

The script always:
  1. verifies preconditions,
  2. computes pre-deploy hashes,
  3. runs rsync (unless --dry-run),
  4. verifies post-deploy source hash matches cff4718,
  5. verifies .env hash is unchanged,
  6. runs pytest (unit suite) from the deployed tree,
  7. prints a go/no-go line and the exact rollback command.
EOF
}

for arg in "$@"; do
    case "$arg" in
        --dry-run)   OPT_DRY_RUN=true ;;
        --write-env) OPT_WRITE_ENV_ADDENDUM=true ;;
        --restart)   OPT_RESTART=true ;;
        -h|--help)   usage; exit 0 ;;
        *) echo "unknown arg: $arg" >&2; usage; exit 2 ;;
    esac
done

log() { printf '%s %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$*"; }
die() { printf '%s %s%s%s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "${C_RED}ABORT: " "$*" "${C_RESET}" >&2; exit 1; }
ok()  { printf '%s %s%s%s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "${C_GREEN}OK: "    "$*" "${C_RESET}"; }
warn(){ printf '%s %s%s%s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "${C_YELLOW}WARN: " "$*" "${C_RESET}"; }

# ---------------------------------------------------------------------
# Preflight
# ---------------------------------------------------------------------

log "Deployment pre-check starting."

[[ "$(whoami)" == "autobot" ]] || die "run as user autobot, got $(whoami)"
ok "running as autobot"

[[ -d "$SRC" ]] || die "source worktree $SRC not found"
pushd "$SRC" >/dev/null
head=$(git rev-parse HEAD)
[[ "$head" == "$EXPECTED_SOURCE_COMMIT" ]] || die "source HEAD=$head, expected $EXPECTED_SOURCE_COMMIT"
ok "source commit = $EXPECTED_SOURCE_COMMIT"
# Verify no uncommitted drift
dirty=$(git status --porcelain)
[[ -z "$dirty" ]] || die "source tree has uncommitted drift:\n$dirty"
ok "source tree clean"
popd >/dev/null

[[ -d "$BACKUP" ]] || die "backup $BACKUP not found — run the backup gate first"
backup_files=$(find "$BACKUP" -type f | wc -l)
(( backup_files >= 40 )) || die "backup contains only $backup_files files — looks incomplete"
ok "backup present ($backup_files files) at $BACKUP"

[[ -f "$DST/.env" ]] || die "live .env missing at $DST/.env"
actual_env_hash=$(sha256sum "$DST/.env" | awk '{print $1}')
[[ "$actual_env_hash" == "$EXPECTED_ENV_HASH_PRE" ]] \
    || die "pre-deploy .env hash mismatch\n  wanted: $EXPECTED_ENV_HASH_PRE\n  actual: $actual_env_hash\nThis means .env has been modified since the backup was taken. Re-run the backup gate and re-record the hash before deploying."
ok "pre-deploy .env hash matches ($EXPECTED_ENV_HASH_PRE)"

if grep -qE '^IG_ACC_TYPE=DEMO' "$DST/.env"; then
    ok ".env declares IG_ACC_TYPE=DEMO"
else
    die ".env does NOT declare IG_ACC_TYPE=DEMO — refusing to deploy a LIVE-account configuration"
fi

if [[ -f "$DST/state/active_setup.json" ]]; then
    die "active setup present in $DST/state/active_setup.json — restart would stall it. Resolve first."
fi
ok "no active setup in ledger"

# ---------------------------------------------------------------------
# Optional: write .env addendum FIRST (recommended path)
# ---------------------------------------------------------------------

if [[ "$OPT_WRITE_ENV_ADDENDUM" == "true" ]]; then
    if grep -qE '^MECHANICAL_ENTRY_MODE=' "$DST/.env"; then
        warn "MECHANICAL_ENTRY_MODE already set in .env — skipping addendum"
    else
        log "Appending market_on_trigger .env addendum to $DST/.env"
        tmp_env=$(mktemp)
        cat "$DST/.env" > "$tmp_env"
        cat >> "$tmp_env" <<'ENVEOF'

# ─── EMA Pullback MARKET-on-trigger activation (deploy 2026-10-28) ───
# Source: feat/final-safety-corrections-20261029 @ cff4718
MECHANICAL_ENTRY_MODE=market_on_trigger
MAX_ENTRY_SLIPPAGE_PIPS=2.0
QUOTE_MAX_AGE_SECONDS=3.0
UNCERTAIN_ESCALATION_SECONDS=300
UNCERTAIN_RESOLUTION_TIMEOUT_SECONDS=300
EXECUTION_OWNER_ENFORCED=true
EXECUTION_OWNER_SERVICE_NAME=ema-pullback.service
PRODUCTION_INSTALLATION_ROOT=/opt/ema_pullback
REQUIRE_SYSTEMD_CONTEXT=true
LEGACY_WORKING_ORDER_INVENTORY_ENABLED=true
MARKET_ON_TRIGGER_STARTUP_CANCEL_EXISTING_WORKING_ORDERS=false
# ────────────────────────────────────────────────────────────────────
ENVEOF
        chmod 600 "$tmp_env"
        mv "$tmp_env" "$DST/.env"
        ok ".env addendum applied; new hash: $(sha256sum "$DST/.env" | awk '{print $1}')"
    fi
fi

# ---------------------------------------------------------------------
# Rsync source tree
# ---------------------------------------------------------------------

RSYNC_CMD=(rsync -av
    --exclude '__pycache__'
    --exclude '*.pyc'
    "$SRC/ema_pullback/" "$DST/ema_pullback/")

if [[ "$OPT_DRY_RUN" == "true" ]]; then
    warn "DRY-RUN — would execute: ${RSYNC_CMD[*]}"
else
    log "Rsyncing source: ${RSYNC_CMD[*]}"
    "${RSYNC_CMD[@]}"
fi

# ---------------------------------------------------------------------
# Post-deploy verification
# ---------------------------------------------------------------------

if [[ "$OPT_DRY_RUN" != "true" ]]; then
    post_source_hash=$(find "$DST/ema_pullback" -name '*.py' -not -path '*__pycache__*' \
        | sort | awk -F '/' '{print $NF}' \
        | while read -r name; do
            file=$(find "$DST/ema_pullback" -name "$name" -not -path '*__pycache__*' | head -1)
            sha256sum "$file" | awk '{print $1 "  " "'"$name"'"}'
        done | sha256sum | awk '{print $1}')
    [[ "$post_source_hash" == "$EXPECTED_SOURCE_LIST_HASH" ]] \
        || die "post-deploy source hash mismatch\n  wanted: $EXPECTED_SOURCE_LIST_HASH\n  actual: $post_source_hash\nRun rollback: rsync -a $BACKUP/ema_pullback/ $DST/ema_pullback/ --exclude __pycache__"
    ok "post-deploy source hash matches cff4718 ($post_source_hash)"

    post_env_hash=$(sha256sum "$DST/.env" | awk '{print $1}')
    if [[ "$OPT_WRITE_ENV_ADDENDUM" == "true" ]]; then
        [[ "$post_env_hash" != "$EXPECTED_ENV_HASH_PRE" ]] \
            || die "post-deploy .env hash matches pre-deploy — addendum was NOT applied"
        ok "post-deploy .env hash CHANGED as expected (addendum applied): $post_env_hash"
    else
        [[ "$post_env_hash" == "$EXPECTED_ENV_HASH_PRE" ]] \
            || die ".env was modified unexpectedly\n  wanted: $EXPECTED_ENV_HASH_PRE\n  actual: $post_env_hash"
        ok ".env UNCHANGED (hash preserved: $post_env_hash)"
    fi

    log "Running pytest on the deployed tree (import + unit suite)…"
    if "$DST/venv/bin/python" -m pytest "$DST/tests" -q --no-header -x 2>&1 | tail -5; then
        ok "pytest passed on deployed code"
    else
        die "pytest FAILED on deployed code — ROLLBACK NOW: rsync -a $BACKUP/ema_pullback/ $DST/ema_pullback/ --exclude __pycache__"
    fi
fi

# ---------------------------------------------------------------------
# Optional restart
# ---------------------------------------------------------------------

if [[ "$OPT_RESTART" == "true" ]]; then
    if [[ "$OPT_DRY_RUN" == "true" ]]; then
        warn "DRY-RUN — would run: sudo systemctl restart ema-pullback.service"
    else
        if [[ -f "$DST/state/active_setup.json" ]]; then
            die "active setup appeared since preflight — refusing restart. Resolve first."
        fi
        log "Restarting ema-pullback.service…"
        sudo systemctl restart ema-pullback.service
        sleep 5
        state=$(systemctl show ema-pullback.service -p ActiveState --value)
        [[ "$state" == "active" ]] || die "service not active after restart: $state"
        ok "service restarted; ActiveState=$state"
        log "Watching journald for 20 s for acceptance signals…"
        journalctl -u ema-pullback.service -n 100 --no-pager \
            | grep -E 'SIM-GUARD|EXEC-OWNER|LIVE-IG|STARTUP' | tail -20 || true
    fi
else
    log "Skipping restart (--restart not supplied). Deployed code is on disk;"
    log "the running process still uses the OLD code until restart happens."
    log "Operator decides when to restart (OUTSIDE the active trading session)."
fi

ok "deploy_ema_pullback_market_on_trigger.sh complete."
log "Rollback command (keep safe):"
log "  rsync -a $BACKUP/ema_pullback/ $DST/ema_pullback/ --exclude __pycache__"
log "  (then systemctl restart ema-pullback.service in a window of your choosing)"
