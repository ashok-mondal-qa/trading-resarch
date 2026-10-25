# 9/15 EMA scalp ("The Trade Room" style), EXP-0037/0038: report (research only, 2026-10-25)

Spec `docs/strategy-specifications/crypto-intraday.md` v0.2 addendum (committed in a252324 before any run).
Rules are the common published form of the 9/15 EMA scalp, not The Trade Room's own rule book (not found
publicly). Data: Binance spot 5m BTCUSDT + ETHUSDT 2018–2024 (as EXP-0033..0036). Holdout not downloaded.

**Result: both REJECTED.**

| Dev 2018–2022 (calculated) | Trades | Trades/month | Win rate | Mean R 1× (97.5% CI) | Mean return per trade 1× | After tax | Mean R 2× |
| --- | --- | --- | --- | --- | --- | --- | --- |
| EXP-0037 as described (no minimum stop) | 17,936 | ~300 | 20% | −1.98 (−2.14..−1.83) | −0.30% | −2.04R | −3.04 |
| EXP-0038 with 0.6% minimum stop | 2,099 | ~35 | 33% | −0.33 (−0.40..−0.26) | −0.29% | −0.49R | −0.63 |

Validation 2023–2024 is worse for both (−2.84R and −0.29R at 1×). Every sub-period is negative at 1× and 2×.
Illustrative account risking 0.5% per trade: EXP-0037 is wiped out (−99.5% a year); EXP-0038 −44% a year.

## Model interpretation
* **Before costs the signal is break-even.** The mean loss per trade (−0.30% at 1×, −0.60% at 2×) is almost
  exactly the round-trip cost (≈ 0.30% per 1×), so the crossover itself predicts nothing; costs are the loss.
* **The stop is smaller than the cost.** The median stop (signal candle low) is 0.20% of price, below the
  0.30% round-trip cost, so a "1:2" trade is really about 1:0.3 after costs.
* On NIFTY options the same scalp pays ₹20 per order plus STT, exchange charges and a wider bid-ask on each
  trade, so costs per trade are likely higher in %, not lower (hypothesis; Indian intraday data not tested).

## Limitations
Proxy market (BTC/ETH 5m, not NIFTY/BANKNIFTY options 1m); the rule is the published form, and a discretionary
trader may filter signals in ways not written down. Same 5m-bar and cost caveats as EXP-0033..0036.
