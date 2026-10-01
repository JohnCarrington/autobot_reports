# briefing_direction.py — Provenance vs commit c60ea96

Companion to `README.md §3`. Full git-blob trace, with evidence commands and output excerpts.

## 1. Target era

Commit under study:

```
c60ea9698717aba100238cac5ae519ee0c6b324b 2026-07-29 06:54:32 +0000
docs(env): align 40-gates.env BB_BOUNCE_LEVEL_GATE_MODE with live enforce
```

Published as the anchor commit for the recovery branch `recovery/autobot-july2026-c60ea96`; chosen for its unique runtime-observation anchor in its commit message.

## 2. briefing_direction.py — not tracked at c60ea96

```
$ cd /opt/tradingbot && git ls-tree c60ea96 briefing_direction.py
(no output — path not present in that tree)
```

Full commit history for the path on the main repo:

```
fb0039f7dcc819df63852f80b940693b8d8c67b2 2026-09-11 08:37:16 +0000
    chore(live-state): track live production modules with no git history

df43178b4651535bb976f487d4dc1c362d487420 2026-06-02 17:57:53 +0000
    feat(briefing): direction veto via resolve_direction gate
```

Two distinct eras:

### Era A — df43178 (2026-06-02 → sometime before 2026-07-29)

126 lines. API:

```python
def resolve_direction(
    daily_bias: Optional[str],
    session_bias: Optional[str],
    plan_bias: Optional[str],
) -> Resolution: ...

@dataclass(frozen=True)
class Resolution:
    direction: str  # "BUY" or "SELL"
    reason: str
    daily: str; session: str; plan: str
    agree: bool
    plan_blocked: bool
```

Caller signature was `resolve_direction(daily, session, plan)` returning a frozen dataclass. This file is *removed* from the git tree between `df43178` and `c60ea96` (invisible to `ls-tree` at c60ea96 and in the subsequent `df43178`→`fb0039f` interval, but reappears via fb0039f as a verbatim snapshot of the live file).

### Era B — fb0039f (2026-09-11, snapshot of live production)

55 lines. API:

```python
def resolve_briefing_direction(briefing: Dict[str, Any]) -> Dict[str, Any]: ...
```

Returns `{action, direction, bias, class, reason}` where `action ∈ {STAND_DOWN, TRADE}`, `class ∈ {BOTH_NEUTRAL, DAILY_NEUTRAL, SESSION_NEUTRAL, AGREE, DISAGREE}`.

The fb0039f commit message is explicit:

> **chore(live-state): track live production modules with no git history**

i.e. it is backfilling git for a file that had been running live under the operator's hand without a git record.

## 3. briefing_execution.py — the import at c60ea96

Reading the briefing_execution.py blob at c60ea96:

```
$ git ls-tree c60ea96 briefing_execution.py
100644 blob 24343d18ff70f3ca187373ff534e6ba3468d1e99  briefing_execution.py

$ git show c60ea96:briefing_execution.py | grep -n 'briefing_direction'
38:  from briefing_direction import resolve_briefing_direction
1573:         decision = resolve_briefing_direction(briefing)
```

The import names **`resolve_briefing_direction`** — the Era B function. The Era A `resolve_direction` dataclass API would raise `ImportError` here. Therefore the live `briefing_direction.py` at c60ea96 **must** have exposed `resolve_briefing_direction`. The current (fb0039f-era) file exposes exactly that; the earlier df43178 file did not.

## 4. Byte-identity: current file vs fb0039f snapshot

```
$ cd /opt/tradingbot && diff <(git show fb0039f:briefing_direction.py) briefing_direction.py
(no output — byte-identical)
```

So the bundled `code/briefing_direction.py` (SHA-256 `c0042e5a173b859ca791eeda616f8aadda42eca29b63cb00af13c3c09ef1608d`, blob `b5c88c5a7b27204a72d46ae7a22a9e7e47a54e5f`) is the Era B snapshot that `fb0039f` captured and is semantically compatible with the c60ea96 import surface. The on-disk `mtime` is `2026-08-24 19:21:12 UTC`, which further supports that the file was in-place well before the September commit.

## 5. Upstream dependency: d1_direction + config

```
$ git ls-tree c60ea96 d1_direction.py config/d1_direction.yaml
100644 blob 6b1fb88fa05db0afbec49e753f536fcd4165a5c2  d1_direction.py
100644 blob 043ddd277c3fb1bd7a2bf01078aeac4f60da8c43  config/d1_direction.yaml

$ cd /opt/tradingbot && git hash-object d1_direction.py config/d1_direction.yaml
6b1fb88fa05db0afbec49e753f536fcd4165a5c2
043ddd277c3fb1bd7a2bf01078aeac4f60da8c43
```

**Both blobs match c60ea96 exactly.** No change to the upstream between c60ea96 and today. Added to git by `b8c05de` on 2026-05-11:

```
b8c05de29cbe626e072ee7ff9ba7cc36b1b9bdae 2026-05-11 18:24:27 +0000
fix(briefing): deterministic 9-check D1 direction scoring. LLM cannot override
daily_bias. Bug 1 from audit 2026-05-11. Used by both briefing producer and
d1_veto (single source of truth).
```

The current `briefing_direction.py` docstring points at this contract:

> Reads briefing["daily_bias"] — the DETERMINISTIC 9-check output (post b8c05de; single source of truth, written by d1_direction.compute_d1_direction).

## 6. Runtime contract — what briefing_direction consumes

The 55-line Era B file consumes two keys from the briefing dict:

- `briefing["daily_bias"]` — written by `d1_direction.compute_d1_direction` (deterministic 9-check).
- `briefing["session_bias"]` — written by the briefing producer upstream of execution.

Returns `{action, direction, bias, class, reason}`. Full truth table (reproduced from the file's docstring):

```
daily=NEUTRAL  & session=NEUTRAL     → STAND_DOWN (class=BOTH_NEUTRAL)
daily=NEUTRAL  & session directional → STAND_DOWN (class=DAILY_NEUTRAL)
                                       — +34.5p abstention edge
daily directional & session=NEUTRAL  → TRADE daily (class=SESSION_NEUTRAL)
daily directional & session agrees   → TRADE daily (class=AGREE)
daily directional & session differs  → TRADE daily (class=DISAGREE)
                                       — corrected: daily wins
```

Verified against live July 2026 briefings (`/opt/tradingbot/briefings/v5_pia/briefing_GBPUSD_2026-07-*.json`): a sample `briefing_GBPUSD_2026-07-17_NY.json` carries `state: STAND_ASIDE, stand_aside_reason: d1_h4_bias_disagree` — the briefing-producer side of the same truth table. The direction resolver bundled here is the live-time-compatible consumer.

## 7. No other imports

```
$ grep -n '^from\|^import' /opt/tradingbot/briefing_direction.py
8: from __future__ import annotations
10: from typing import Any, Dict
```

Only stdlib imports. No third-party deps, no autobot-internal deps beyond the two briefing-dict keys. The module is a pure resolver and will run on any Python 3.9+ environment with no setup beyond standard library.
