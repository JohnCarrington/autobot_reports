# autobot_reports

Public copies of AutoBot-FXi engineering reports and post-mortems.

## Redaction notice

This is a **public** mirror. Every report here has been scrubbed for public
exposure. The private originals are kept elsewhere and are not published.

Substitutions applied throughout:

| Original class | Rendered here as |
|---|---|
| Host IP addresses | short host labels — `144`, `161`, `OG`, `sentinel`, `178` |
| Broker account numbers | `ACCT-1` |
| IG deal ids | `DEAL-01` … `DEAL-51` (stable across every file) |
| IG deal references | `DEALREF-01`, `DEALREF-02` |
| Internal signal UUIDs | `SIGID-01` … `SIGID-05` |
| The retired project name | the current name, `FXi` / `AutoBot-FXi` |
| Credential values (usernames, hashes) | removed, with the finding kept |

Pseudonyms are **stable**: `DEAL-47` is the same trade in every file that
mentions it, so cross-report joins still work. They are **not** reversible
without the private mapping, and they do not preserve any structure of the
original strings (ordering, shared prefixes, character distances).

Where a report's argument depended on the literal text of a redacted string,
the surrounding prose was rewritten to say so rather than left to read as a
claim about the pseudonym.

The git history of this repository was rewritten on 2026-07-30 to a single
initial commit; earlier history carried the retired project name and personal
committer identities.
