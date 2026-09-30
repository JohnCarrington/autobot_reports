#!/bin/sh
# Write the forensic-backfill freshness marker as well-formed JSON.
#
# Invoked from forensic-backfill.service's ExecStartPost — only runs
# after a successful ExecStart (exit 0). Future alerting can read
# /opt/tradingbot/logs/forensic_backfill_last_run.json and check the
# last_run_ts field's age.
#
# Wrapped as a script (rather than inlined as ExecStartPost=/bin/sh -c
# 'printf ...') because systemd unit files require %%-escaping for date
# format specifiers AND \"-escaping for JSON quotes inside a /bin/sh -c
# argument; the double-nested escape eats the JSON quotes and produces
# malformed output. A 5-line script is the maintainable shape.
set -eu

OUT="/opt/tradingbot/logs/forensic_backfill_last_run.json"
TS="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

printf '{"last_run_ts":"%s","unit":"forensic-backfill.service","exit_status":"success"}\n' \
  "$TS" > "$OUT"
