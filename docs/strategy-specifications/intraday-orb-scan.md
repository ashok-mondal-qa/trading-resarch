# Morning opening-range scan (NSE cash, intraday, paper only) — spec v0.2

Status: **pre-registered 2026-10-30, forward tracking from 2026-11-02** (written and committed before any
forward data exists). Code: `src/trading_research/live/intraday_scan.py`. Registry: EXP-0079.

## Why (label: hypothesis)
The owner asked for live intraday ideas. No intraday NSE rule has been tested here: there is no intraday
history in the project (1-minute NSE history needs a paid feed). On 2026-10-30 an ad-hoc noon scan gave two
WATCHLIST ideas (INFY, DIVISLAB); both breakouts failed within hours. Rather than keep improvising, this spec
freezes one simple rule and records it every session, so evidence builds up from data nobody has seen.

Waiting until about 09:30 IST before acting is common practitioner advice (the first 15 minutes are the
noisiest, and the 09:15–09:30 high and low form an "opening range"). That comes from broker and education
articles, not from tested evidence; this experiment is one way to test it.

## Rule (frozen for v0.1)
Run once, weekdays at about 09:35 IST, on NSE `cm-market` MCP quotes (1–3 minutes delayed).
1. Data: newest quote from today and at most 15 minutes old, else `DATA INSUFFICIENT` (also covers holidays).
2. Quote screen (series EQ, not ETFs): traded value so far ≥ ₹10 crore, price ≥ ₹100, change +0.5% to +4%,
   gap at open < 2.5%, last price ≥ open and within 0.6% of the day high.
3. History check (`nse-bhavcopy` MCP, daily, unadjusted): previous close must equal the live previous close;
   ≥ 15 bars for ATR14; last price above the previous day's high.
4. Levels: opening range = day high/low at scan time. Buy-stop 0.05% above the range high (rounded up to
   ₹0.05), stop one tick under the range low, target entry + 1.5 × risk. Risk must be 0.15–0.5 ATR14.
5. At most 2 ideas, most traded value first (`max_new_candidates_per_day`). Status `WATCHLIST`, or
   `NO TRADE` when none pass. Never `TRADE CANDIDATE`: gates 1–9 are not applied and nothing is validated.
6. Exit: stop, target, or 15:10 IST time exit. Size: 0.5% of capital at risk, never above available cash.

## Scoring (decided now)
Each idea is graded from that day's EOD bar (next morning's run): high < entry → not triggered; low ≤ stop →
−1R, even if the target was also touched or the stop was hit before entry (conservative); else high ≥ target
→ +1.5R; else exit at the close (stands in for 15:10). Costs per share in R: brokerage 0.03% capped at ₹20
per order, STT 0.025% on the sell, exchange 0.00297%, SEBI 0.0001%, stamp 0.003% on the buy, GST 18% on
brokerage and fees, slippage 0.05% per side. These rates are **unverified placeholders**; scored at 1× and 2×.

## Decision rule (decided now)
- **tracking** until both 30 triggered trades and 3 calendar months, or 12 months, whichever is first.
- Then **PASSED** only if: ≥ 30 triggered trades; mean R at 2× costs > 0; profit factor at 1× ≥ 1.2; a 95%
  bootstrap interval of mean R at 1× (resampled by day) above 0. Otherwise **REJECTED**.
- A PASS makes it a candidate for paper-trading review; it is not a probability claim or live approval.

## Known limitations
EOD-bar grading cannot see the order of intraday moves, so it is biased against the idea. Quotes are delayed;
the "opening range" is whatever the snapshot shows. Close ≠ 15:10 price. Single snapshot, no confirmation
candle. Unadjusted daily history (a corporate action on the previous day breaks the close check and the
symbol is skipped).

## Changelog
- v0.1 (2026-10-30): first version. Tests: `tests/test_intraday_scan.py`; full suite passed. No earlier
  results affected. No holdout used (forward data only).
- v0.1 reporting addendum (2026-11-02, no rule change): the scan can size ideas for a real cash account
  (`--capital`, `--risk-pct`, `--charges-inr`): qty from the stop distance capped by cash, and a charges
  check (profit at target >= 4x round-trip charges). Grading stays in R and is unaffected. The owner trades
  his own Rs 15,000 at 1% risk per trade; that is his decision, the project itself stays paper-only
  (settings.yaml 0.5% unchanged). Also: MCP calls retried in rounds after the first run lost sessions.
- v0.1 reporting addendum (2026-11-02, no rule change): `--list-all` also lists every other stock that passes
  the same rule, most traded first, for the owner to choose from (he takes 1-2). Only the first 2 (`ideas`)
  are recorded and graded; `also_passing` is not part of the experiment.
- **v0.2 (2026-11-02, EXP-0080) — rule change, decided before 2026-11-03's data.** What: target 1.5R -> **2R**;
  at most **one** recorded idea a day (was 2); the lead is the most traded passing stock, and when a capital is
  given, the most traded one whose charges check passes; other passing stocks are listed as WATCH only and
  are not graded; live labels WATCH / APPROACHING (LTP within 0.25% below the buy level) / ACTIVATED (high
  reached the buy level) / INVALIDATED (low reached the stop) / NO TRADE; output follows the owner's brief.
  Why: the owner replaced the project brief ("AI Trading Desk India": one opportunity a day, R:R at least
  1:2, max Rs 300 risk per trade). Old -> new: 0.1 -> 0.2. Tests: `tests/test_intraday_scan.py`, full suite
  passed. Impact: EXP-0079 (v0.1) ran one day (2026-11-02: TCS, LT); it is closed and its day is graded as
  v0.1, never pooled with v0.2. The decision rule above applies to EXP-0080 from 2026-11-03. No holdout used.
  Not adopted from the brief: F&O / options / index derivatives (no live F&O data here and the project bans
  derivatives); EMA, VWAP, RSI, India VIX, global cues (no intraday bars or VIX feed; the brief says use
  indicators only when they add evidence).
- ID fix (2026-11-03, no rule change): renumbered EXP-0052 -> **EXP-0079** (v0.1) and EXP-0053 -> **EXP-0080**
  (v0.2), because another branch registered EXP-0052/0053 first (multibagger base rates, 2026-11-01).
