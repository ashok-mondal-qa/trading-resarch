---
name: price-action-structure
description: Objective, code-defined price-action concepts - swing points, trend structure, BOS, CHoCH, support/resistance zones, breakouts, pullbacks and failed breakouts. Use when evaluating or coding structure-based rules.
---

# Price action and market structure

## Responsibility
Provide one testable definition per concept. A concept that cannot be coded deterministically is not
used as a gate.

## Operational definitions (v0.1; parameters live in the strategy spec)
- **Swing high (k):** bar i whose high is strictly greater than the highs of the k bars on each side.
  It is only *known* at bar i+k. Code must timestamp it at i+k (confirmation lag) to avoid look-ahead.
- **Swing low (k):** mirror of the above.
- **Uptrend structure:** last two confirmed swing highs and lows are each higher than the previous.
- **Break of structure (BOS), bullish:** a daily close above the most recent confirmed swing high
  while structure is already up (continuation).
- **Change of character (CHoCH), bullish:** in down-structure, the first daily close above the most
  recent confirmed lower swing high.
- **Support/resistance zone:** cluster of >= 2 confirmed swing points within 0.5 x ATR(14), zone
  width = that range.
- **Breakout:** close above the zone top by >= 0.25 x ATR with volume >= 1.5 x 20-day median.
- **Failed breakout:** a breakout followed within 3 sessions by a close back inside the zone.
- **Pullback:** in up-structure, a retracement to the 20-EMA or to the broken level without a close
  below the last higher low.

## Workflow
1. Implement each definition in `src/trading_research/indicators/structure.py`.
2. Write fixture tests with hand-labelled bars, plus a no-look-ahead test (changing bars after t
   must not change outputs at t).
3. When reviewing a chart claim, restate it in these definitions; if it does not fit, it is an
   interpretation, not evidence.

## Verification
- Same input bars always give the same labels.
- Confirmation lag is visible in the output (a `confirmed_at` column).
