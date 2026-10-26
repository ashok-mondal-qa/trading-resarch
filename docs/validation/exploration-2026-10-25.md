# Data exploration, 2026-10-25 (dev data only: 2013–2022)

Purpose: find where returns come from before writing any new rule. Everything here is **calculated on
2013-01-01..2022-12-31** (NIFTY 50 index files; NSE EQ stocks built to 2022-12-31). Later data was not
read. Each line is a calculated indicator, not a tested strategy. This counts as a search: anything chosen
from it must be proven on later data.

## NIFTY 50: where the index's return happened (2,456 sessions)
| | Mean per day | Annualised | t-stat |
| --- | --- | --- | --- |
| Close to close | +5.2 bp | +12.2% | 2.35 |
| Overnight (previous close → open) | +12.4 bp | +36.0% | 9.54 |
| Daytime (open → close) | −7.3 bp | −17.5% | −4.03 |

The whole gain came overnight; holding NIFTY only during market hours lost money. That fits the failed
intraday-buying results. The overnight part can't be captured cheaply in cash stocks (0.1% STT per side on
delivery is more than the 12 bp edge) and futures are not allowed. NIFTY ETF opening prints are too noisy to
measure it (NIFTYBEES "overnight" of +205 bp/day in 2021 reflects thin opening trades, not real returns).

## NIFTY calendar and state
* Day of week: Tuesday highest (+11 bp), Monday lowest (−4 bp); weak t-stats.
* Turn of month: days −4..+2 averaged ~13 bp vs ~3 bp otherwise. The textbook window (last day to day +3)
  with 6% cash otherwise gave 9.0% a year after a 0.1% round trip vs 12.2% for holding, with a −12% vs −38%
  drawdown. The best-looking window (−4..+2) was picked by eye, so it is not used. Not pursued.
* Above vs below the 200-day average: forward returns were higher *below* it (mean reversion at the index
  level), so a trend filter on NIFTY would have hurt.
* After a −2% day: next-20-day return +2.2% vs +1.0% on average (73 cases, overlapping). Weak evidence.

## Stocks: quintiles within the 200 most traded (monthly, equal weight, before costs)
| Signal (top quintile) | CAGR | Volatility | Sharpe | Max drawdown | Monthly turnover |
| --- | --- | --- | --- | --- | --- |
| All 200 equal weight | 12.7% | 21.6% | 0.66 | −43% | |
| Low volatility | 15.2% | 13.9% | 1.09 | −19% | 9% |
| 12-1 momentum | 22.1% | 23.9% | 0.97 | −33% | 25% |
| Near 52-week high | 17.2% | 17.9% | 0.98 | −29% | 49% |
| 1-month reversal (losers) | 11.7% | 27.6% | 0.55 | −49% | 79% |

Low volatility trailed in strong bull years (2014, 2017, 2021) and won in falls; momentum beat the
equal-weight group in 8 of 10 years. These two go forward (spec `factor-portfolios.md`); 52-week high is
similar to momentum with twice the turnover; reversal is weak.
