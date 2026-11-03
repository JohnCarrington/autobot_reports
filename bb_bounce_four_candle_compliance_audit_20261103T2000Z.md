# BB_BOUNCE Four-Candle Strategy Compliance Audit

**Auditor:** AutoBot session, 2026-11-03 20:00 UTC
**Mode:** READ-ONLY. No code, config, service, position or order modified.

## Verdict (headline)

The nine trades on 2026-11-03 **do not** faithfully execute an operator-written **"four-candle"** strategy because **no four-candle specification exists in the codebase**. The in-tree specification — `strategy.py` docstring, tests `BB01–BB15`, and every related commit — describes a **three-candle setup followed by immediate MARKET entry on the confirmation bar's close**. The nine trades correctly implement that in-tree specification.

**I cannot locate a four-candle specification document in the repository, commit history, tests, or branch tips.** If such a specification exists outside the repo (operator's private notes, chat logs, verbal direction), the audit cannot verify compliance against it. **Marking the trades UNVERIFIED against the operator's four-candle intent is the correct audit action.**

Separately, **no commit has weakened the strategy from a four-candle to a three-candle design** — the three-candle design has been present since the original Stage 2 build commit `366fcf6` on 2026-10-10. If the strategy was intended to be four-candle, the gap is an original-build incompleteness, not a regression.

---

## 1. Original strategy specification — recovery

### 1a. Specification sources searched

| Source | Found | 4-candle reference? |
|---|---|---|
| `/opt/bb_bounce/README.md` | Yes | No — only general description |
| `/opt/bb_bounce/BB_BOUNCE_ENHANCEMENT_DELIVERABLES.md` | Yes | No — focuses on STRUCTURAL_3 stop |
| `/opt/bb_bounce/TRADING_HOURS_DEPLOYMENT.md` | Yes | No — trading-hours gate only |
| `/opt/bb_bounce/strategy.py` docstring | Yes | **No — describes 3 candles (A4-A10)** |
| `/opt/bb_bounce/tests/test_bb_acceptance.py` | Yes | **No — tests 3-candle flow BB01-BB15** |
| `/opt/bb_bounce/tests/*.py` | Yes | **No match on "C4", "candle_4", "four", "fourth"** |
| Git log all branches | 25 commits | **No commit message references "4 candles" / "C4"** |
| Design docs under `/opt/bb_bounce/docs/` | Does not exist | — |
| Backup directories under `/opt/bb_bounce/backups/` | Yes | None contain 4-candle spec |

**One incidental "4-candle" string** at `tests/test_bb_acceptance.py:167`:
```python
# 4 candles between C2.close and the confirmation candle.
```
Context: this is test BB10 which validates that confirmation CAN occur up to 30 min after C2 — so 4 waiting bars + 1 confirmation bar is a valid sequence. **It does NOT describe a 4-candle setup; it describes a window that can contain 4 waiting candles.**

### 1b. In-tree specification — the operator-approved rules in `strategy.py:1-32`

Verbatim from the docstring (indentation preserved):

```
A4   BB(20, 2) population stdev on closes, band computed at the
     bar in question (that bar + 19 before).
A5   C1: BUY = red + low < lower_band at C1; SELL = green +
     high > upper_band at C1. Doji (close == open) cannot be C1
     or C2.
A6   C2 immediately follows C1 (exactly +5 min). BUY C2 = green +
     close > lower_band at C2 (strictly). SELL C2 = red + close <
     upper_band at C2 (strictly). C2 HIGH and LOW frozen for the
     lifetime of the setup.
A7   30 minutes measured from C2 CLOSE: a candle whose CLOSE is at
     or before C2.close + 30 min can confirm; a candle whose CLOSE
     is beyond that boundary cannot.
A8   BUY confirm: close >= C2.high (equality confirms); BUY cancel:
     close <= C2.low (equality cancels). SELL mirrored.
A9   Missing candle: if the candle at C1.ts + 5 min never arrives
     (i.e. the next candle received has a timestamp > C1.ts + 5
     min), ARMED setups cancel. AWAITING_CONFIRMATION setups are
     unaffected.
A10  One open trade per direction. Confirm-while-same-direction-
     open → cancelled. Opposite-direction may arm/wait freely.
```

**The in-tree specification describes exactly three candles** (C1, C2, confirmation = Cn) and does not define a fourth-candle condition for entry.

### 1c. What `strategy.py` + `main.py` + `trade_runner.py` do

The engine's loop in `main.py:179-184`:
```python
events = strategy.on_candle(c, list(closes), open_dirs)
for ev in events:
    if ev.kind is EventKind.OPEN_TRADE:
        trader.open_on_confirm(ev)
```

**Entry fires immediately upon receiving an OPEN_TRADE event, which is emitted inside `Strategy.on_candle()` when the confirmation condition triggers.** The MARKET order is submitted as the next action after the confirmation bar's close. There is **no bar-level wait between confirmation and entry.**

### 1d. The operator's four-candle framing in the current task

Operator stated:
- Candle 1: Bollinger Band pierce
- Candle 2: Rejection/reversal candle
- Candle 3: Confirmation candle
- Candle 4: Entry candle

The in-tree spec defines Candle 1 + Candle 2 + Confirmation. **The operator's "Candle 4: Entry candle" has two possible interpretations:**

- **Interpretation A (loose):** The 4th candle is the bar DURING WHICH the MARKET order's fill occurs. Since the order is submitted at the C3 bar's close, the actual fill prints during the next 5-minute bar (observed fills 21-30s into that bar). In this reading, implementation is COMPLIANT.
- **Interpretation B (strict):** The 4th candle is a required WAIT period or qualifying filter between confirmation and entry. If an additional check (e.g., "next bar must also close beyond C2.low") was intended, implementation is NON-COMPLIANT (missing filter).

**The in-tree spec does not describe Interpretation B.** No test asserts a 4th-candle qualifying filter. No commit implements one. If the operator's original intent was Interpretation B, that intent was never written to code.

---

## 2. Production implementation audit (operator §2 questions)

| # | Question | Answer | Evidence |
|---:|---|---|---|
| a | Does the strategy require four distinct candles? | **No** — spec requires 3 (C1, C2, confirmation). Entry is on confirmation bar's close, filling in the next bar. | `strategy.py:1-32` + state machine lines 150-220 |
| b | Are rejection and confirmation candles required to CLOSE? | **Yes.** C2 is evaluated at close (color + close inside band). Confirmation checked on close (`c.close >= c2.high` / `c.close <= c2.low`). | `strategy.py:168-172`, `strategy.py:200-215` |
| c | Can a wick alone satisfy rejection? | **No.** C2 requires both correct color (close vs open) AND close strictly inside the band. Wick alone fails. | `_c2_passes_buy` / `_c2_passes_sell` at `strategy.py:109-115` |
| d | Can confirmation occur INTRABAR? | **No.** `Strategy.on_candle` is called ONLY with completed 5m bars. `main.py` tails the completed-bar archive. No intrabar confirmation path exists. | `main.py:170-184`, `candle_reader.py` |
| e | Can a trade open on the SAME candle as confirmation? | **Yes — the trade order is submitted immediately on the confirmation bar's close.** The MARKET order fills during the next bar's open, but no logical check runs on that next bar. | `main.py:181-184`, `trade_runner.py:471+` |
| f | Are candle indices correctly aligned? | **Yes.** C2 must be `C1.ts + exactly 5 min` (line 155-160); any gap triggers `C2_MISSING`. | `strategy.py:155-166` |
| g | Can one candle satisfy multiple stages? | **No** — commit `030ccf3` (2026-10-11) fixed the self-confirm defect: C2 cannot confirm itself. C1 cannot be C2 (different timestamp). Confirmation must be strictly after C2.ts. | `strategy.py:184-186` (the `if c.ts == s.c2.ts: continue` guard) |
| h | Can the engine reuse a previous rejection signal? | **No.** Each ARMED setup corresponds to a single C1; C2_FAIL / C2_MISSING / EXPIRED finalise the setup; a NEW C1 starts a fresh setup. | `strategy.py:_finalise()` + state transitions |
| i | Can a setup trigger multiple entries? | **No.** Once CONFIRMED, the setup is finalised. The admission guard in `trade_runner._check_admission` additionally blocks concurrent same-direction opens. | `trade_runner.py:_check_admission()` |
| j | Have later changes weakened or bypassed the original rules? | **No regression weakening the 3-candle rules.** All post-Stage-2 commits added SAFETY (admission guard, structural stop, trading hours, direction gate). No commit removed or weakened an A4–A10 rule. | Full commit log review (see §5) |

---

## 3. Trade-by-trade compliance against the in-tree 3-candle spec

**Reconstructed from 5m candle archive** (`/opt/tradingbot/data/candles/GBPUSD/2026-11-03.csv`) + strategy CSV. Tick-level evidence unavailable (post-April 2026 tick archive has only 2-decimal rounded mids, unusable at the pip level).

### Compliance verdict table

| # | setup_ts (C1) | C1 pierce? | C2 ts | C2 red+inside? | C3 ts | C3 close ≤ C2.low? | Within 30 min? | **Verdict** |
|---:|---|---|---|---|---|---|---|---|
| 1 | 00:20 | YES | 00:25 | YES | 00:40 | YES (13402.95 ≤ 13412.25) | YES | **COMPLIANT** |
| 2 | 03:35 | YES | 03:40 | YES | 03:45 | YES (13404.75 ≤ 13405.05) | YES | **COMPLIANT** |
| 3 | 04:05 | YES | 04:10 | YES | 04:15 | YES (13407.35 ≤ 13407.45) | YES | **COMPLIANT** |
| 4 | 05:35 | YES | 05:40 | YES | 05:45 | YES (13414.15 ≤ 13415.45) | YES | **COMPLIANT** |
| 5 | 08:05 | YES | 08:10 | YES | 08:15 | YES (13421.05 ≤ 13424.15) | YES | **COMPLIANT** |
| 6 | 12:10 | YES | 12:15 | YES | 12:25 | YES (13409.35 ≤ 13411.95) | YES | **COMPLIANT** |
| 7 | 13:10 | YES | 13:15 | YES | 13:20 | YES (13415.35 ≤ 13416.35) | YES | **COMPLIANT** |
| 8 | 13:40 | YES | 13:45 | YES | **14:00** | YES (13415.25 ≤ 13417.75) | YES | **COMPLIANT** |
| 9 | 14:50 | YES | 14:55 | YES | 15:00 | YES (13424.55 ≤ 13427.35) | YES | **COMPLIANT** |

**All 9 trades passed every A4-A10 rule.** For each trade I verified:
- C1 was a GREEN candle with `high > upper_bb` (SELL arm condition)
- C2 was exactly 5 min after C1, was a RED candle, and closed strictly inside the upper band
- Confirmation bar's close was ≤ C2.low (strict inequality or equality — spec A8 says equality confirms for SELL)
- Confirmation close occurred within 30 min of C2.close

**Trade 8 note:** Trade 8's confirmation bar is 14:00 (C2 + 3 bars = 15 min), not 13:50. The 13:50 and 13:55 bars did NOT confirm (closes 13419.95 and 13422.05 both > c2.low = 13417.75). The 14:00 bar closed at 13415.25 — first bar after C2 to satisfy the confirm rule. **This confirms the "wait for valid confirmation" semantics are working correctly.**

### Entry timing vs c3.close vs next-bar open

| # | c3.close | next_bar_open | fill_price | fill − c3.close | fill − next_open |
|---:|---:|---:|---:|---:|---:|
| 1 | 13402.95 | 13403.05 | 13403.1 | +0.15 | +0.05 |
| 2 | 13404.75 | 13404.65 | 13404.0 | −0.75 | −0.65 |
| 3 | 13407.35 | 13407.45 | 13406.7 | −0.65 | −0.75 |
| 4 | 13414.15 | 13413.85 | 13413.4 | −0.75 | −0.45 |
| 5 | 13421.05 | 13421.25 | 13420.7 | −0.35 | −0.55 |
| 6 | 13409.35 | 13409.25 | 13408.5 | −0.85 | −0.75 |
| 7 | 13415.35 | 13415.15 | 13414.9 | −0.45 | −0.25 |
| 8 | 13415.25 | 13415.15 | 13414.1 | −1.15 | −1.05 |
| 9 | 13424.55 | 13424.65 | 13423.4 | −1.15 | −1.25 |

The fill prices track between c3.close and next bar open with small variance consistent with MARKET order slippage. **This is the pattern of "submit MARKET on c3 close, fill a few seconds later during next bar's early price activity"** — no intermediate check on a 4th qualifying bar.

### Did the required four-candle sequence genuinely occur before entry?

**Per in-tree 3-candle spec: YES for all 9 trades.**

**Per operator's current "four-candle" framing (strict interpretation B — 4th qualifying candle): CANNOT VERIFY — the specification itself is absent from the codebase, so there is no concrete rule to test.**

All 9 trades MUST be marked **UNVERIFIED** against an operator-held four-candle specification. I cannot confirm or deny compliance without that spec in writing.

---

## 4. Specification vs implementation matrix

| Row | Original strategy.py A-rule | Current implementation | Evidence | Compliant? | Defect location |
|---|---|---|---|---|---|
| 1 | A5: C1 red + low < lower (BUY) / C1 green + high > upper (SELL); doji excluded | `_c1_qualifies_buy / _sell` at `strategy.py:103-108` + `c.is_green/is_red` on `Candle` type | Code paths match spec exactly; 9/9 trades verified | **YES** | n/a |
| 2 | A6: C2 exactly +5 min after C1; correct color + strictly inside band | Loop at `strategy.py:155-172` enforces `c.ts == c1.ts + 5min` + `_c2_passes_*` | 9/9 trades verified | **YES** | n/a |
| 3 | A7: confirmation within 30 min of C2.close | Loop at `strategy.py:194-199` boundary check | 9/9 trades verified | **YES** | n/a |
| 4 | A8: confirm rule inequality (equality confirms for the favourable direction) | Code at `strategy.py:200-215` and SELL mirror | 9/9 trades verified | **YES** | n/a |
| 5 | A9: missing C2 → cancel ARMED | `strategy.py:159-166` emits C2_MISSING | No violations today (all C2s present) | **YES** | n/a |
| 6 | A10: one trade per direction; same-dir confirm → CANCEL_SAME_DIR_OPEN | `strategy.py:203-209` + admission guard | No concurrent same-dir attempts observed | **YES** | n/a |
| 7 | C2 cannot self-confirm | `strategy.py:184-186` skip rule | Fixed by commit 030ccf3 | **YES (post-fix)** | n/a |
| 8 | **Operator's four-candle intent (if intended)** | NOT IMPLEMENTED | No code checks a 4th-candle condition | **UNVERIFIED** (no written spec) | would need new code in `trade_runner.open_on_confirm` or `strategy.on_candle` |

**All implemented in-tree rules are compliant.** The only gap is between the operator's current "four-candle" framing and the in-tree three-candle specification — and that gap has existed since the original build.

---

## 5. Regression history — did the strategy start as four-candle and get shortened?

Full BB_BOUNCE commit log reviewed:

| commit | date | subject | affects C1/C2/C3 rules? |
|---|---|---|---|
| 55093b3 | 2026-10-29 | C5 — H1-direction gate on RANGE/NORMAL (default OFF) | No — new filter |
| ef127a0 | 2026-10-29 | trading-hours operator corrections | No — session gate |
| a2c8b48 | 2026-10-29 | standalone BB Bounce admission gate | No — session gate |
| e6ad977 | 2026-10-28 | SL target 12 → 4 pips with IG-min-widen (FIXED_12) | No — stop size change |
| fe05b4d | 2026-10-28 | broker TP 30 → 100 pips | No — TP size |
| 5c5b73b | 2026-10-28 | formalise 2026-10-28 dynamic IG min-stop | No — stop sizing |
| fb9d3f5 | 2026-10-27 | WATCH_AND_WAIT fail-closed | No — NMS filter |
| a372851 | 2026-10-27 | WATCH_AND_WAIT consumer | No — NMS filter |
| 23bec41 | 2026-10-27 | EMERGING counter-bounces require exhaustion | No — NMS filter |
| c672194 | 2026-10-27 | Phase 2B unified NMS authority with exhaustion | No — NMS filter |
| 5f54715 | 2026-10-26 | BLOCKED broker status: no uncertain-state trap | No — admission |
| 60a6ca5 | 2026-10-26 | session-trend-guard tests | No — tests |
| c3bf2d3 | 2026-10-23 | broker close resolution via transactions | No — reconciliation |
| 5192ba1 | 2026-10-21 | stale-tiring EMERGING tests | No — tests |
| ef0e951 | 2026-10-19 | bounce rulebook tests (29 cases) | No — tests |
| 0a76b3d | 2026-10-18 | BOUNCE rulebook — standalone bb-bounce | No — direction gate design |
| da1babd | 2026-10-12 | session-trend counter-trend guard | No — direction gate |
| 542746a | 2026-10-12 | deploy enhancements merge | No — deploy mechanics |
| d82c742 | 2026-10-12 | positions VERSION=2 test | No — IG API |
| fb4ebaa | 2026-10-12 | pin /positions VERSION=2 | No — IG API |
| d1a88d3 | 2026-10-12 | never retry OTC create on 401 | No — IG API |
| 267b669 | 2026-10-12 | reconciliation repair | No — reconciliation |
| 983d14a | 2026-10-12 | admission guard — duplicate orders | No — admission |
| 70f1730 | 2026-10-12 | STRUCTURAL_3 stop mode + risk controls | No — stop mode |
| 030ccf3 | 2026-10-11 | **C2 must not confirm or cancel its own setup** | **YES — tightens C2 rules (safer)** |
| bb13461 | 2026-10-11 | same as 030ccf3 (merge) | YES — same fix |
| d3824e8 | 2026-10-11 | A17 structural failure exit | No — exit mode |
| **366fcf6** | **2026-10-10** | **Stage 2 build — standalone GBPUSD BB-bounce strategy** | **ORIGINAL BUILD — 3-candle** |

### Verdict on regression

**No commit shortened or weakened a four-candle sequence into a three-candle one.** The original Stage 2 build (`366fcf6`, 2026-10-10) created the 3-candle flow and all 76 original tests validated it. Subsequent commits:
- Added safety (admission, structural stop, direction gates, trading hours)
- Fixed one real defect (`030ccf3`: C2 self-confirm — TIGHTENED the rules)
- Changed sizing (TP 30→100, SL 12→4+widen)

**If a four-candle requirement was intended, it has never been implemented.** This is an original-build situation, not a post-build regression.

### Do the tests validate the current code or the operator's original intent?

**They validate the current code.** The 15 acceptance tests in `tests/test_bb_acceptance.py` (BB01–BB15) are byte-exact mirrors of the state machine's behaviour. They assert:
- BB05: "C3 closes above C2.high → OPEN_TRADE" — exactly what the code emits
- BB06: "C3 closes below C2.low → OPEN_TRADE" — exactly what the code emits
- BB10: Confirmation up to 30 min after C2.close works — matches A7
- BB11: 7th candle after C2 → EXPIRED — matches A7

The tests are **implementation-driven** (test what the code does) rather than **specification-driven** (test what a separate document says the code should do). This is a documented pattern — the strategy.py docstring IS the specification, and the tests implement that docstring.

**If an operator-held four-candle specification differs from strategy.py's docstring, the tests would not catch that discrepancy — because the tests encode the three-candle docstring.**

---

## 6. Report-only — findings and recommendations

### Confirmed findings

1. **9/9 trades today executed the in-tree three-candle specification correctly.** No implementation defect, no missing step, no bypassed rule.

2. **The in-tree specification (strategy.py docstring A4-A10) describes three setup candles + immediate MARKET entry on confirmation close.** No fourth-candle condition is defined.

3. **No commit weakened or shortened the strategy.** The three-candle design has been constant since 2026-10-10. All subsequent changes added safety, not features.

4. **Tests validate the code's behaviour**, not an independent specification. A specification–implementation gap would not be visible via the test suite.

### Unverified claims

1. **Whether the operator's original four-candle intent was ever written down.** I did not find such a document in the repo. If it exists outside the codebase (operator's private notes, email, chat log), the audit cannot assess compliance against it.

2. **The exact meaning of "Candle 4: Entry candle"** in the operator's current framing. Under Interpretation A (loose), implementation is compliant. Under Interpretation B (strict qualifying check), implementation is non-compliant with a never-defined rule.

3. **Whether tick-level entry behaviour matches operator intent.** Certified tick data for 2026-11-03 is unavailable; 5m candle approximations have been used.

### Recommended operator decisions (NOT implementing anything)

1. **Clarify "Candle 4: Entry candle" semantics.** Does the operator intend:
   - (a) The post-confirmation bar during which the MARKET order fills — current behaviour, no code change; OR
   - (b) An additional qualifying bar check between confirmation and entry (e.g., "entry only if the bar after confirmation also closes beyond C2.low") — would require new code.

2. **If (b) is the intent, provide the exact Candle 4 rule.** The implementation can then be audited against that rule and (if required) extended.

3. **If (a) is the intent, document it explicitly in `strategy.py` docstring** so future auditors do not re-raise the ambiguity. Add a short section after A10:

```
A11  Entry: MARKET order submitted immediately upon receiving an
     OPEN_TRADE event on the confirmation bar's close. The fill
     occurs during the next 5-minute bar at IG market price. No
     additional check is performed on the fill bar.
```

This is a documentation addition only; no code change. **I have not made this edit.** It is a proposal for operator approval.

### What this audit DID NOT do

- Change any code, config, parameter, service, position or order
- Introduce shadow mode
- Optimise or redesign the strategy
- Make any claim about whether BB_BOUNCE "should" be a 4-candle strategy — only whether the implementation matches a hypothetical 4-candle spec

---

## 7. Preservation certification

- `/opt/bb_bounce/` production: UNCHANGED (service PID 2400402 preserved)
- `/opt/tradingbot/bounce_engine/v3/`: UNCHANGED since 16:44 UTC fix (SHA `38fb8d92eee70c9e94f5d5f93e31a1a746c70ab046de991ef469698d845c7062`)
- autobot PID 3504088 preserved
- NMS C1+C2+C6 unchanged
- C6 midnight verification 2026-11-04 00:00 UTC still scheduled, OUTSTANDING, untouched
- No `.env` modification
- No broker API write
- All audit artefacts isolated to `/mnt/volume_lon1_1778405456698/bb_bounce_compliance_audit_20261103/`

---

## Appendix — evidence paths

| Evidence | Path |
|---|---|
| 9-trade reconstruction | `/mnt/volume_lon1_1778405456698/bb_bounce_compliance_audit_20261103/trade_reconstruction.txt` |
| BB_BOUNCE in-tree spec | `/opt/bb_bounce/strategy.py:1-32` |
| BB_BOUNCE strategy state machine | `/opt/bb_bounce/strategy.py:120-250` |
| BB_BOUNCE acceptance tests | `/opt/bb_bounce/tests/test_bb_acceptance.py` (15 tests, BB01–BB15) |
| C2 self-confirm fix test | `/opt/bb_bounce/tests/test_c2_no_self_confirm.py` |
| BB_BOUNCE trade_runner entry logic | `/opt/bb_bounce/trade_runner.py:471+` (`open_on_confirm`) |
| BB_BOUNCE main loop | `/opt/bb_bounce/main.py:170-200` |
| Original Stage 2 build | `git show 366fcf6` in `/opt/bb_bounce/` |
| C2 self-confirm fix | `git show 030ccf3` in `/opt/bb_bounce/` |
| GBPUSD 5m candles today | `/opt/tradingbot/data/candles/GBPUSD/2026-11-03.csv` |
| Nov 3 BB_BOUNCE trades | `/opt/bb_bounce/reports/2026-11-03.csv` |
| trades-api authoritative ledger | `http://127.0.0.1:8080/trades` filter `host_prefix=HBB` |

**Audit complete. Awaiting operator clarification on Candle 4 intent before any further action.**
