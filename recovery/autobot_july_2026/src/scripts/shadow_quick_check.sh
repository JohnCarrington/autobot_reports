#!/usr/bin/env bash
# shadow_quick_check.sh — 30-second sanity check for BRIEFING-EXEC-SHADOW logs.
#
# Usage:
#   scripts/shadow_quick_check.sh [hours]
#
# Reads journalctl for autobot.service over the last N hours (default 24)
# and summarises [BRIEFING-EXEC-SHADOW] activity. Exits 0 always — this is
# a check, not a gate.
#
# Optional env override for tests: SHADOW_LOG_FILE=/path/to/file.txt feeds
# the parser from a flat file instead of journalctl.

set -u

HOURS="${1:-24}"
SERVICE="autobot.service"
SHADOW_TAG="[BRIEFING-EXEC-SHADOW]"

if ! [[ "${HOURS}" =~ ^[0-9]+$ ]]; then
    echo "Usage: $0 [hours]" >&2
    exit 0
fi

read_logs() {
    if [[ -n "${SHADOW_LOG_FILE:-}" ]]; then
        cat "${SHADOW_LOG_FILE}"
    else
        journalctl -u "${SERVICE}" --since "${HOURS} hours ago" --no-pager 2>/dev/null
    fi
}

# Pre-filter to shadow lines once; everything below works off this buffer.
SHADOW_LINES="$(read_logs | grep -F "${SHADOW_TAG}" || true)"
# SHADOW_TAG contains "[" and "]"; force -F so they are not parsed as a regex
# character class (which produces "Invalid range end" via the E-E sub-range).
TOTAL="$(printf '%s\n' "${SHADOW_LINES}" | grep -cF "${SHADOW_TAG}" || true)"
# grep -c on an empty buffer can return "" — coerce to 0.
TOTAL="${TOTAL:-0}"
# A blank SHADOW_LINES still counts as one empty line via printf, which grep
# returns 0 on; protect against the rare case where SHADOW_LINES has the
# token embedded but TOTAL came back blank.
if [[ -z "${SHADOW_LINES// /}" ]]; then
    TOTAL=0
fi

echo "============================================================"
echo " Shadow-mode quick check — last ${HOURS}h"
echo "============================================================"
echo

# --------------------------------------------------------------------
# Section 1: shadow log volume
# --------------------------------------------------------------------
echo "Section 1: Shadow log volume"
echo "  Total [BRIEFING-EXEC-SHADOW] lines: ${TOTAL}"

if [[ "${TOTAL}" -gt 0 ]]; then
    echo
    echo "  By symbol:"
    # Each shadow line: "[BRIEFING-EXEC-SHADOW] SYMBOL would_block=... failed=..."
    # The token immediately after the tag is the symbol.
    printf '%s\n' "${SHADOW_LINES}" \
      | awk -v tag="${SHADOW_TAG}" '
            {
                idx = index($0, tag)
                if (idx == 0) next
                rest = substr($0, idx + length(tag))
                # rest now starts with "  SYMBOL would_block=..."
                n = split(rest, parts, /[ \t]+/)
                # parts[1] is empty if there is leading whitespace
                sym = ""
                for (i = 1; i <= n; i++) if (parts[i] != "") { sym = parts[i]; break }
                if (sym == "") sym = "?"
                count[sym]++
            }
            END {
                for (s in count) printf "    %-12s %d\n", s, count[s]
            }
      ' | sort

    echo
    echo "  By entry_mode:"
    printf '%s\n' "${SHADOW_LINES}" \
      | grep -oE 'entry_mode=[^[:space:]]+' \
      | sort | uniq -c \
      | awk '{printf "    %-25s %d\n", $2, $1}'
    # If no entry_mode tokens were emitted at all, surface that.
    if ! printf '%s\n' "${SHADOW_LINES}" | grep -q 'entry_mode='; then
        echo "    entry_mode field absent on all lines"
    fi
fi
echo

# --------------------------------------------------------------------
# Section 2: would_block distribution
# --------------------------------------------------------------------
echo "Section 2: would_block distribution"
WB_TRUE=0
WB_FALSE=0
if [[ "${TOTAL}" -gt 0 ]]; then
    WB_TRUE="$(printf '%s\n' "${SHADOW_LINES}" | grep -c 'would_block=True' || true)"
    WB_FALSE="$(printf '%s\n' "${SHADOW_LINES}" | grep -c 'would_block=False' || true)"
    WB_TRUE="${WB_TRUE:-0}"
    WB_FALSE="${WB_FALSE:-0}"
fi
echo "  would_block=True : ${WB_TRUE}"
echo "  would_block=False: ${WB_FALSE}"
SUM=$(( WB_TRUE + WB_FALSE ))
if [[ "${SUM}" -gt 0 ]]; then
    # Block ratio as a percentage, no bc dependency.
    RATIO_PCT=$(awk -v t="${WB_TRUE}" -v s="${SUM}" 'BEGIN{ printf "%.1f", (t/s)*100 }')
    echo "  block ratio      : ${RATIO_PCT}%"
else
    echo "  block ratio      : n/a (no shadow lines)"
fi
echo

# --------------------------------------------------------------------
# Section 3: failed-condition breakdown (only when would_block=True)
# --------------------------------------------------------------------
echo "Section 3: Failed-condition breakdown (would_block=True only)"
if [[ "${WB_TRUE}" -gt 0 ]]; then
    BLOCKED_LINES="$(printf '%s\n' "${SHADOW_LINES}" | grep 'would_block=True')"

    # Count by condition type. The failed= field is a Python-list repr; we
    # search the rest of the line for known type tokens. release_event,
    # sweep, candle_close, rsi, consecutive_closes are emitted as e.g.
    # "release_event(NFP): now=..." inside the failed= list.
    echo "  By condition type:"
    for cond in release_event sweep candle_close rsi consecutive_closes; do
        # Match "<cond>(" so "rsi" doesn't catch unrelated text.
        c=$(printf '%s\n' "${BLOCKED_LINES}" | grep -c "${cond}(" || true)
        c="${c:-0}"
        printf "    %-22s %d\n" "${cond}" "${c}"
    done

    echo
    echo "  Top 5 specific failure messages:"
    # Pull the failed=[...] payload, then split list elements. We extract
    # everything between the first "failed=[" and the next "] briefing_time"
    # so commas inside parens (e.g. "candle_close(5m,below,...)") survive.
    printf '%s\n' "${BLOCKED_LINES}" \
      | awk '
            {
                a = index($0, "failed=[")
                if (a == 0) next
                rest = substr($0, a + length("failed=["))
                b = index(rest, "] briefing_time=")
                if (b == 0) {
                    # tolerate trailing-only ] or unexpected layout
                    b = index(rest, "]")
                    if (b == 0) next
                }
                payload = substr(rest, 1, b - 1)
                print payload
            }
      ' \
      | awk '
            {
                # Split list on ", " (with quotes) but preserve parenthesised commas.
                # Strategy: walk char by char, only treat comma as separator
                # when paren-depth is 0.
                s = $0
                depth = 0
                buf = ""
                for (i = 1; i <= length(s); i++) {
                    c = substr(s, i, 1)
                    if (c == "(") depth++
                    else if (c == ")") depth--
                    if (c == "," && depth == 0) {
                        gsub(/^[ \t\047"]+|[ \t\047"]+$/, "", buf)
                        if (buf != "") print buf
                        buf = ""
                    } else {
                        buf = buf c
                    }
                }
                gsub(/^[ \t\047"]+|[ \t\047"]+$/, "", buf)
                if (buf != "") print buf
            }
      ' \
      | sort | uniq -c | sort -rn | head -5 \
      | awk 'NF>1 {
            n = $1
            $1 = ""
            sub(/^ */, "", $0)
            printf "    %4d  %s\n", n, $0
      }'

    if [[ -z "$(printf '%s\n' "${BLOCKED_LINES}" | grep 'failed=' || true)" ]]; then
        echo "    failed= field absent on all blocked lines"
    fi
else
    echo "  (none — no would_block=True lines in window)"
fi
echo

# --------------------------------------------------------------------
# Section 4: most recent 10 raw lines
# --------------------------------------------------------------------
echo "Section 4: Most recent 10 shadow log lines (raw)"
if [[ "${TOTAL}" -gt 0 ]]; then
    printf '%s\n' "${SHADOW_LINES}" | tail -n 10
else
    echo "  (none)"
fi
echo

# --------------------------------------------------------------------
# Section 5: sanity flags
# --------------------------------------------------------------------
echo "Section 5: Sanity flags"
if [[ "${TOTAL}" -eq 0 ]]; then
    echo "  ! MODE not flipped to shadow OR no entry attempts in window"
elif [[ "${WB_TRUE}" -eq 0 && "${WB_FALSE}" -gt 0 ]]; then
    echo "  ! v2 not blocking anything — either conditions are too loose"
    echo "    or no setups have stressed the conditions"
elif [[ "${WB_FALSE}" -eq 0 && "${WB_TRUE}" -gt 0 ]]; then
    echo "  ! v2 blocking everything — schema or LLM emission likely broken"
else
    echo "  ok — mixed allow/block distribution"
fi

exit 0
