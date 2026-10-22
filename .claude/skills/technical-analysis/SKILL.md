---
name: technical-analysis
description: Deterministic indicators - moving averages, ATR, relative strength vs benchmark, volume measures, volatility, momentum, multi-timeframe - with no-look-ahead tests. Use when computing or reviewing any indicator.
---

# Technical analysis

## Responsibility
A small, tested indicator library in `src/trading_research/indicators/`. Indicators are inputs, not
confirmations: an indicator used in a rule must be justified by an experiment.

## Library (v0.1 scope)
- SMA, EMA; slope of MA over n bars.
- ATR (Wilder), ATR as % of close.
- Relative strength: stock return / benchmark return over n bars, and its percentile rank in the universe.
- Volume: 20-day median volume and traded value; volume ratio to median.
- Volatility: n-day realised volatility; volatility percentile.
- Momentum: n-day rate of change; distance from 52-week high.
- Multi-timeframe: weekly bars resampled from completed daily sessions (W-FRI, IST), never a partial week.
- VWAP is intraday; with daily data it is not available. Do not approximate it from OHLC and call it VWAP.

## Workflow
1. Implement as pure functions on a DataFrame indexed by date (one symbol).
2. Warm-up bars produce NaN, never a backfilled value.
3. Tests: hand-computed values on a small fixture; no-look-ahead (perturb future bars); NaN handling.

## Verification
- `pytest tests/test_indicators.py` passes.
- Every indicator documents its warm-up length.
