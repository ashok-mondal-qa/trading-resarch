# One-time 2026 holdout, EXP-0050/0051: report (research only, 2026-10-26)

Rule fixed in `docs/strategy-specifications/factor-portfolios.md` (holdout addendum, commit cd0487f) before the
holdout was read; one run with `python -m trading_research.backtesting.run_factors --holdout ...`; owner approval
recorded in the JSON files. Data: NSE EQ adjusted bars and NIFTY 50 index files 2026-01-01..2026-10-22 (verified
fact: NSE archive; NIFTY opened 2026 at 26,173 on 2026-01-01 and closed at 22,688 on 2026-10-22).

**Verdict under the pre-registered rule: the mix (EXP-0051) PASSED HOLDOUT; low volatility (EXP-0050) FAILED
HOLDOUT** (on one check, by a small margin).

## Results (calculated; ₹10 lakh start; NIFTY = price index with the same costs)
| | Net return 1× | Net return 2× | Daily Sharpe 1× | Daily Sharpe 2× | Max DD 1× | Max DD 2× |
| --- | --- | --- | --- | --- | --- | --- |
| NIFTY 50 held | −13.5% | −13.7% | −1.14 | −1.14 | −15.6% | −15.6% |
| EXP-0050 low volatility 30 | −11.7% | −12.3% | −1.12 | **−1.16** | −13.4% | −13.8% |
| EXP-0051 momentum + low vol 30 | −12.0% | −13.2% | −0.93 | −1.02 | −15.6% | −15.7% |

No tax is due on these windows (all lots lost money). Low volatility lost less than NIFTY and fell less, but at
2× costs its daily Sharpe (−1.156) is just below NIFTY's (−1.143), so it fails the "Sharpe not below NIFTY" check.

## What this says (model interpretation)
* **2026 so far is a falling market** (NIFTY −13.7% at 2× costs). Both portfolios lost money too, slightly less
  than NIFTY. Neither protects capital in a broad fall; at best they lose a little less.
* **Sharpe misleads when returns are negative:** a calmer portfolio with a smaller loss can score a more negative
  Sharpe. That is why low volatility failed. The rule was fixed in advance, so the result stands as FAILED; it
  is noted here only so the number is read correctly.
* **Overall record for the mix:** ahead of NIFTY in 2006–2011, 2013–2022, 2023–2025 and the first ten months of
  2026, all by small to moderate margins, with crashes of similar depth. Low volatility: ahead in the first three,
  marginal in 2026. None of this is proof; the 24-month forward test (EXP-0042/0043) stays the deciding test.

## Consequences
The NSE holdout is now used up. EXP-0039/0041 stay REJECTED under their own rules; forward tracking continues
unchanged. Any later NSE idea needs forward data.
