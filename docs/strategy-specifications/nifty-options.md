# NIFTY monthly options: four popular approaches (research only) — spec v0.1

Status: **pre-registered, not run** (written and committed before any options backtest).
Code: `src/trading_research/strategies/options.py`, runner `src/trading_research/backtesting/run_options.py`,
data `src/trading_research/data/fo_bhavcopy.py`. Registry: EXP-0029..0032.

**Scope (owner, 2026-10-25):** Ashok asked to explore options after the swing results. This is research on
historical data only. CLAUDE.md bans derivatives for trading: nothing here can become a paper or live
candidate without a separate written change to the risk policy by the owner.

## Context (verified fact, SEBI press release 23 Sep 2024, "Updated SEBI study reveals 93% of individual
traders incurred losses in equity F&O between FY22 and FY24")
Over 1 crore individual F&O traders: 93% lost money, about ₹2 lakh each on average including costs; only
1% made more than ₹1 lakh. Proprietary traders and FPIs profited, mostly through algorithmic trading.

## Data
NSE F&O bhavcopy, every session 2012-01-02..2026-10-23 (legacy files to 2024-07-05, UDiFF after), NIFTY and
BANKNIFTY index options and futures, raw files with SHA-256 and manifests. NIFTY 50 index values from NSE's
daily index files (final settlement of NIFTY options = the index close on expiry day). Only NIFTY monthly
options are used here (weekly NIFTY options exist only from 2019; BANKNIFTY weeklies were withdrawn in 2024).
Lot sizes are not needed (results are per unit, in index points and R); the brokerage per order is charged
per lot using the lot size from UDiFF, or for legacy files inferred from the near-month future's turnover.

## Monthly cycle (shared)
Monthly expiry = the last expiry date listed in each calendar month. **Signal day t** = the first session
after a monthly expiry; the trade uses the next monthly expiry. At t's close: spot S = NIFTY close; ATM
strike = listed strike nearest S; straddle D = close(ATM call) + close(ATM put), both traded at t, else no
trade that month. **Entry** at the open of t+1 for every leg; every leg must have traded at t+1, else no
trade. Expiry: legs settle at intrinsic value against the NIFTY close on the expiry day.

| | Strategy | Legs (strikes chosen at t) | Management | R (risk unit per trade) |
| --- | --- | --- | --- | --- |
| EXP-0029 | `iron_condor` | sell call ≥ S + D and put ≤ S − D; buy call ≥ S + 2D and put ≤ S − 2D | hold to expiry | wing width − net credit |
| EXP-0030 | `short_strangle` | sell call ≥ S + D and put ≤ S − D | stop: at a close where buy-back cost ≥ 3 × credit (loss ≥ 2 × credit), exit at the next open | 2 × credit (losses can exceed it) |
| EXP-0031 | `covered_call` | hold NIFTY (price index, as an index fund would) and sell the call ≥ S × 1.02 | hold to expiry | — (judged against NIFTY buy and hold) |
| EXP-0032 | `long_call` | NIFTY close > previous 20-session high and NIFTY regime `up`: buy the ATM call of the first monthly expiry ≥ 15 sessions away | exit at the next open after a NIFTY close < previous 10-session low, or when ≤ 5 sessions remain; one position at a time | premium paid + costs |

`long_call` is a daily signal, not a monthly cycle: signal at a close, entry at the next open (traded leg
required), at most one open position.

## Costs (per leg, per side; unverified, current rates applied throughout)
Brokerage ₹20 per order per lot; STT 0.1% of premium on sells, 0.125% of intrinsic value on options
exercised at expiry; NSE transaction charge 0.03503% of premium; SEBI ₹10 per crore; stamp duty 0.003% of
premium on buys; GST 18% on brokerage + transaction + SEBI. **Slippage** max(1 index point, 1.5% of the
price) per leg per side (bid-ask on monthly OTM options). 2× stress doubles all of it.

## Splits
dev 2012-02-21..2022-12-31 (decides) · sub-periods 2012–2016 and 2017–2022 · validation 2023-01-01..
2024-12-31 · **holdout 2025-01-01..2026-10-23 sealed** (one-time use for a strategy that passes; no runner
path). A trade belongs to the split of its entry date and must expire inside the split.

## Acceptance / rejection (decided now)
For `iron_condor`, `short_strangle`, `long_call`, all must hold:
1. Dev: ≥ 60 trades; at 2× costs expectancy > 0 and profit factor ≥ 1.1.
2. Dev at 1× costs: 95% bootstrap interval of mean R, Bonferroni over the four (98.75%), above 0
   (trades resampled whole; monthly trades do not overlap).
3. 2× costs expectancy > 0 in 2012–2016, in 2017–2022 and in validation 2023–2024.
For `covered_call`: monthly returns' Sharpe (rf 0) above NIFTY buy and hold's in dev at 1× and 2× costs, and
not below it at 2× costs in either sub-period or validation; maximum drawdown not worse than buy and
hold's in dev at 1× costs. Monthly returns run from one monthly expiry close to the next (NIFTY held
throughout; months without a tradable call are NIFTY alone).
Otherwise **REJECTED**. Passing makes a strategy a holdout candidate only.

## Reported but not decided on
Worst trade (R and % of the index), losing months, the share of profit from the best 5 trades, an equity
curve risking 5% of equity per trade (R strategies; illustrative, not the project's 0.5% policy, under which
one NIFTY lot does not fit a ₹10 lakh account), and post-tax figures (F&O profits are business income: 31.2%
on each financial year's net profit, losses offset and carried forward; assumption, unverified).

## Known limitations
End-of-day data only: intraday stops, the popular 9:20 straddle and weekly expiry-day trades cannot be
tested. Opening prices of OTM options can be stale or wide; slippage is a flat estimate. Margin, interest
on collateral, dividends (price index) and lot-size changes are not modelled. Early years (2012–2014) have
thinner far-OTM liquidity, so some months are skipped for untraded legs.

## Review (gate 8, 2026-10-25)
**Risk manager:** derivatives remain forbidden for paper/live; this spec is research only. Undefined-risk
short strangles can lose many multiples of credit in a gap (e.g. 2020-03); report it. Accepted as research.
**Independent auditor:** strikes are chosen from t's closes and filled at t+1's open; expiry values come from
the index file; no holdout path. Objection: the straddle-width strike rule is one of many common choices;
no alternatives will be tried on this data. Not a veto.

## Changelog
- **v0.1 (2026-10-25):** initial spec, before any options run.
