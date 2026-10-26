# Monthly factor portfolios on Binance coins (research and paper only) — spec v0.1

Status: **REJECTED, all three** (2026-10-26; `reports/backtests/EXP-0044-0046-report.md`). Rules, splits and
pass/fail were committed before any run (b66ac0e). Nothing is forward-tracked.
Code: `src/trading_research/strategies/factors.py` (same scores as EXP-0039..0041), runner
`src/trading_research/backtesting/run_crypto_factors.py`. Registry: EXP-0044..0046.

**Why (model interpretation):** the Phase 18 factor portfolios (`factor-portfolios.md`) were the best results
so far on NSE stocks but failed the significance check. Their signals were picked from NSE dev data only. Running
**the same signals, unchanged, on a different market** is a cleaner out-of-sample test than any new NSE
variant, and it answers the owner's standing question (2026-10-25) of how crypto compares with Indian equities
for the best approach found so far. Low volatility and momentum are both reported in crypto research
(hypothesis; not verified here).

## Data (verified source, `docs/data-sources.md`)
Binance archive daily USDT pairs as loaded for Phase 14 (stablecoins, fiat, gold tokens, wrapped and staked
copies and leveraged tokens already excluded by `binance.py`). **Also excluded here: BKRW** (a KRW-pegged
stablecoin missing from that list; a low-volatility rule would otherwise pick it). Every UTC day is a session.
Point-in-time handling exactly as Phase 14: a pair is split at every missing day into separate instruments
(pieces under 200 bars dropped); a piece that ends before the data end counts as delisted and leaves the
universe for its last 7 bars (Binance announces delistings in advance). Bars are read only up to 2024-12-31.

## Rules (shared; Phase 18 rules with crypto sizes, windows unchanged in bars as in Phase 14)
* Rebalance at each month's last UTC day t (signal at the close), trade at the next day's open.
* Universe at t: the **50** instruments with the highest 63-day median quote volume, with that median at
  least **5,000,000 USDT** (the Phase 14 floor), at least 240 closes in the last 260 days and a bar on t.
* Hold the top **10** by score (fewer if fewer qualify), equal weight at entry; names that drop out are sold,
  names that enter are bought with min(cash / new names, equity / 10); no top-ups; idle cash earns nothing; a
  holding with no bar for 5 days is sold at its last close.

| | Strategy | Score at t (closes up to t) |
| --- | --- | --- |
| EXP-0044 | `lowvol` | minus the standard deviation of the last 252 daily returns |
| EXP-0045 | `momentum` | close 21 days ago / close 252 days ago − 1 |
| EXP-0046 | `mom_lowvol` | mean of the two percentile ranks |

Sizes: NSE held 30 of 200 (15%); 10 of 50 (20%) keeps a similar share for a market with far fewer liquid
names. Universe counts were checked before writing this (no returns looked at): coins passing the liquidity
and history rules numbered 0 on 2018-03-31, 10 on 2019-12-31, 26 on 2020-12-31, 144 on 2021-12-31, 44 on
2022-12-31, 121 on 2023-12-31 and 181 on 2024-12-31. Before mid-2020 a "top 10" would just be every coin, so
the splits start in July 2020.

## Costs and tax (unverified assumptions, as Phase 14)
Binance spot fee 0.10% + 18% GST (0.118%) plus 0.10% slippage per side; 2× stress doubles both. Tax: 31.2% of
every profitable sale, losses never set off (s.115BBH as read from secondary sources); positions are sold at
each split's end for tax. 1% TDS is a credit, not a cost (not modelled). Benchmark: **BTCUSDT bought at the
first open with the same costs and held**, taxed on its gain at the end. Start 10 lakh USDT units per split
(results are percentages; size is irrelevant).

## Splits
dev 2020-07-01..2023-12-31 · sub-periods 2020-07-01..2021-12-31 and 2022-01-01..2023-12-31 · validation
2024-01-01..2024-12-31 (seen by the Phase 14 rules, never by these) · **holdout 2025-01-01..2026-09-30
sealed** (the Phase 14 crypto holdout; one use; no runner path). Each split starts fresh from cash.

## Acceptance (decided now; Bonferroni over three, α = 0.05/3)
1. Dev at 2× costs: Sharpe (monthly returns, rf 0) above BTC's, and after-tax CAGR above BTC's.
2. Dev at 1× costs: 98.33% moving-block bootstrap interval (12-month blocks) of Sharpe(strategy) − Sharpe(BTC)
   above 0.
3. At 2× costs, Sharpe not below BTC's in each sub-period and in validation.
4. Validation at 2× costs: maximum drawdown at most 10 points worse than BTC's.
Otherwise **REJECTED**. Passing makes a strategy a holdout candidate only. Dev is 42 months, so rule 2 needs a
large edge; a REJECTED that fails only rule 2 is reported as a near miss, as in Phase 18.

## Policy note (risk manager)
A fully invested coin portfolio without stops does not fit the swing risk rules (0.5% planned risk per
position, 2% aggregate); crypto drawdowns of 70%+ are normal for BTC itself. Research and paper only; no
limit is changed here; real money would need the owner's written approval of a separate policy after review.

## Known limitations
One exchange; Binance prices in USDT (no INR conversion; rupee moves ignored); quote volume includes some wash
trading; delisted coins are present in the archive but a coin's history before its Binance USDT listing is not;
flat slippage; no staking income; 2020–2024 holds one full crypto cycle only.

## Review (gate 8, 2026-10-26)
**Risk manager:** long only, no leverage, no derivatives, paper only; policy note above. Accepted as research.
**Independent auditor:** the signals and windows are Phase 18's and were not chosen on crypto data; the only
crypto-specific choices (50/10, the 5M floor, the July 2020 start) are stated above with their reasons, made
from universe counts only. Validation 2024 was seen by other crypto rules. Objection: a 42-month dev with one
bull-bear cycle is short for a Sharpe test. Not a veto.

## Changelog
- **v0.1 (2026-10-26):** initial spec, before any run. Code change shared with Phase 18: `factors.Params` gains
  `min_median_value` (default 0, so EXP-0039..0043 are unchanged; their tests still pass).
- **v0.1 result (2026-10-26):** run once, no changes; all three REJECTED; none forward-tracked.
