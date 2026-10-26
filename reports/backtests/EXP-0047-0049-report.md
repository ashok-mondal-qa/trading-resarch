# Factor portfolios on unseen 2006–2011 NSE data, EXP-0047..0049: report (research only, 2026-10-26)

Spec `docs/strategy-specifications/factor-portfolios-pre2011.md` (v0.1 in 11448d9 before any data was loaded;
v0.1.1 in b530a11 before any run). Runner `python -m trading_research.backtesting.run_factors_pre2011`; outputs
`EXP-00xx-pre2011-<strategy>.json` and window equity curves here.

Data (verified source): NSE CM legacy bhavcopy from the official archive, 2005-07-01..2011-06-30, 1,480
sessions loaded, 82 weekdays with no file (holidays; never filled). 1,576 EQ symbols adjusted with NSE MCP
corporate actions (1,046 ok, 529 partial, 1 without data); 1,447 stocks used after excluding 24 ETFs/funds and
renamed duplicates. Benchmark NIFTYBEES (no events, no data errors). Its tracking of the NIFTY 50 index on
2012-02-21..2014-12-31: price CAGR 14.63% vs 14.62%, daily correlation 0.95 (thin closes add noise),
`niftybees-tracking-2012-2014.json`.

**Verdict under the pre-registered rules: low volatility (EXP-0047) and the mix (EXP-0049) REPLICATED;
momentum (EXP-0048) NOT REPLICATED.** This is the first time any rule in this project beat its benchmark on a
period it had never seen before the rules were frozen.

## Results (calculated; 2× costs unless stated; ₹10 lakh start; benchmark NIFTYBEES, same costs)
| | 2006-07..2011-06 CAGR | after tax | Sharpe | Max DD | 2006-07..2008 Sharpe | 2009..2011-06 Sharpe |
| --- | --- | --- | --- | --- | --- | --- |
| NIFTYBEES (NIFTY 50 ETF) held | 12.5% | 11.2% | 0.55 | −60% | 0.07 | 1.22 |
| EXP-0047 low volatility 30 | 17.3% | 14.9% | 0.73 | −52% | 0.08 | 1.42 |
| EXP-0048 momentum 30 | 1.9% | 0.5% | 0.26 | −78% | −0.05 | 0.94 |
| EXP-0049 momentum + low vol 30 | 18.1% | 15.5% | 0.66 | −65% | 0.12 | 1.34 |

Reported, not a gate: 98.33% interval of the Sharpe difference at 1×: low vol −0.11..+0.45, mix −0.27..+0.53,
momentum −0.64..+0.18. Five years cannot prove the gap on their own.

Calendar years at 1× costs (2006 is July–December only):
| | 2006 H2 | 2007 | 2008 | 2009 | 2010 | 2011 H1 |
| --- | --- | --- | --- | --- | --- | --- |
| NIFTYBEES | +27% | +51% | −52% | +71% | +18% | −8% |
| Low volatility | +27% | +38% | −46% | +74% | +15% | +14% |
| Momentum | +37% | +105% | −75% | +75% | −2% | −5% |
| Mix | +27% | +85% | −59% | +71% | +19% | +18% |

## What this says (model interpretation)
* **Low volatility and the mix held up on new data.** Both beat the NIFTY ETF over the five years after tax and
  in both halves on Sharpe, as they did in 2013–2025. Together with the Phase 18 results (corrected), the
  direction has now held in three separate periods: 2006–2011, 2013–2022 and 2023–2025.
* **They are not crash-proof.** In 2008 low volatility lost 46% and the mix 59%, against 52% for NIFTY. Anyone
  holding these must expect to see half the money gone at some point. Our stop-based 0.5% risk rules could not
  allow that, which is why real use needs a separate written investing policy.
* **Momentum alone failed badly.** It doubled in 2007 and then lost 75% in 2008. This matches Phase 19 (crypto
  momentum −92% in 2022): momentum crashes when a boom ends.
* **The statistical test still cannot be passed with this much history.** Each period alone is too short.
  The evidence is consistency across periods, not a proof; forward paper tracking (EXP-0042/0043) remains the
  deciding test.

## Limitations
ETF benchmark with thin early trading and an expense ratio (makes the benchmark slightly worse); price returns
without dividends on both sides; today's costs and taxes applied to 2006–2011; ETF exclusion by name; renames
confirmed without ISINs; 529 symbols have data errors, after which their history restarts (a held stock takes
the full move on an error day, real crash or missing split, which biases against the portfolios).
