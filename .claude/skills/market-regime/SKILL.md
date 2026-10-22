---
name: market-regime
description: Classify the market regime (trend up/down, range, high/low volatility, event-driven) from benchmark data and decide whether a strategy is allowed to trade. Use at gate 2 and when slicing backtest results by regime.
---

# Market regime detection

## Definitions (v0.1, computed on the benchmark, e.g. NIFTY 50 or NIFTY 500, daily closes)
- **Trend:** close vs 200-day SMA and the 50-day SMA slope over 20 days.
  Up = close > SMA200 and slope > 0; Down = close < SMA200 and slope < 0; otherwise Range.
- **Volatility:** 20-day realised volatility percentile over the trailing 3 years.
  High >= 80th, Low <= 20th, else Normal.
- **Breadth (optional input):** % of universe above their 50-day SMA, from the same EOD data.
- **Event-driven:** a calendar flag for scheduled events (Union Budget, RBI policy, general election
  results) within +/- 2 sessions. Dates must come from official sources.

## Workflow
1. Compute the regime label for each date using data up to that date only.
2. Each strategy spec lists its allowed regimes. Gate 2 fails if today's regime is not allowed.
3. In backtests, report every metric per regime and flag regimes with < 30 trades.

## Verification
- Regime labels are reproducible from the data date and stored with the report.
- No regime threshold is tuned on the holdout.
