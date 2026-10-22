# CLAUDE.md — Indian equity swing-trading research (paper only)

## Non-negotiable rules
1. **Paper trading only.** Never place, submit, or write code that sends real orders. There is no live
   broker adapter; `get_broker()` refuses anything but paper. Do not relax the guard, the hook, or
   `config/settings.yaml` limits. Live trading needs a separate, explicit written authorization from the
   project owner after research, operational and regulatory review.
2. **Never invent data.** No made-up candles, prices, volume, news or filings. If essential data is stale,
   inconsistent or missing, the answer is `DATA INSUFFICIENT`.
3. **Never ask for secrets in chat.** Credentials live in environment variables / the environment's secret
   store. Never commit `.env`.
4. **No probability claims** ("high probability", "likely to win") without calibrated out-of-sample evidence
   recorded in `docs/validation/`.
5. **Zero trades is acceptable.** At most 2 new candidates per day, as a ceiling. Never loosen criteria to
   produce a signal.
6. **Label every statement** as verified fact (with source + timestamp), calculated indicator, hypothesis,
   or model interpretation.

## On every session start, read
- This file, `docs/risk-policy.md`, `docs/data-sources.md`, `docs/mcp-inventory.md`
- `experiments/registry.csv` and the current spec in `docs/strategy-specifications/`
- The latest `reports/` and `journal/` entries
- The relevant skill in `.claude/skills/` for the task at hand

## Signal statuses
`TRADE CANDIDATE` · `WATCHLIST` · `REJECTED` · `NO TRADE` · `DATA INSUFFICIENT` — produced only through
gates 1–9 (see the `signal-gates` skill). The risk-manager and independent-auditor agents can veto.

## Risk limits (paper phase; enforced in code)
0.5% planned risk per position · 2% aggregate open planned risk · no leverage, margin, derivatives ·
no averaging down · no widening stops. Gaps can lose more than planned; say so in reports.

## Change control
Every strategy or parameter change: add a row to `experiments/registry.csv` and a changelog entry in the
strategy spec (what, why, old→new version, tests run, impact on earlier results, whether a new holdout
evaluation is needed). Never delete failed experiments. Never tune on the holdout.

## Dev workflow
- `uv venv .venv && uv pip install -e '.[dev]'`, then `.venv/bin/python -m pytest -q`
- Tests must pass before each commit. Work phase by phase (see README).
- Data under `data/` is git-ignored; NSE data is for educational/informational use only.
