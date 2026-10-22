---
name: portfolio-risk
description: Position sizing, stop distance, aggregate open risk, correlation, gap risk, drawdown and consecutive-loss analysis for the virtual portfolio. Use at gate 6, for the risk-manager review, and in backtest reporting.
---

# Portfolio and risk management

## Rules (enforced in code, see docs/risk-policy.md)
0.5% planned risk per position; 2% aggregate; no leverage, derivatives, averaging down or stop
widening; liquidity floor from config.

## Workflow
1. Size with `trading_research.risk.sizing.size_long_position` (it includes slippage and charges).
   A `SizingRejected` means the candidate is REJECTED, never resized by hand.
2. Check correlation: if a new candidate's 60-day return correlation with an open position is > 0.7,
   or it is in the same sector, count their risk together against a 1% sector sub-limit (spec v0.1).
3. Gap risk: report the 95th percentile overnight adverse gap for the stock (from history) and the
   loss if it occurs at the planned size.
4. Drawdown and streaks: for any strategy, report max drawdown, the longest losing streak, and the
   equity impact of 10 consecutive full-risk losses (about 4.9% at 0.5%).
5. Risk of ruin: estimate by bootstrap of the out-of-sample trade list, not by formula alone.

## Veto
The risk-manager may veto any candidate whose stop is not at a structural level, whose liquidity is
too thin for the size, or whose gap risk exceeds 3x planned risk.

## Verification
- `pytest tests/test_risk_and_costs.py` passes.
- Every report shows aggregate open planned risk vs the 2% cap.
