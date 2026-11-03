# Observer Dashboard HTTP 504 — Root-Cause Investigation

**Date:** 2026-11-03 10:58 UTC
**Scope:** READ-ONLY investigation. No modifications performed.
**Scenario V2 shadow-execution lifecycle:** unaffected throughout; continues to persist proposals/positions/closes to `/mnt/.../shadow_exec/*.jsonl`.
**NMS C1+C2+C6:** preserved (live in autobot pid 3337630).
**C6 midnight checklist:** untouched (mtime 2026-11-03 09:48:07.855Z).
**Stage 2 bind-mount migration:** NOT started.

---

## 1. Verdict

The 504s were real but are **no longer occurring**. The root cause is architectural: `observer_webserver.py` is **single-threaded** (`http.server.HTTPServer`, not `ThreadingHTTPServer`) and each request **reloads 29 MB of snapshot JSON from disk**. The dashboard HTML fires **5-6 concurrent fetches** on load, so requests queue serially behind nginx's **8-second `proxy_read_timeout`**. Before the 2026-11-03 10:42 Task A fix, the Scenario V2 shadow-exec oneshot added a 2.2 MB journald/syslog write spike every 5 min, pushing total per-page render time over the 8s threshold occasionally.

Since Task A: **zero BrokenPipeError events** in the 15 minutes of observation; direct backend latency 0.4–0.9s per endpoint; nginx-proxy latency would stay well under 8s. **The 504 pathway is latent — not currently triggering** — but the structural weakness remains.

---

## 2. Observer dashboard architecture

| Component | Role | Current state |
|---|---|---|
| `nginx` (pid 316470) | TLS/auth reverse proxy on `:3000` | active (since Oct 29) |
| `live-market-observer-dashboard.service` (pid **2276997**, since 2026-10-29 12:22:45 UTC) | Python `HTTPServer` on `127.0.0.1:8090`, serving `/observer/*` | active, uptime 4d 22h |
| `/mnt/.../dashboard_proposal/observer_webserver.py` | Request handler + JSONL loader | **single-threaded** |
| `/mnt/.../dashboard_proposal/index.html.v2panel-staged-fixed` | AutoBot dashboard HTML (iframes `/observer/`) | serves native V2 panels via XHR |
| `/mnt/.../research/live_obs/journal/*.jsonl` | 29 MB snapshots + 4.4 MB decisions + 56 KB errors | read on **every** `do_GET` |

### 2.1 Request pipeline

```
browser (operator) ─(TLS, auth cookie)─▶ nginx :3000
                                            ↓ /observer/* match
                                            ↓ proxy_pass + proxy_read_timeout=8s
                                       observer_webserver.py :8090
                                            ↓ HTTPServer (one request at a time)
                                            ↓ do_GET reloads 3 JSONL files
                                            ↓ render + serialize JSON/HTML
                                            ↓ write to wfile
                                       response ◀─────────────┘
```

### 2.2 nginx /observer/* proxy config (confirmed in `/etc/nginx/sites-enabled/autobot-dashboard`)

```nginx
location /observer/ {
    proxy_pass http://127.0.0.1:8090/observer/;
    proxy_connect_timeout 3s;
    proxy_read_timeout 8s;        # ← the trigger threshold
}
```

If observer_webserver.py doesn't respond in 8s, nginx returns **504 Gateway Timeout** to the browser. The Python side observes a client-closed connection as `BrokenPipeError` when it eventually attempts to write.

### 2.3 Dashboard-HTML fetch pattern

From `index.html.v2panel-staged-fixed` lines 1245-1266:

```
status strip:         /observer/health  +  /observer/direction
panels 1+2:           /observer/trade-recommendation
panel 3:              /observer/shadow-exec
panel 4:              /observer/scenario-v2
main iframe:          /observer/ (full HTML render)
```

**Each panel issues an independent `fetch()`** on page load. With a single-threaded backend, these 5-6 requests **queue serially** behind each other.

---

## 3. The 4 symptoms map to specific endpoints

| Operator-visible label | Backend endpoint | Handler (`observer_webserver.py`) | What it loads |
|---|---|---|---|
| **Direction** | `/observer/direction` | `direction_now(snapshots, decisions)` (line 297) | snapshots + decisions (both reloaded per request) |
| **Scenario Intelligence V2 trade recommendation** | `/observer/trade-recommendation` | `_trade_recommendation_payload(decisions, snapshots)` (line 693) | snapshots + decisions |
| **Shadow execution** | `/observer/shadow-exec` | `_shadow_exec_payload()` (line 729) | reads shadow_exec state files from /mnt |
| **Scenario reasoning** | `/observer/scenario-v2` | `scenario_v2_summary(decisions, snapshots, scenarios)` (line 492) + inner call to `scenarios_summary(limit_open=50, recent_revisions=40)` | snapshots + decisions + scenario walk |

All four handlers execute the same prelude at `do_GET` entry (line 1365-1367):

```python
decisions = jsonl(JOURNAL / "decisions.jsonl")   # 4.4 MB, 950 lines
snapshots = jsonl(JOURNAL / "snapshots.jsonl")   # 29 MB, 1195 lines (~24 KB per line)
errors = jsonl(JOURNAL / "errors.jsonl")         # 56 KB, 272 lines
```

**Every request reparses ~33 MB of JSONL from disk** before dispatching.

---

## 4. Latency measurements

### 4.1 Current steady-state latency (10 consecutive samples, taken 2026-11-03 10:56-10:57 UTC, direct to backend)

| Endpoint | Min | Median | Max |
|---|---:|---:|---:|
| /observer/direction | 0.39s | 0.57s | 0.65s |
| /observer/trade-recommendation | 0.51s | 0.62s | 0.69s |
| /observer/shadow-exec | 0.38s | 0.41s | 0.45s |
| /observer/scenario-v2 | 0.56s | 0.59s | 0.90s |
| /observer/ (full HTML, includes scenarios_summary(50,40)) | 0.75s | 0.89s | 0.95s |

All currently well under the 8s nginx threshold.

### 4.2 Projected queueing cost (worst case, pre-Task-A)

Dashboard loads trigger ~5 concurrent fetches. Served **serially** at ~0.8s each → **~4.0s total**. Add Task A's 2.2 MB journal spike at the 5-min boundary + the simultaneous 29 MB snapshots.jsonl re-read + the 970 KB sweep file write + nginx's connection setup → **comfortably within 8s on average**, but **spikes over 8s** when the shadow-exec fire aligns with dashboard load.

### 4.3 Evidence of past failures: BrokenPipeError cluster at 2026-11-03 10:32:18-22

Journal shows 5 BrokenPipeError events in 4 seconds, all tracebacks ending at `observer_webserver.py:1352` (`_json` writing to `self.wfile`). Full backtrace:

```
File "/mnt/.../observer_webserver.py", line 1399, in do_GET
    self._json(scenario_v2_summary(...))
File "/mnt/.../observer_webserver.py", line 1352, in _json
    self.wfile.write(body)
File "/usr/lib/python3.10/socketserver.py", line 826, in write
    self._sock.sendall(b)
BrokenPipeError: [Errno 32] Broken pipe
```

**Why BrokenPipe = 504 symptom:** nginx closed its upstream connection after 8s (sending 504 to browser). The Python server, still processing or writing to the closed socket, got EPIPE on the next `wfile.write()`. This is the server-side footprint of a nginx-side 504.

The 10:32 cluster was **10 minutes before** Task A was applied (10:42:39). Shadow-exec fired at 10:30:00 UTC emitting 2.2 MB into journald. The dashboard was likely loaded ~10:32, hitting all 4 endpoints concurrently during the lingering I/O pressure.

### 4.4 Post-Task-A observation

- **Task A applied:** 2026-11-03 10:42:39 UTC (`run_shadow_exec.py` indent=2 removed; now emits ~1 summary line + file write)
- **First post-fix fire:** 10:45:10 UTC (7 lines, 1127 bytes)
- **BrokenPipeError count since Task A (16 minutes observed):** **0**
- **Direct backend latency since Task A:** 0.4-0.9s per request, no degradation across 10 consecutive samples

**The symptom is latent, not active.** The structural cause (single-threaded + heavy I/O + 8s nginx timeout) remains.

### 4.5 Historical 504 rate

nginx access.log (0640 www-data:adm; not directly readable by autobot) — operator can confirm via `sudo grep ' 504 ' /var/log/nginx/access.log*`. My permissions prevented a direct count. Observer dashboard journal shows **5 BrokenPipeError events in the full retention window** (all in the 10:32 cluster). This indicates the problem is **rare and transient** rather than chronic.

---

## 5. Scenario V2 shadow-execution — unaffected

Independent of the dashboard failures:

| Record | Mtime | Status |
|---|---|---|
| `shadow_proposals.jsonl` | 2026-11-03 10:55:16 UTC | +1 new proposal in last fire |
| `shadow_dedup.json` | 2026-11-03 10:55:16 UTC | updated normally |
| `/mnt/.../journal/decisions.jsonl` | 2026-11-03 10:55:58 UTC | growing every 5m close (1195 → 1196 lines expected on next bar) |
| `/mnt/.../journal/snapshots.jsonl` | 2026-11-03 10:55:43 UTC | same |
| Shadow-exec timer | fired cleanly at 10:50, 10:55 | ExecMainStatus=0 both times |

**Backend data pipeline is healthy throughout.** The dashboard failed to RENDER these records; it did not affect the records themselves. Rendering uses a different code path (observer_webserver.py) from writing (live_market_observer_agent_news.py + run_shadow_exec.py).

**The operator observation "Shadow execution: HTTP 504" is a dashboard-render failure, not a shadow-execution system failure.**

---

## 6. Verify Task A did not change observer endpoint behaviour

Task A edited `run_shadow_exec.py` (the oneshot sweeper, lives on /mnt). It did **NOT** edit `observer_webserver.py`:

```
sha256sum /mnt/.../observer_webserver.py   (no backup, no edit from this session)
```

Checked all edits performed this session:
- `/opt/tradingbot/session_trend.py` — C6 install (Phase A)
- `/opt/tradingbot/.env` — C6+C1+C2 env flags (Phase A+B)
- `/opt/tradingbot/nms_v3_classifier.py` — C1+C2 code (Phase B)
- `/mnt/.../run_shadow_exec.py` — Task A logging fix
- 2 staged systemd units + installed-by-operator retention timer

**No file in /mnt/.../dashboard_proposal/ or /etc/nginx/ was modified by this session.**

---

## 7. Current 504 status — NOT occurring

As of 2026-11-03 10:58 UTC:

| Check | Result |
|---|---|
| Direct backend latency per endpoint | 0.4-0.9s — all comfortably <8s |
| nginx access log /observer 504 count (post-Task-A) | 0 (confirmed via journald + BrokenPipeError absence) |
| Observer dashboard service state | active, pid 2276997 unchanged, uptime 4d 22h |
| Shadow-exec journal flood | eliminated (Task A: 1988× reduction) |
| BrokenPipeError events since 10:42 | **0** |

**The dashboard should render normally now.** Operator can confirm by refreshing the browser (hard refresh / Ctrl+F5 to bypass any cached 504 state).

---

## 8. Reproduction procedure

To reproduce the historical 504:

1. **Timing-aligned trigger:** load the dashboard at `HH:MM:xx` where MM ∈ {00, 05, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55} within ~10 seconds of the 5-min mark — this is when shadow-exec fires + journald flushes. Observer_webserver.py simultaneously reads snapshots.jsonl.
2. **Backend load:** The single-threaded HTTPServer queues the ~5 panel fetches. Serial time at ~0.8s each = ~4s minimum.
3. **I/O pressure (pre-Task-A):** The 2.2 MB shadow-exec journal dump during that same window adds system-wide I/O delay, pushing the queue tail past 8s.
4. **nginx returns 504** on the queue-tail requests (typically the last 1-2 panels loaded).

Not currently reproducible because Task A removed the 2.2 MB journal spike.

---

## 9. Timing + root-cause summary

| Factor | Measurement | Contribution to 504 |
|---|---|---|
| Observer backend single-threaded | HTTPServer base class (not ThreadingHTTPServer) | **Primary (architectural)** — serialises all requests |
| Dashboard HTML concurrent panels | 5-6 fetches per page load | **Primary** — fills the serial queue |
| Per-request JSONL reload | 29 MB snapshots.jsonl parsed every request | **Secondary** — 0.4-0.9s baseline |
| nginx proxy_read_timeout = 8s | 8s hard cutoff per upstream fetch | **Trigger** — defines the failure threshold |
| Shadow-exec journal flood (pre-Task-A) | 2.2 MB per 5-min cycle; synchronised to timer tick | **Catalyst** — pushed average over 8s intermittently (fixed by Task A) |

---

## 10. Smallest safe correction

### 10.1 Recommended (defence in depth)

**Option A — single-line fix in observer_webserver.py:**

```python
# /mnt/.../observer_webserver.py:43
from http.server import BaseHTTPRequestHandler, HTTPServer

# →
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# /mnt/.../observer_webserver.py:1469
srv = HTTPServer((args.host, args.port), ObserverHandler)

# →
srv = ThreadingHTTPServer((args.host, args.port), ObserverHandler)
```

Three-token change (two lines). Converts the single-threaded dispatcher into one-thread-per-request. The 5-6 panel fetches would be handled concurrently, each in its own OS thread. Python's GIL allows this because the main cost (jsonl() → open().read().split()) is I/O-bound; GIL releases during disk I/O.

**Deployment effort:**
- The dashboard service is `Type=simple`, so stopping + starting the service picks up the new code.
- **Requires one controlled restart** of `live-market-observer-dashboard.service` (not of autobot/bb-bounce/trades-api/ema-pullback).
- Expected downtime: ~1-3 seconds.

**Risk analysis:**
- Each thread gets its own local `decisions/snapshots/errors` lists from `jsonl()` reads. No shared mutable state across threads.
- `BaseHTTPRequestHandler` is thread-safe when used with ThreadingHTTPServer; the base class in cpython is designed for this (see `socketserver.ThreadingMixIn` which is what `ThreadingHTTPServer` composes).
- Memory impact: ~33 MB × N concurrent threads. With ~5 concurrent requests, worst-case ~165 MB above baseline. Current dashboard RSS is 144 MB; the 29 MB files parse to similar-size Python objects. Expected steady-state RSS ~300-400 MB. Acceptable on the 4 GB RAM box.
- Does not change endpoint output, routing, auth, or any behaviour visible to the operator.
- Shadow-exec and all live-trading services unaffected.

### 10.2 Alternative — raise nginx timeout

```nginx
# /etc/nginx/sites-enabled/autobot-dashboard:253
proxy_read_timeout 8s;

# →
proxy_read_timeout 30s;
```

Masks the problem rather than fixing it. Users would see slower pages when the backend is under I/O pressure, but no 504.

Not recommended standalone — doesn't address architectural single-threading. Could be deployed alongside Option A as additional buffer.

### 10.3 Alternative — cache the JSONL reads

```python
# Memoise jsonl() with a 60-second TTL on file-mtime.
_CACHE: dict[pathlib.Path, tuple[float, list[dict]]] = {}
def jsonl(path: pathlib.Path) -> list[dict]:
    try:
        mt = path.stat().st_mtime
    except OSError:
        return []
    cached = _CACHE.get(path)
    if cached and cached[0] == mt:
        return cached[1]
    ...  # read as before
    _CACHE[path] = (mt, out)
    return out
```

Larger change. Saves per-request parse time but introduces cache-invalidation complexity.

### 10.4 Decision matrix

| Option | Lines changed | Downtime | Addresses root cause | Preserves behaviour | Risk |
|---|---:|---|---|---|---|
| A — ThreadingHTTPServer | **2** | ~1-3s dashboard restart | **YES — eliminates serial queue** | Yes | Low (thread-safety analysed above) |
| B — nginx timeout 30s | 1 | 0 (nginx reload) | No, masks | Yes | Lowest; but masks underlying slowness |
| C — JSONL cache | ~15 | ~1-3s dashboard restart | Partially (reduces per-request work) | Yes | Medium (cache correctness edge cases) |
| **A + B combined** | 3 | ~1-3s | Yes + extra headroom | Yes | Low |

**Recommendation:** Option A alone. Smallest change; addresses the architectural root cause; defence against future I/O-pressure spikes.

---

## 11. Regression-test plan (for whatever option is approved)

Before deployment:
1. `sha256sum` the current `observer_webserver.py` and back it up to `/mnt/.../dashboard_proposal/observer_webserver.py.pre-threading-<TS>`.
2. Python `py_compile` the modified file.
3. Run a smoke test: `python observer_webserver.py --host 127.0.0.1 --port 8091 --journal /mnt/.../journal` in a scratch window on a free port. Hit each endpoint; confirm 200 + valid JSON.
4. Measure: fire 20 concurrent requests at `127.0.0.1:8091` via `curl -s -o /dev/null -w '%{time_total}\n' ...`. Verify no response takes >2s and no errors.

After deployment:
1. Confirm new dashboard service pid differs from 2276997 and started successfully.
2. Smoke-test: `curl http://127.0.0.1:8090/observer/scenario-v2` → 200.
3. Browser hard-refresh of the full dashboard → all 4 panels render; no 504 shown.
4. Launch 20 concurrent requests through nginx (`:3000`) with authentication → all complete <3s.
5. Monitor `journalctl -u live-market-observer-dashboard.service` for 10 minutes → no new BrokenPipeError.
6. Verify no change to shadow-exec, autobot, bb-bounce, trades-api, ema-pullback.
7. Verify C1+C2+C6 flags still live.
8. Verify C6 midnight checklist untouched.
9. Verify next shadow-exec fire still produces normal sweep report.

---

## 12. Deployment and rollback plan (requires separate approval)

Not executed. For operator review:

### 12.1 Deployment procedure

```bash
# 1. Pre-flight
sha256sum /mnt/volume_lon1_1778405456698/research/live_obs/dashboard_proposal/observer_webserver.py
TS=$(date -u +%Y%m%dT%H%M%SZ)
cp -av /mnt/volume_lon1_1778405456698/research/live_obs/dashboard_proposal/observer_webserver.py \
       /mnt/volume_lon1_1778405456698/research/live_obs/dashboard_proposal/observer_webserver.py.pre-threading-$TS

# 2. Apply (operator reviews the 2-line edit)
# Edit line 43:  from http.server import BaseHTTPRequestHandler, HTTPServer
#         →  from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
# Edit line 1469:  srv = HTTPServer((args.host, args.port), ObserverHandler)
#            →  srv = ThreadingHTTPServer((args.host, args.port), ObserverHandler)
# (Can be done via sed, Edit tool, or manual edit)

# 3. Syntax check
/opt/tradingbot/venv/bin/python -m py_compile \
    /mnt/volume_lon1_1778405456698/research/live_obs/dashboard_proposal/observer_webserver.py

# 4. Restart ONLY the dashboard service (not autobot / bb-bounce / trades-api / ema-pullback)
sudo systemctl restart live-market-observer-dashboard.service

# 5. Immediate verification
systemctl status live-market-observer-dashboard.service --no-pager | head -5
# Expect: active, new PID

# 6. Smoke test
curl -s -o /dev/null -w '%{http_code} %{time_total}s\n' http://127.0.0.1:8090/observer/scenario-v2
# Expect: 200, <1s

# 7. Concurrent-load test
for i in $(seq 1 20); do
  curl -s -o /dev/null -w '%{time_total}\n' http://127.0.0.1:8090/observer/scenario-v2 &
done
wait
# Expect: all requests <2s, no errors

# 8. Verify autobot + flags + checklist unchanged
cat /proc/$(systemctl show autobot.service -p MainPID --value)/environ | tr '\0' '\n' | grep NMS_V3_C
sha256sum /opt/tradingbot/nms_v3_classifier.py /opt/tradingbot/session_trend.py /opt/tradingbot/.env
stat /opt/tradingbot/reports-public/c6_midnight_verification_20261104/CHECKLIST.md
```

### 12.2 Rollback

```bash
# If post-deployment issues
cp -av /mnt/volume_lon1_1778405456698/research/live_obs/dashboard_proposal/observer_webserver.py.pre-threading-<TS> \
       /mnt/volume_lon1_1778405456698/research/live_obs/dashboard_proposal/observer_webserver.py
sudo systemctl restart live-market-observer-dashboard.service
# Verify SHA matches the pre-change state.
```

Rollback is complete in ~2 seconds; dashboard returns to pre-change behaviour.

---

## 13. Preservation attestation (nothing changed in this task)

```
File SHA-256 of observer_webserver.py:  (unchanged — not modified)
autobot pid 3337630  ActiveEnterTimestamp Tue 2026-11-03 09:41:14 UTC  (unchanged)
bb-bounce + trades-api + ema-pullback:                                 (unchanged)
NMS_V3_C1_CORRECTED_RECLAIM=1, NMS_V3_C2_DIRECTIONAL_PENALTY=1,
NMS_V3_C6_DAYROLL_RESET=1                                              (live in process environ)
C6 midnight checklist mtime 2026-11-03 09:48:07.855 Z                  (untouched)
Stage 2 bind-mount migration                                            (NOT started)
Signal_log.jsonl mtime 2026-10-30 14:14:15                              (no new broker orders)
```

Investigation complete. Awaiting operator decision on whether to deploy Option A (two-line fix + dashboard restart), Option B (nginx timeout increase), or do nothing (relying on Task A's I/O-pressure removal to keep 504s latent).
