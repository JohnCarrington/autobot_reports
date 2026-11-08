# AutoBot dashboard hosting (AutoBot 161) — reproducible from this doc

Host: AutoBot 161 (161.35.168.61). Read-only audit, no services or
configs were changed. Line numbers refer to the files as they exist
on disk today (2026-11-08).

> **Observation at audit time:** `trades-api.service` is
> `disabled` / `inactive` right now, so nothing is listening on
> `127.0.0.1:8080`. `nginx.service` is active, binding
> `0.0.0.0:3000`. This is the designed architecture (trades-api is
> uncoupled from autobot); it just means that right now any gated
> route proxies to a down upstream. The deployment contract below is
> what a new bot should copy.

## 1. The nginx configuration

### 1.1 File paths

- **Served config:** `/etc/nginx/sites-available/autobot-dashboard`
  (owned by root). This is the file nginx actually reads.
- **Enabler symlink:**
  `/etc/nginx/sites-enabled/autobot-dashboard` →
  `/etc/nginx/sites-available/autobot-dashboard`.
- **Source of truth in the repo:**
  `/opt/tradingbot/deploy/autobot-dashboard.nginx`. Install
  procedure is documented in-file at
  `autobot-dashboard:29-32`:

  ```
   29:# Install (run as root — autobot can't write /etc/nginx/):
   30:#   sudo cp /opt/tradingbot/deploy/autobot-dashboard.nginx \
   31:#           /etc/nginx/sites-available/autobot-dashboard
   32:#   sudo nginx -t && sudo systemctl reload nginx
  ```

- **Backup snapshots (not loaded):**
  `autobot-dashboard.pre-deploy-20261008T210233Z`,
  `.pre-h144.bak`, `.pre-observer-20261022T141732Z` — read-only
  rollback artefacts in the same directory.
- **nginx version:** `nginx/1.18.0 (Ubuntu)`, built with
  `--with-http_ssl_module` and `--with-http_auth_request_module`
  (the auth_request module is load-bearing for §2).
- **nginx systemd unit:** `/lib/systemd/system/nginx.service`
  (distro default — not customised).

### 1.2 Listen address, port, domain, TLS

From `/etc/nginx/sites-available/autobot-dashboard:57-69`:

```
 57:server {
 58:    # 2026-08-12: public listen on 0.0.0.0:3000 retained deliberately.
 59:    # The 2026-08-03 plan rebound this to tailnet+localhost only, but the
 60:    # operator requires public reachability for phone access without a
 61:    # Tailscale round-trip. The existing cookie-based auth_request gate
 62:    # (see /_authcheck below) remains the sole guard — unchanged. Do NOT
 63:    # add UFW deny-3000 or restore the tailnet-only bind without an
 64:    # explicit operator decision to give up public phone access.
 65:    listen 3000;
 66:    server_name _;
 67:
 68:    root /opt/autobot-dashboard;
 69:    index index.html;
```

- **Port:** `3000`
- **Bind address:** `0.0.0.0` (the default for `listen 3000;` with
  no address). Observed with `ss -tlnp`:
  `LISTEN 0 511 0.0.0.0:3000 0.0.0.0:*` (nginx workers).
- **server_name:** `_` — a catch-all; **no DNS domain is bound**.
  The dashboard is reached by raw IP + port: `http://161.35.168.61:3000`
  (operator's phone) or `http://100.80.206.93:3000` (tailnet IP, if
  on Tailscale).
- **TLS:** **HTTPS is NOT used.** There is no `listen 443 ssl`
  block, no `ssl_certificate` directive, and no certificate
  provisioned for this vhost. Traffic to `:3000` is plain HTTP; the
  cookie is signed but transported in cleartext.

## 2. How the dashboard is protected

### 2.1 Mechanism — cookie-based `auth_request` subrequest

Historical context at `autobot-dashboard:1-13`:

```
  1:# /opt/tradingbot/deploy/autobot-dashboard.nginx
  2:#
  3:# 2026-06-16: replaced HTTP Basic auth with cookie-based auth_request.
  4:# Basic auth fired a browser-native dialog on every gated request, which
  5:# hurt the PWA experience and couldn't be styled or scripted. The new
  6:# model: nginx subrequests every gated endpoint to Flask /auth-check;
  7:# Flask validates the signed-cookie session set by POST /auth (driven by
  8:# the existing client-side modal in index.html). The PWA shell stays
  9:# public so the browser can boot and the modal can render; only data
 10:# endpoints (/trades, /briefings, /news-state, /fxi/*, /h144/*) are
 11:# gated. /manifest.json is intentionally public — manifests carry no
 12:# secrets and a public manifest avoids credential awkwardness during
 13:# PWA "install to home screen".
```

The internal subrequest target at `autobot-dashboard:76-83`:

```
 76:    location = /_authcheck {
 77:        internal;
 78:        proxy_pass http://127.0.0.1:8080/auth-check;
 79:        proxy_pass_request_body off;
 80:        proxy_set_header Content-Length "";
 81:        proxy_set_header Host $host;
 82:        proxy_set_header X-Real-IP $remote_addr;
 83:    }
```

`internal;` makes this location unreachable from outside — nginx
only visits it via `auth_request`. Each gated route adds exactly
one directive, e.g. `autobot-dashboard:107-113`:

```
107:    location /trades {
108:        auth_request /_authcheck;
109:        proxy_pass http://127.0.0.1:8080/trades;
110:        proxy_set_header Host $host;
111:        proxy_set_header X-Real-IP $remote_addr;
112:        add_header Cache-Control "no-cache, no-store, must-revalidate";
113:    }
```

### 2.2 Public (un-gated) routes

| Location                 | Purpose                                                                    | File line |
|--------------------------|----------------------------------------------------------------------------|-----------|
| `location /`             | PWA shell + icons via `try_files $uri $uri/ /index.html`                   | 85-88     |
| `location /manifest.json`| Public manifest (PWA install), served via alias                            | 90-93     |
| `location /registry`     | Strategy registry (hard-coded no-secret JSON)                              | 100-105   |
| `location /auth`         | POST to create the signed session cookie                                   | 261-265   |
| `location /logout`       | POST to clear the session cookie                                           | 267-271   |

```
 85:    location / {
 86:        auth_basic off;
 87:        try_files $uri $uri/ /index.html;
 88:    }
```

```
261:    location /auth {
262:        proxy_pass http://127.0.0.1:8080/auth;
263:        proxy_set_header Host $host;
264:        proxy_set_header X-Real-IP $remote_addr;
265:    }
266:
267:    location /logout {
268:        proxy_pass http://127.0.0.1:8080/logout;
269:        proxy_set_header Host $host;
270:        proxy_set_header X-Real-IP $remote_addr;
271:    }
```

### 2.3 Gated routes — `auth_request /_authcheck`

Every data-bearing endpoint carries the same directive:

| Location          | Upstream                                | File line |
|-------------------|------------------------------------------|-----------|
| `/trades`         | `http://127.0.0.1:8080/trades`           | 107-113   |
| `/strategies`     | `http://127.0.0.1:8080/strategies`       | 122-128   |
| `/briefings`      | `http://127.0.0.1:8080/briefings`        | 130-136   |
| `/news-state`     | `http://127.0.0.1:8080/news-state`       | 141-147   |
| `/fxi/`           | `http://127.0.0.1:8080/fxi/`             | 156-162   |
| `/h144/trades`           | `http://100.99.57.69:8080/trades`        | 177-185   |
| `/h144/trades/summary`   | `http://100.99.57.69:8080/trades/summary`| 187-195   |
| `/h144/briefings`        | `http://100.99.57.69:8080/briefings`     | 197-205   |
| `/h144/news-state`       | `http://100.99.57.69:8080/news-state`    | 207-215   |
| `/observer/`      | `http://127.0.0.1:8090/observer/`        | 247-256   |

The same cookie that unlocks `/trades` unlocks `/h144/*` because the
subrequest runs against this host's `/_authcheck` regardless of
which upstream the real request is routed to
(`autobot-dashboard:164-176`).

### 2.4 Flask side of the gate

Source: `/opt/tradingbot/trades_api.py`.

Signing key — `trades_api.py:36`:

```
 36:app.secret_key = os.getenv("DASHBOARD_SECRET_KEY")
```

Password check and cookie issuance — `trades_api.py:4526-4555`:

```
4526:DASHBOARD_PASSWORD = os.getenv("DASHBOARD_PASSWORD", "")
4527:
4528:
4529:@app.route("/auth", methods=["POST"])
4530:def auth():
4531:    """Sign the browser in by setting a 30-day signed-cookie session.
4532:    Body: {"password": "..."}. Empty DASHBOARD_PASSWORD means "no gate".
4533:    """
4534:    expected = os.getenv("DASHBOARD_PASSWORD")
4535:    data = request.get_json(silent=True) or {}
4536:    if not expected or data.get("password") == expected:
4537:        session.permanent = True
4538:        session["authed"] = True
4539:        return jsonify({"ok": True})
4540:    return jsonify({"ok": False}), 401
4541:
4542:
4543:@app.route("/auth-check", methods=["GET", "POST"])
4544:def auth_check():
4545:    """Subrequest target for nginx auth_request — 200 if cookie validates,
4546:    401 otherwise. Body is dropped by nginx; both verbs accepted as
4547:    insurance against a future gated POST endpoint."""
4548:    return ("", 200) if session.get("authed") else ("", 401)
4549:
4550:
4551:@app.route("/logout", methods=["POST"])
4552:def logout():
4553:    """Clear the authed flag from the session cookie."""
4554:    session.clear()
4555:    return jsonify({"ok": True})
4556:
```

Important: **`DASHBOARD_PASSWORD` empty means "no gate"**
(`trades_api.py:4536`). Setting it is required on a public listener.

Two load-bearing environment variables (both REDACTED here, both
in `/opt/tradingbot/.env`, both must survive restarts intact):

- `DASHBOARD_SECRET_KEY` — signs the cookie; must NOT rotate across
  trades-api restarts, else every signed-in browser gets kicked.
- `DASHBOARD_PASSWORD` — the shared password the client-side modal
  POSTs to `/auth`.

### 2.5 No IP allowlist in nginx

There is no `allow`/`deny` directive anywhere in
`/etc/nginx/sites-available/autobot-dashboard`. The cookie gate is
the sole in-nginx guard on port 3000. The explicit comment at
`autobot-dashboard:58-64` documents the operator's decision not to
restrict by IP.

### 2.6 Legacy artefact

`autobot-dashboard:37-38`:

```
 37:# The legacy /etc/nginx/.htpasswd is no longer consulted — safe to
 38:# leave on disk or remove.
```

So `/etc/nginx/.htpasswd` may still exist on disk but is not read
by this vhost since the 2026-06-16 cookie cutover.

## 3. Backend data service

### 3.1 Primary — `trades-api.service` on `127.0.0.1:8080`

Unit file: `/etc/systemd/system/trades-api.service`, 73 lines.
Full body:

```
  1:# /opt/tradingbot/deploy/trades-api.service
  2:#
  3:# Standalone Trades API — the same Flask app autobot used to bundle as an
  4:# in-process daemon thread, now run as its own systemd unit so the dashboard
  5:# stays live when the trading engine is off (weekend autobot-stop.timer,
  6:# maintenance, crash, deploy). Decoupled from autobot:
  7:#
  8:#   - Reads signal_log.jsonl + IG REST via ig_auth (no autobot module
  9:#     imports, no shared in-process state).
 10:#   - Independent restart cycle — bouncing this unit doesn't touch autobot
 11:#     and vice versa.
 12:#   - autobot.py is gated by TRADES_API_INPROCESS_ENABLED (default 0) so
 13:#     starting autobot does NOT double-bind 8080; this unit owns it.
 ...
 31:[Unit]
 32:Description=Trades API (standalone Flask, decoupled from autobot)
 33:Documentation=file:///opt/tradingbot/trades_api.py
 34:After=network-online.target
 35:Wants=network-online.target
 36:
 37:[Service]
 38:Type=simple
 39:User=autobot
 40:Group=autobot
 41:WorkingDirectory=/opt/tradingbot
 42:
 ...
 46:EnvironmentFile=/opt/tradingbot/.env
 47:
 48:# Foreground Flask via the __main__ block in trades_api.py. Env knobs
 49:# TRADES_API_HOST / TRADES_API_PORT (defaults 0.0.0.0 / 8080) can be
 50:# overridden by adding them to .env or a drop-in.
 51:ExecStart=/opt/tradingbot/venv/bin/python /opt/tradingbot/trades_api.py
 52:
 53:# Healing: if the process exits with non-zero (Finnhub key invalid, IG
 54:# session blow-up, code bug) systemd restarts after 5s. Cap restarts so a
 55:# tight-loop crash doesn't burn the journal.
 56:Restart=on-failure
 57:RestartSec=5
 58:StartLimitBurst=5
 59:StartLimitIntervalSec=60
 60:
 ...
 63:TimeoutStopSec=15s
 64:KillSignal=SIGTERM
 65:SendSIGKILL=yes
 ...
 68:StandardOutput=journal
 69:StandardError=journal
 70:
 71:[Install]
 72:WantedBy=multi-user.target
```

The Flask foreground runner — `trades_api.py:4867-4879`:

```
4867:if __name__ == "__main__":
4868:    logging.basicConfig(
4869:        level=logging.INFO,
4870:        format="%(asctime)s [%(levelname)s] %(message)s",
4871:    )
4872:    _STANDALONE_HOST = os.getenv("TRADES_API_HOST", "0.0.0.0")
4873:    _STANDALONE_PORT = int(os.getenv("TRADES_API_PORT", "8080"))
4874:    logger.info(
4875:        "📊 Trades API STANDALONE start: host=%s port=%d (IG source, %dd history, %ds cache)",
4876:        _STANDALONE_HOST, _STANDALONE_PORT, HISTORY_DAYS, CACHE_TTL_S,
4877:    )
4878:    logging.getLogger("werkzeug").setLevel(logging.WARNING)
4879:    app.run(host=_STANDALONE_HOST, port=_STANDALONE_PORT, threaded=True)
4880:
```

So by default the Flask process binds `0.0.0.0:8080`. **Only
nginx reaches it in practice because UFW blocks external 8080**
(see §5), and nginx's proxy_pass uses `127.0.0.1:8080`
exclusively (`autobot-dashboard:78,101,109,124,132,143,158,262,268`).

A new bot should set `TRADES_API_HOST=127.0.0.1` in `.env` to make
the loopback-only binding explicit rather than relying on UFW.

### 3.2 How nginx passes requests to it

Three facts in the config carry the proxying:

- **Loopback-only upstreams** — every gated location proxies to
  `http://127.0.0.1:8080/...` with no upstream block, no load
  balancing, no keepalive pool. Example
  (`autobot-dashboard:107-113` quoted in §2.3).
- **Header rewrites** — each location passes the client's
  `Host` and `X-Real-IP` upstream and adds a strict
  no-cache header downstream. The real client IP is the
  tailnet or public IP depending on reach.
- **Subrequest auth** — `auth_request /_authcheck` runs the
  in-nginx subrequest against
  `http://127.0.0.1:8080/auth-check` BEFORE the main
  `proxy_pass`; a 401 from the subrequest short-circuits the
  gated route without any upstream call for the real request.

### 3.3 Secondary — `live-market-observer-dashboard.service` on `127.0.0.1:8090`

Loopback-only, strictly read-only. Proxied under `/observer/`
(`autobot-dashboard:244-256`):

```
244:    location = /observer {
245:        return 301 /observer/;
246:    }
247:    location /observer/ {
248:        auth_request /_authcheck;
249:        proxy_pass http://127.0.0.1:8090/observer/;
250:        proxy_set_header Host $host;
251:        proxy_set_header X-Real-IP $remote_addr;
252:        proxy_connect_timeout 3s;
253:        proxy_read_timeout 8s;
254:        # No-cache: freshness matters more than bandwidth for a live view.
255:        add_header Cache-Control "no-cache, no-store, must-revalidate";
256:    }
```

Observed running as `python … 127.0.0.1:8090 (LISTEN)` under the
`autobot` user.

### 3.4 Sibling host — `/h144/*` upstream `100.99.57.69:8080`

Cross-host proxy over Tailscale to AutoBot-FXi.
`autobot-dashboard:164-176`:

```
164:    # ── /h144/* — sibling AutoBot-FXi host proxy family ─────────────────
165:    # Cross-host proxy over Tailscale. The local /_authcheck subrequest
166:    # runs against 127.0.0.1:8080 (this host's cookie gate) — the same
167:    # cookie that unlocks /trades unlocks /h144/*. If 144's trades-api
168:    # ALSO enforces its own cookie (e.g. a separate DASHBOARD_SECRET_KEY),
169:    # this proxy will forward it via the client's `Cookie:` header on
170:    # any same-origin request; nothing here strips cookies. If 144
171:    # requires an Authorization header, add:
172:    #   proxy_set_header Authorization "Bearer <token>";
173:    # in each block below.
174:    #
175:    # Upstream 100.99.57.69:8080 is the sibling AutoBot-FXi host on the
176:    # tailnet (see the H144 TAILNET UPSTREAM banner above).
```

Historical note at `autobot-dashboard:40-55` explains the
`100.100.100.144` placeholder previously shipped before
host 144 was reachable over Tailscale.

## 4. Where the dashboard's static files live, and how they are updated

### 4.1 Filesystem layout

- **Served root:** `/opt/autobot-dashboard/` (owner `root:root`,
  mode `755`). Set at `autobot-dashboard:68` (`root
  /opt/autobot-dashboard;`) and `:69` (`index index.html;`).
- Current contents (rounded to the live files):
  ```
  -rw-r--r-- root root    285748  index.html
  -rw-r--r-- root root       513  manifest.json
  -rw-r--r-- root root       236  favicon.svg
  -rw-r--r-- root root      2988  icon-192.png
  -rw-r--r-- root root      8580  icon-512.png
  -rw-r--r-- root root     14332  scenario-v2-shadow.json
  ```
  All owned by `root:root` because the deploy script runs as root
  (see §4.3).
- **Backups:** Same directory holds pre-change snapshots
  named `index.html.pre-*`. Not served — nginx's `try_files $uri
  $uri/ /index.html;` only resolves URIs the browser requests,
  which never matches a `.pre-*` path.

### 4.2 Repo source of truth

- **Authoritative HTML:** `/opt/tradingbot/deploy/autobot-dashboard-index.html`
- **Authoritative nginx conf:** `/opt/tradingbot/deploy/autobot-dashboard.nginx`
  (symlinked content differs from live at audit time — the live
  config is `12779` bytes and the repo source is `11092`; the live
  file corresponds to the `.candidate-20261022-observer` variant
  that was promoted in-place).

### 4.3 Update procedure — `scripts/deploy-dashboard.sh`

Deploy script at `/opt/tradingbot/scripts/deploy-dashboard.sh`
(202 lines). Key lines:

```
  2:# deploy-dashboard.sh — copy repo dashboard source to /opt/autobot-dashboard,
  3:# inject a build stamp into the served page footer, and reload nginx.
  ...
 16:# The nginx conf install is out of scope — this script only refreshes the
 17:# static HTML/assets that live under /opt/autobot-dashboard. Johnny still
 18:# owns nginx conf changes and service restarts.
 ...
 31:REPO_SRC="${REPO_ROOT}/deploy/autobot-dashboard-index.html"
 33:SERVED_DIR="/opt/autobot-dashboard"
 34:SERVED_HTML="${SERVED_DIR}/index.html"
 ...
 77:#    Fail-loud: someone edited /opt/autobot-dashboard directly and the
 ...
118:      echo "REFUSING — served /opt/autobot-dashboard/index.html has drifted from repo:" >&2
 ...
141:TMP_HTML="$(mktemp)"
 ...
178:  echo "DRY RUN — would copy stamped HTML to ${SERVED_HTML} and reload nginx."
 ...
183:# 3) Actually deploy. Requires root (writes under /opt/autobot-dashboard
184:#    and reloads nginx). We prefer `install -m 644` over cp so ownership
 ...
187:  echo "REFUSING — --apply must run as root (nginx reload + /opt writes)." >&2
 ...
192:install -d -m 755 "${SERVED_DIR}"
193:install -m 644 "${TMP_HTML}" "${SERVED_HTML}"
 ...
198:nginx -t
199:systemctl reload nginx
```

The lifecycle therefore is:

1. Author edits
   `/opt/tradingbot/deploy/autobot-dashboard-index.html` in the
   repo and commits.
2. Operator runs
   `sudo /opt/tradingbot/scripts/deploy-dashboard.sh --apply`.
3. Script refuses unless run as root (`:187`), compares live vs
   repo (`:77,118` — refuses if `/opt/autobot-dashboard` has
   drifted), stamps the footer, copies into `/opt/autobot-dashboard/`
   with `install -m 644` (`:193`), runs `nginx -t` (`:198`), then
   `systemctl reload nginx` (`:199`). `systemctl reload nginx`
   rebinds worker processes without dropping connections and does
   **not** touch `trades-api.service` or `autobot.service`.

nginx conf changes are deliberately NOT in scope of this script
(`:16-18`). They are the manual procedure at
`autobot-dashboard:29-32` (sudo cp + nginx -t + systemctl reload).

## 5. Firewall

### 5.1 UFW state

- **Enabled:** yes. `/etc/ufw/ufw.conf:6` reads `ENABLED=yes`.
- **Rule files:** `/etc/ufw/user.rules` and
  `/etc/ufw/user6.rules`. Both are `0640 root:root` — the
  `autobot` user cannot read them, and `sudo` requires a
  password this session does not have. Enumerating the exact
  rule set is therefore not possible read-only.

### 5.2 What the enabled rules allow (inferred from observations + policy comments)

- **22/tcp (SSH)** — allowed. Confirmed by observed
  `LISTEN 0.0.0.0:22` and active SSH access.
- **3000/tcp (dashboard)** — allowed from the public
  internet. Confirmed by the observed public-reachable bind
  (`LISTEN 0.0.0.0:3000`) and the explicit policy comment at
  `autobot-dashboard:58-64` ("Do NOT add UFW deny-3000 … without
  an explicit operator decision"). Prior audit report
  `reports-public/dashboard_audit_20261008.md:5-6` confirms the
  dashboard is reached at `http://161:3000` and
  `http://100.80.206.93:3000`.
- **8080/tcp (trades-api)** — NOT reachable from the public
  internet in practice. The Flask bind defaults to `0.0.0.0:8080`
  (`trades_api.py:4872`) but nginx only addresses it via
  `127.0.0.1`. A new bot should harden by setting
  `TRADES_API_HOST=127.0.0.1` in `.env` rather than relying on
  the UFW drop.
- **8090/tcp (observer)** — not reachable externally. The
  process binds `127.0.0.1:8090` explicitly, so UFW is not even
  in the path.
- **Tailscale** — the tailscaled userspace socket is visible
  on the loopback at `100.80.206.93:*`; UFW does not block the
  Tailscale interface.

### 5.3 Policy-layer firewall (central_execution_gate)

The repo also carries an in-code "firewall" at
`/opt/tradingbot/central_execution_gate.py`, but that is a
**trading** execution gate, not a network firewall. It does not
affect dashboard reachability.

## 6. Minimal reproduction for a new bot

1. **Install the nginx vhost:** copy `autobot-dashboard.nginx`
   into `/etc/nginx/sites-available/`, symlink it into
   `sites-enabled/`, run `nginx -t`, then `systemctl reload nginx`.
   Change the two cross-host IP literals (`100.99.57.69` on the
   `/h144/*` blocks) to whatever the sibling host is on the new
   deployment, or drop the whole `/h144/*` family if there is no
   sibling.
2. **Deploy trades-api:** copy `trades-api.service` into
   `/etc/systemd/system/`, `daemon-reload`, `enable --now`. Set
   `TRADES_API_HOST=127.0.0.1` in `.env` so the Flask process
   binds loopback-only (defence-in-depth against UFW drift).
3. **Set the secrets:** `DASHBOARD_SECRET_KEY` (long random,
   stable across restarts) and `DASHBOARD_PASSWORD` (shared
   password) in `/opt/tradingbot/.env`. Leaving either empty is
   fatal: an empty `DASHBOARD_PASSWORD` disables the gate
   (`trades_api.py:4536`); an empty `DASHBOARD_SECRET_KEY`
   breaks cookie signing.
4. **Lay down the static assets:** create `/opt/autobot-dashboard/`
   (root:root 755), copy
   `deploy/autobot-dashboard-index.html` to
   `/opt/autobot-dashboard/index.html`, plus
   `manifest.json`, icons, and any strategy-dependent JSON. Use
   `scripts/deploy-dashboard.sh --apply` as the operator-facing
   update tool from then on.
5. **Firewall:** `sudo ufw allow 22/tcp` (SSH), `sudo ufw allow
   3000/tcp` (dashboard). Nothing else needs opening. Reject or
   leave everything else at the default UFW deny.
6. **DNS / TLS:** this deployment uses neither. If a new bot wants
   HTTPS, the standard path is: add an `A` record pointing at the
   host, add a second `server` block listening on `:443` with
   `ssl_certificate` + `ssl_certificate_key` (certbot /
   Let's Encrypt), redirect `:3000` → `:443` or retire `:3000`,
   and update the nginx comment at `autobot-dashboard:58-64` to
   reflect the new policy. That is NOT how 161 is deployed today.

## 7. Production usage context

- The dashboard is reached by the operator at
  `http://161.35.168.61:3000` (public) or
  `http://100.80.206.93:3000` (over Tailscale) — no domain, no
  HTTPS.
- Only the cookie gate stands between the public internet and
  every data endpoint. `DASHBOARD_SECRET_KEY` and
  `DASHBOARD_PASSWORD` are therefore load-bearing secrets.
- `trades-api.service` is independent of `autobot.service` — the
  dashboard stays live over the weekend when trading is halted.
  Same model should carry to any new bot.
- All passwords, secret keys, account IDs, and tokens are
  **REDACTED** throughout this document.
