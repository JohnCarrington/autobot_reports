# AutoBot 161 Dashboard — Look & Feel Notes

Companion to `autobot161_dashboard_index_20261108.html` (a redacted copy of
`/opt/autobot-dashboard/index.html` served by nginx on AutoBot 161).
Three items were replaced with `REDACTED` in the HTML: a public server IP
(Sentinel host comment), a tailnet placeholder IPv4 (144 host lookup error
message), and one historical IG dealId cited in a comment. All other
content is unchanged.

## Page structure (top → bottom)

1. **`<head>`** — PWA metadata, theme colour `#0a0a0f`, manifest, favicon,
   Google Fonts preconnect (JetBrains Mono + Syne), one `<style>` block
   holding the entire stylesheet, and a build-tag `<meta>`.
2. **Password-gate overlay** (`#authOverlay`) — full-screen modal with
   "AutoBot" wordmark, single password input, Unlock button, inline error
   slot. Posts the password to the trades-api which sets an HTTP-only
   cookie; the overlay stays until a successful unlock.
3. **Header bar** (`.header`) — left: AutoBot wordmark with a tiny logo
   dot; right: a LIVE/Demo pill (`.live-badge`) that pulses green on LIVE.
4. **System-group tab strip** (`.host-tabs #systemGroupTabs`) — six
   buttons, horizontally scrollable on narrow screens:
   `AUTOBOT · STRATEGIES · OBSERVER · BRIEFINGS · FXi · DEMO`. Active tab
   has a green underline/background; inactive tabs are muted grey.
5. **News banner** (`#newsBanner`) — thin full-width strip that appears
   only when a news window is in-force; left diamond glyph, text, meta
   timestamp on the right.
6. **One `.host-tab-panel` per tab** (only the active one is visible):
   - **AUTOBOT** (`#tabAutobot`): a period selector (`Day · Week · Month ·
     All`), a persistent red "LIVE ACCOUNT — real money — orders are
     real" banner when env=live, env toggle (LIVE/DEMO) + source and
     positions chips, error banner, and the main trades application
     slot. Internally the rows are AutoBot V2 (ONE_STRATEGY, QM_V2,
     V2_PICK_BOUNCE) with a sub-view for Pre-V2 history kept strictly
     separate from the V2 total.
   - **STRATEGIES** (`#tabStrategies`): a strip of host-info chips
     (System · Trading day · 22:00 Europe/London boundary · Generated at),
     then one systemd-style card per deployed strategy service on this
     host — status, today's realised P&L, open-position count, last
     update.
   - **OBSERVER** (`#tabObserver`): Live Market Observer, read-only. Top
     strip shows System / Pair (GBPUSD) / Backend (loopback) / Updated.
     Below are four Scenario Intelligence V2 panels:
     1. **Trade Recommendation** — large blue-bordered card with
        entry/stop/target and provenance.
     2. **Market Bias / Observer Summary** — companion text block.
     3. **Shadow Execution** — scenarios the observer *would* have fired,
        explicitly stamped `SHADOW ONLY`.
     4. **Scenario V2 grid** — tabular scenario list with HIGH / WARN /
        INFO severity badges.
     An iframe below hosts the self-contained observer HTML for full
     detail.
   - **BRIEFINGS** (`#tabBriefings`): same period bar + a strategy pill
     row (`Briefing Suite · BRIEFING_EXECUTION · BRIEFING_V5`), then the
     briefings table and KPI summary.
   - **H144** (`#tabH144`): legacy host panel, hidden under the current
     four-system model. Retained so residual DOM references resolve.
   - **FXi** (`#tabFxi`): information-only; host info strip (System /
     Host / "Trading P&L — information only") then the briefings feed
     from the FXi producer.
   - **DEMO** (`#tabDemo`): experimental sandbox, visually unmistakable —
     dark-red tinted host-info strip with a `⚠ DEMO` label and the line
     "Production total contribution: NONE — demo results are isolated".
     Period bar and an empty experimental-host roster below.
7. **Build-stamp pill** — fixed to the bottom-right corner, muted
   monospace chip (`v3c2-<sha> · <ISO timestamp>`) on a translucent dark
   background.

## Colour palette

Defined as CSS custom properties on `:root`. All panels inherit from these.

| Token              | Value          | Use                                        |
| ------------------ | -------------- | ------------------------------------------ |
| `--bg`             | `#0a0a0f`      | page background (near-black with blue cast)|
| `--surface`        | `#111118`      | cards, tab-panel backgrounds               |
| `--surface2`       | `#1a1a24`      | nested panels, hover fills                 |
| `--border`         | `#ffffff0f`    | hairline dividers                          |
| `--border2`        | `#ffffff18`    | card outlines                              |
| `--text`           | `#e8e8f0`      | body text                                  |
| `--muted`          | `#6b6b80`      | labels, chrome, timestamps                 |
| `--accent`         | `#00ff88`      | primary green — active tab, BOT chip, KPIs |
| `--accent-dim`     | `#00ff8820`    | tinted backgrounds for accented chips      |
| `--accent-mid`     | `#00ff8840`    | accented borders                           |
| `--red`            | `#ff4466`      | losses, LIVE banner, DEMO warning          |
| `--red-dim`        | `#ff446620`    | banner fills                               |
| `--amber`          | `#ffaa00`      | warnings, EXTERNAL provenance chip         |
| `--amber-dim`      | `#ffaa0020`    | warning banners                            |
| `--blue`           | `#4488ff`      | manual/informational chips, recommendation |
| `--blue-dim`       | `#4488ff15`    | panel tints                                |

The overall feel is a near-black cockpit with one dominant green accent,
secondary red for losses/LIVE, amber for warnings, and blue for
manual/informational chrome.

## Typography

- **Display / headings** — `Syne` (weights 400, 600, 800) — used for the
  "AutoBot" wordmark and headline titles.
- **Body / chrome / tables / KPIs** — `JetBrains Mono` (weights 300, 400,
  500, 700). Letter-spacing is tightened on uppercase labels (0.06–0.12em)
  for a terminal aesthetic.
- **Icons** — single unicode glyphs (`◆`, `⚠`, dots) rather than an icon
  font.

## Refresh / polling behaviour

All polling is cookie-authenticated and same-origin to the trades-api.

| Loop                                   | Interval | Notes                                                           |
| -------------------------------------- | -------- | --------------------------------------------------------------- |
| Main active-tab refresh                | **60 s** | `setInterval(..., 60000)` near the end of the file. Re-fetches `trades` / `strategies` / `briefings` / `fxi` for the active tab, plus the news-state banner. Paused when the viewer is unauthenticated, and paused on the AUTOBOT and BRIEFINGS tabs when a historical date is selected so the picker selection sticks. DEMO is a static discovery view and does **not** poll. |
| Observer tab                           | **30 s** | `OBSERVER_REFRESH_MS = 30000`. Pauses when the browser tab is hidden. |
| Scenario V2 shadow-execution panel     | **5 min**| `scenV2ShadowTimer` runs every 300 000 ms within the Observer tab. |
| Initial load                           | once     | `loadStrategyRegistry()`, `fetchTrades()`, `fetchNewsState()` run on page load. |

Historical date selections freeze the tab in place until the user clears
them. All intervals are passive — no WebSocket, no SSE — so the UI
converges within one tick of any backend change.

## Assets referenced

- `/manifest.json` (PWA install)
- `/favicon.svg`
- Google Fonts: JetBrains Mono + Syne (`fonts.googleapis.com`,
  `fonts.gstatic.com` preconnect)

No third-party JS and no external analytics.
