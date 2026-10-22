---
name: smc-concepts
description: Operational, testable definitions of Smart Money Concepts - liquidity pools, sweeps, displacement, fair value gaps, order blocks, mitigation, inducement - and how to test whether they add value over a baseline. Use for any SMC-based hypothesis.
---

# Smart Money Concepts (treated as hypotheses)

## Stance
SMC labels are hypotheses about order flow inferred from OHLC data. A pattern appearing on a chart is
not evidence that it predicts anything. Each concept stays only if it improves out-of-sample results
over the same strategy without it.

## Operational definitions (v0.1, daily bars)
- **Buy-side / sell-side liquidity:** price levels of confirmed swing highs / lows (see
  `price-action-structure`), optionally equal highs/lows within 0.1 x ATR.
- **Liquidity sweep (sell-side):** bar low trades below a sell-side level but the bar closes back
  above it.
- **Displacement (bullish):** a bar with body >= 1.5 x ATR(14) and close in the top 25% of its range.
- **Fair value gap (bullish):** for bars i-1, i, i+1: low(i+1) > high(i-1). Gap = [high(i-1), low(i+1)].
  Known only at the close of i+1.
- **Order block (bullish):** the last down-close bar before a bullish displacement that produces a BOS.
  Zone = that bar's low to high (or open to low; the spec must pick one).
- **Mitigation:** first later bar whose range enters the zone. A zone is used once.
- **Inducement:** a minor swing low formed after the BOS and before price reaches the zone. Required
  or not is a spec parameter, not a judgement call.
- **Higher-timeframe context:** weekly structure computed from completed weeks only.

## Workflow
1. Code each definition with fixtures and no-look-ahead tests.
2. Build the SMC strategy as its own versioned spec.
3. Compare against (a) the same entry without the SMC filter and (b) a simple trend baseline, on the
   same data, costs and splits.
4. Report the incremental effect with uncertainty. If it is within noise, reject the concept.

## Verification
- No concept depends on a human drawing a zone.
- Any SMC result report includes the ablation (with vs without).
