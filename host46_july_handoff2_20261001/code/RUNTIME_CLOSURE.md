# Runtime closure for the v5_pia briefing producer

The shipped `briefing/v5_pia/` module tree is the **producer**, but at runtime it calls out to a wider set of modules in the AutoBot repo. This document lists the direct imports the producer makes so the operator on host 46 knows what has to be present at run time.

The handoff ships only the producer. The rest of the closure must come from `JohnCarrington/AutoBot.git` at pinned SHA `7d9fb2c97e4ba090cc8f1baf3ab685cd128f231d`.

## Direct imports from `briefing/v5_pia/*`

Enumerated by `ast.walk` on each module in the shipped tree:

```
# standard library (always available on host 46 with Python 3.11+)
__future__, dataclasses, datetime, json, logging, math, os, pathlib,
re, threading, time, typing

# third-party (install from the AutoBot repo's requirements.txt)
pandas, pydantic, requests

# AutoBot repo modules — must be on PYTHONPATH alongside `briefing/`
level_computation          # swing / structural level engine
morning_briefing           # data-package assembler + ANTHROPIC_API_KEY/URL
pair_config                # per-pair constants and symbol → epic map
structural_state           # (indirect, via pair_config)
```

## Why we don't ship `morning_briefing.py` etc.

`morning_briefing.py` is ~196KB and transitively imports ~230 top-level AutoBot modules (the whole runtime closure). That is effectively the entire AutoBot codebase and does not belong in a reports repo. Host 46 should pull the pinned SHA of the AutoBot repo for everything outside `briefing/v5_pia/`.

The shipped `briefing/v5_pia/` is a **byte-identical** copy of the module at that commit (clean working tree at package build time). If host 46 clones the AutoBot repo at `7d9fb2c97e4ba090cc8f1baf3ab685cd128f231d`, overlaying the shipped `v5_pia/` is a no-op.

## Minimum viable boot sequence on host 46

```bash
# 1. Clone AutoBot at the pinned SHA
git clone git@github.com:JohnCarrington/AutoBot.git /opt/tradingbot
cd /opt/tradingbot
git checkout 7d9fb2c97e4ba090cc8f1baf3ab685cd128f231d  # detached HEAD is fine for a fresh host

# 2. Create venv + install deps
python3 -m venv venv
venv/bin/pip install -r requirements.txt

# 3. Configure .env from the shipped template
cp /path/to/handoff/config/env.example /opt/tradingbot/.env
# fill in IG_USERNAME / IG_PASSWORD / IG_API_KEY / TELEGRAM_TOKEN / ...

# 4. Verify the briefing producer loads cleanly
venv/bin/python -c "from briefing.v5_pia import orchestrator; print('v5_pia OK')"

# 5. Install systemd units from config/systemd/ (see config/scheduler.md)
```

## Not required but useful

`briefing/v5_pia/anthropic_client.py` reads `ANTHROPIC_API_KEY` and `ANTHROPIC_URL` from `morning_briefing` at module load. The host 46 `.env` must set:

- `ANTHROPIC_API_KEY=...` (Phase 2 rationale writer)
- Optional: `ANTHROPIC_URL=...` (default is the public Anthropic Messages endpoint)

If `BRIEFING_V5_RATIONALE_ENABLED=0` the rationale writer is skipped and no Anthropic call is made.
