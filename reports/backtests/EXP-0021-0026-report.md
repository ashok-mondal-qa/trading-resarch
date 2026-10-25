# EXP-0021..0026: the NSE rule sets on Binance crypto — backtest report

**Verdict: all six REJECTED** by the rules in `docs/strategy-specifications/crypto-comparison.md`, committed
(8374c91, comparison code 657fed3) before any crypto run. The sealed crypto holdout (2025-01..2026-09) was
**not** run. No strategy is eligible for paper trading.

Generated 2026-10-25. Every number is a **calculated value** from Binance's official archive
(data.binance.vision, monthly 1d klines, SHA-256 verified, retrieved 2026-10-25, manifests in
`data/manifests/binance_spot_1d/`). 674 USDT pairs loaded (656 complete, 18 with gaps or dropped rows,
1 empty, 2 failed on non-ASCII names; both list after 2024, so outside every split). Split into pieces at
missing days: 436 instruments of ≥ 200 bars to 2023, 95 of them delisted pieces. Cost rates **unverified**.
Nothing here is a probability claim. Reproduce: `python -m trading_research.backtesting.run_crypto --split dev`
(and dev_a, dev_b, validation), then `--verdict`.

## Pass/fail (rules fixed before the run)
| Rule | minervini | supertrend | ma44 | turtle55 | golden_cross | momentum_weekly |
| --- | --- | --- | --- | --- | --- | --- |
| Dev portfolio ≥ 30; 2×: expectancy > 0, PF ≥ 1.1 | pass | **fail** (2 trades) | **fail** | pass | pass | **fail** (3 trades) |
| Dev standalone ≥ 300 trades | **fail** (247) | **fail** (2) | **fail** (230) | **fail** (85) | pass (319) | **fail** (3) |
| Dev standalone 1×: 99.2% interval above 0 | **fail** (−0.03..+4.42) | **fail** | **fail** | **fail** | **fail** | **fail** |
| Dev standalone 2× > 0 | pass | **fail** | **fail** | pass | **fail** | pass |
| dev_a / dev_b / validation 2× > 0 (closed and incl. open) | **fail** validation | **fail** | **fail** | **fail** dev_b | **fail** all three | **fail** |
| **Outcome** | **REJECTED** | **REJECTED** | **REJECTED** | **REJECTED** | **REJECTED** | **REJECTED** |

## Results, dev 2018-04-01..2023-12-31 (1× costs)
| Strategy | Portfolio trades | Expectancy (PF) | CAGR | Max DD | Sharpe | Standalone trades | Standalone expectancy closed / incl. open (99.2% CI) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| minervini (0021) | 120 | +2.27R (2.62) | +24% | −23% | 1.12 | 247 | +1.91R / +2.15R (−0.03..+4.42) |
| supertrend (0022) | 2 | −0.28R | 0% | −1% | | 2 | |
| ma44 (0023) | 170 | −0.01R (0.98) | 0% | −13% | −0.03 | 230 | +0.03R (−0.24..+0.29) |
| turtle55 (0024) | 43 | +1.70R (2.78) | +12% | −24% | 0.94 | 85 | +0.55R / +2.67R (−0.73..+2.94) |
| golden_cross (0025) | 94 | +1.06R (1.65) | +10% | −49% | 0.50 | 319 | −0.09R / +0.48R (−0.88..+2.27) |
| momentum_weekly (0026) | 3 | +0.54R | 0% | −2% | | 3 | |
| BTCUSDT buy and hold | | | +37%* | −77% | 0.81 | | |

\* BTC rose 5.2× (+521%) over the dev window.

Standalone 1× by entry year (mean R, trades; incl. open). There were no signals in 2018 and 2022: the
BTC regime gate was not `up`.

| Year | minervini | ma44 | turtle55 | golden_cross |
| --- | --- | --- | --- | --- |
| 2019 | −0.05 (8) | −0.06 (5) | +2.11 (6) | −0.04 (8) |
| 2020 | +7.50 (29) | +0.03 (34) | +2.31 (30) | +3.68 (41) |
| 2021 | +2.23 (136) | −0.10 (97) | −0.68 (4) | −0.45 (137) |
| 2023 | +0.53 (91) | +0.17 (94) | +3.04 (75) | +0.47 (179) |

Validation 2024, standalone 2× closed / incl. open: minervini −0.23R / −0.01R; turtle55 +0.65R / +1.39R;
golden_cross −0.98R / −0.65R; ma44 −0.15R.

## What the numbers say (model interpretation)
- **The 10% stop cap shuts out most crypto setups.** Daily crypto moves are 3–5× larger than NSE stocks,
  so Supertrend (stop at the line), weekly momentum (2.5 ATR) and many Turtle signals need stops wider
  than 10% and are refused. Supertrend and momentum produced 2–3 trades in six years. This is the risk
  policy working, not a bug: these rules cannot be traded on crypto within it.
- **Minervini and Turtle made money, but from a handful of trades in one bull run.** Win rates are
  23–27% and the median trade is a full −1R loss. In the Minervini portfolio the top 5 of 124 trades made
  81% of the profit; in Turtle and golden cross the top 5 made more than all the profit (the rest lost).
  Most of it came from 2020–2021 (THETA +140R, ETC +102R, ETH, BTC, SOL). The intervals include zero and
  the minimum trade counts are not met, so the evidence is too thin to call an edge.
- **Golden cross** gave back a 49% drawdown: stops are fixed at entry and never raised, so big open gains
  in 2021 were lost in the 2022 fall before the cross reversed. 2024 lost almost every closed trade.
- **The 44-MA setup** is break-even before costs and negative after, as on NSE.

## Bias checklist
- **Look-ahead:** same feature code as the NSE runs (perturb/truncation tests); new code tested
  (`tests/test_binance.py`, `tests/test_run_crypto.py`); bars only to each split end. The delisting rule
  uses Binance's advance announcements (no signals in a piece's last 7 bars, exit at its last open), which
  a trader could know; a coin that collapsed before delisting still hits its stop first.
- **Survivorship:** delisted pairs in the archive are included (95 pieces); pairs delisted before the
  archive began (2017) are not. Reused tickers never join (LUNAUSDT).
- **Data snooping:** six rules chosen on NSE results, never on crypto; Bonferroni over six.
- **Concentration:** results hinge on a few trades (above); one bull market (2020–21) dominates.
- **Costs:** Binance base fee + GST + 10 bps; INR exchanges cost more. 2× costs barely change the
  winners (large R), but matter for ma44.

## Holdout
Not run. Nothing passed. It stays sealed.
