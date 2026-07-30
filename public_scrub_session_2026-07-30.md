# Public-exposure scrub of this repository — 2026-07-30

**Repo:** `JohnCarrington/autobot_reports` (public)
**Working host:** `144`, as `autobot` (not root)
**Trading service:** untouched throughout — not restarted, no code, config or log file under `/opt/tradingbot` modified by this task.

This repository is a public mirror. Until today it published the retired
project name, a box hostname, four host IP addresses, a broker account
number, 51 broker deal ids, and a git history whose commits carried personal
committer identities. This report records what was removed and how.

Substitution literals are deliberately **not** reproduced here — quoting the
before-side in a public file would undo the scrub. The full reverse map is
held privately on `144` alongside the unredacted originals.

---

## 1. What was scrubbed

19 of the 20 pre-existing report files changed (`test.md`, a two-line
round-trip probe, contained nothing sensitive). 86 distinct substitutions were
applied, by class:

| Class | Distinct substitutions | What it covered |
|---|---|---|
| Network addresses | 10 | 4 host IPv4 addresses + 1 placeholder + 5 phrases using a bare first octet as a host shorthand |
| Retired project name | 12 | 1 bare token, 1 hostname, 1 droplet name, 1 auth realm, and 8 compound identifiers (env flags, module names, package dirs, branch names) |
| Broker account ids | 1 | the live IG account number |
| IG deal ids | 51 | every `dealId` quoted from IG ledgers, logs and confirms |
| IG deal references | 2 | every `dealReference` quoted from an IG order response |
| Internal signal UUIDs | 5 | `signal_log` row ids |
| Credential values | 2 | a live basic-auth username and its bcrypt hash |
| Prose rewrites | 3 | sentences whose argument depended on the literal text of a now-redacted id |

### Replacement scheme

* **Host IPs → short labels.** `144`, `161`, `OG`, `sentinel`, `178`. Five
  phrases in the provenance reports used a bare first octet (`46`) as shorthand
  for one droplet; those were rewritten to the `OG` label so no octet survives.
  Bare `46` still appears in these reports as a price, a timestamp and a source
  line number — those are not addresses.
* **Retired name → current name.** Compound identifiers were mapped to their
  real current equivalents on this box (the rename has already landed in the
  private tree), not to invented strings.
* **Opaque broker ids → stable pseudonyms.** `ACCT-1`; `DEAL-01`…`DEAL-51`;
  `DEALREF-01`…`DEALREF-02`; `SIGID-01`…`SIGID-05`. Numbering is global across
  the corpus, so a cross-report join still resolves: `DEAL-47` is the same
  trade in all six files that cite it.

### Two things pseudonymisation broke, and how they were handled

Broker ids are not interchangeable tokens in these reports — two passages
reasoned about the *characters* in them:

1. A passage arguing that an opening leg and its closing leg are different
   positions cited their shared 10-character prefix and a one-character
   difference. Rewritten to state that the unredacted ids shared a prefix and
   to say explicitly that the pseudonyms do not preserve it.
2. A passage identifying a set of ledger refs by their common leading
   substring. Rewritten to refer to a shared prefix without quoting it.

Left unrewritten but worth naming: one sentence still reads "the two dealId
strings differ character-for-character". That remains true of the originals; it
is not a claim about the pseudonyms.

### The credential finding

One report documented that an nginx dashboard's basic-auth username had not
been renamed. The finding is kept — it is a real piece of outstanding work —
but the username literal and the bcrypt hash are redacted. The section now
says only that the username is a legacy-named literal.

### One accuracy cost, stated plainly

The name-scrub note is a report *about* a rename, structured as before/after
diffs. Substituting the old name for the new collapsed every diff into a
tautology (`-Description=X` / `+Description=X`). Those diffs were re-expanded
with a `<legacy>` / `<LEGACY>` placeholder on the before-side, so the shape of
each change survives without printing the retired token. Elsewhere in the
corpus, directory and module names on the `161` host that still carry the old
name are shown under their `144` equivalents. That is a knowing inaccuracy: on
`161` those paths have not been renamed.

---

## 2. History rewrite

The previous git history exposed the retired name in a commit message and a
reflog entry, and carried three committer identities including a personal
email address across 19 commits.

Replaced with a single orphan commit:

```
initial commit: AutoBot-FXi public reports (scrubbed)
author + committer: AutoBot-FXi <autobot@autobot-fxi.local>
parents: none        rev-list --count: 1
```

Force-pushed over `main`. The local reflog and loose objects were expired and
garbage-collected; `grep -ril` over the resulting `.git/` returns no hits for
the retired name.

### Did anything depend on this repo's history?

Checked exhaustively on `144` before force-pushing — `grep -rIl` for
`reports-shared`, `autobot_reports` and `github-reports` across the whole of
`/opt/tradingbot`, `/home/autobot` and `/etc`:

* No cron entry (`crontab -l` → none for this user), no systemd unit, no
  timer, no rsync invocation, no script of any kind references this repo.
* The only non-transcript hits are one prose sentence in a report and one
  historical tool-permission grant. Neither is a mechanism.

So **nothing on `144` reads this repo at all**, let alone assumes its history.

`161` could not be checked: SSH from `144` to `161` is refused for both
`autobot` and `root` (publickey). If a clone on `161` pulls this repo, that
pull will now fail on unrelated histories and will need a fresh clone. The
operator will confirm `161` separately.

The pre-rewrite history was bundled to a private path on `144` before the
force-push, so the old commits remain recoverable off-line.

---

## 3. Files added in this pass

Two documents were copied in from the private tree and scrubbed to the same
standard before being committed:

* `briefing-audit-2026-07-30.md` — briefing pipeline audit (levels, frequency,
  executor blockers, direction model) over the 20 trading days to 2026-07-30.
* `name_scrub_t0b_2026-07-30.md` — the T0b name-scrub record for changes made
  outside the git tree.

---

## 4. Verification

After the scrub, across every `.md` file in the repository:

```
retired name (case-insensitive)   0 hits
IPv4 addresses                    0 hits
broker account numbers            0 hits
IG deal ids                       0 hits
IG deal references                0 hits
signal UUIDs                      0 hits
email addresses                   1 hit — autobot@autobot-fxi.local, the current bot identity
```

No API keys, session tokens, bearer credentials or `.env` values with
right-hand sides were present in the corpus at any point. The only URLs are
public vendor endpoints.

One rendering caveat: the pseudonym numbering is dense and complete
(`DEAL-01`…`DEAL-51`, no gaps), which was verified programmatically rather
than by eye.

---

*Generated on `144`, 2026-07-30. Read-only with respect to `/opt/tradingbot`:
this task modified only this repository.*
