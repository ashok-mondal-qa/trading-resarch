# Intraday ideas from the research source library (research only) — spec v0.1

Status: **pre-registered 2026-11-03, before any run.** Registry: EXP-0068..0070. Sources: see
`docs/research/source-register.md` (rows SR-0068..SR-0070). Research and paper only; nothing here places orders.

**Why (owner, 2026-11-03):** Ashok set a standing "research source library" rule: research strategies from tiered
sources (official data and peer-reviewed work first), keep a source register per strategy, reconstruct exact rules,
backtest with costs, out-of-sample and walk-forward, and never let lower-tier claims override higher-tier evidence.
Every rule tested so far (EXP-0006..0066) was rejected; the three intraday families of his brief (EXP-0061..0066)
lost after charges in every split. This spec picks the two intraday ideas from the library with the strongest
published evidence that can be reconstructed and tested on the data we have.

## Source check (verified fact / UNVERIFIED, accessed 2026-11-03)
The cloud network blocks the publisher pages (doi.org, ssrn, sebi.gov.in, zerodha.com, groww.in, tradingview.com
all refused by the proxy on 2026-11-03), so **no full text was read**. Only web-search result pages were reachable.
What those pages state is recorded as "search-verified"; anything else is marked UNVERIFIED.

| ID | Idea | Source | Tier | What is search-verified | What is UNVERIFIED |
| --- | --- | --- | --- | --- | --- |
| EXP-0068/0069 | Market intraday momentum | Gao, Han, Li, Zhou, "Market intraday momentum", *Journal of Financial Economics* 129 (2018) 394–414 | 1 | first half-hour market return (measured from the previous close) predicts the last half-hour return, S&P 500 ETF 1993–2013; stronger with higher volatility and volume; out-of-sample R² ~1.2% | exact trading rule and costs in the paper; nobody has shown it for NIFTY (search found no NSE study) |
| EXP-0070 | 5-minute ORB on "Stocks in Play" | Zarattini & Aziz, "Can Day Trading Really Be Profitable?" (SSRN 4416622, 2023); Zarattini, Barbon & Aziz, "A Profitable Day Trading Strategy For The U.S. Equity Market" (2024) | 2 (working papers, not peer-reviewed; authors sell trading education) | 5-min ORB on US stocks with unusually high volume; screen: open > $5, 14-day avg volume ≥ 1M, ATR(14) > $0.50, opening-5-min relative volume ≥ 100%, top 20 by relative volume; claimed net alpha 33–36%/yr | the exact entry, stop and exit rules (search pages did not show them); an independent replication on index CFDs (MQL5 blog) reports "gross reproduced, net zero" (Tier 4, unverified) |

Not tested here (and why): Holmberg, Lönnbark & Lundström (2013, *Finance Research Letters* 10(1) 27–33), the ORB
paper in the library: the abstract (search-verified) says the range threshold comes from a model of normally
distributed returns, but the exact threshold rule was not readable, and the ORB family on NSE data already failed
(EXP-0033, 0056, 0061, 0064). Barardehi, Bogousslavsky & Muravyev, "What Drives Momentum and Reversal? Evidence from
Day and Night Signals" (working paper; the RFS 2026 version and DOI in the owner's list could not be confirmed by
search): it sorts US stocks monthly on past intraday vs overnight returns, a multi-week portfolio signal, not an
intraday trade; registered as a future swing/portfolio idea. SEBI studies are context (who loses), not strategies.

## Data (all reused from EXP-0061..0066, same loaders and day checks)
NIFTY 50 1-min (technovusin, MIT) and BANK NIFTY 1-min (sandeepkapri, MIT), 2017-04..2026-10 / 2026-04; 126 NSE
stocks 1-min with volume (ShabbirHasan1/NSE-Data, GPL-3.0) 2017–2020, scaled to the official NSE bhavcopy. Every day
must pass the gate-1 checks of `docs/strategy-specifications/intraday-three-families.md`; failing days are dropped.
Previous official close (NSE `ind_close_all` for indices; bhavcopy for stocks) is used where a rule needs it.

**Disclosure (data reuse):** every split below was already read by EXP-0061..0066 (other rules) and NIFTY expiry
days by EXP-0054..0060. No rule here was tuned on those runs and the rules below are fixed from the sources before
any run, but none of these splits is a sealed holdout. A pass can therefore only lead to forward paper tracking on new
data, never straight to the live candidate pool.

## Splits (same as EXP-0061..0066)
| Universe | Dev (halves) | Validation | Holdout |
| --- | --- | --- | --- |
| Stocks | 2017-01..2018-12 (2017, 2018) | 2019 | 2020 |
| Indices | 2017-04..2021-12 (2017-04..2019-06, 2019-07..2021-12) | 2022–2023 | 2024-01..2026-10 |

**Walk-forward:** the rules have no fitted parameters (EXP-0069's threshold is a trailing percentile computed only
from earlier days), so walk-forward = each calendar year is evaluated with rules fixed before it. Reported per year.

## Rules
### EXP-0068 `nifty_intraday_momentum` (Gao et al. 2018, adapted to NSE hours)
* Signal: r1 = NIFTY price at 09:45 (close of the 09:44 1-min bar) / previous official NIFTY close − 1.
  (First half-hour including the overnight move, as in the paper.)
* r1 > 0 → long, r1 < 0 → short, r1 = 0 → no trade.
* Trade window: the last half-hour that can be held in an intraday (MIS) position before the 15:15 square-off used in
  every earlier spec: entry at the 14:45 1-min open, exit at the 15:15 1-min open. (The paper's window is the
  exchange's last half-hour, 15:00–15:30 here; that window cannot be held intraday at most brokers, so it is reported
  as a gross diagnostic only. Broker square-off time is UNVERIFIED.)
* Protective stop (added for the brief, not in the paper): 1.0% from entry, checked on 1-min bars; stop before exit.
  R = 1.0% of entry for sizing and R reporting. No target: this rule does **not** have the brief's 1:2 planned
  risk/reward and could only be used if a compliant form were designed later.
* Instrument: NIFTY index ETF in cash (index / 100, NIFTYBEES style). BANK NIFTY (same rule on its own r1) is a
  diagnostic universe, not part of the verdict. One trade a day.

### EXP-0069 `nifty_intraday_momentum_bigmove`
EXP-0068, traded only when |r1| ≥ the 80th percentile of |r1| over the previous 250 sessions with a valid r1 (at
least 120 needed; earlier days skipped). Motivation: the paper reports stronger predictability when volatility is
high (hypothesis that this carries to NIFTY).

### EXP-0070 `orb5_stocks_in_play` (reconstruction of Zarattini & Aziz; exact rules UNVERIFIED)
* Eligible stock on day t: gate-1 day; 20-session median official traded value ≥ ₹50 crore; previous close ≥ ₹50
  (house filter replacing the paper's $5 / 1M-share screen; the $0.50 ATR screen has no rupee equivalent and is
  dropped).
* RVOL = volume of the first 5-minute bar (09:15–09:19) / mean first-5-minute volume of the previous 14 sessions
  (at least 10 available). Stock in play: RVOL ≥ 1.0.
* Direction: first 5-minute bar close > open → long; close < open → short; equal → none.
* Entry: open of the 09:20 1-min bar. Stop: the first 5-minute bar's low (long) / high (short). Skip if the stop is
  closer than 0.20% or farther than 2.0% of entry (house rule from EXP-0061..0066).
* Target: 10R (reconstruction of the published version's large target); otherwise exit at the 15:15 open.
  Stop before target in a 1-min bar; a bar opening through the stop fills at its open.
* One trade a day: among stocks in play with a valid setup, the highest RVOL. The paper's form (top 20 by RVOL,
  equal risk each) is reported as a diagnostic ("top-20 all signals").

## Sizing, costs, metrics, acceptance (identical to EXP-0061..0066)
Scenario A: ₹300 planned risk including slippage and round-trip charges. Scenario B: also ≤ ₹15,000 notional.
Groww intraday equity charges as in that spec (UNVERIFIED on the live pricing page). Slippage per side 0.02% stocks,
0.03% index ETF; sensitivity 0, base, 0.05%, 0.10%; stress 2× slippage and charges.
Metrics: trades, win rate, average win and loss (₹), profit factor, expectancy (₹, R), max drawdown, longest losing
streak, charges, slippage sensitivity, month-clustered bootstrap 95% interval of mean net R, per-year results.

**Acceptance (scenario A, one-trade-a-day, per rule):** dev ≥ 100 trades; dev mean net R > 0 with bootstrap interval
above 0; dev profit factor ≥ 1.15; both dev halves > 0; dev stress > 0; validation > 0 and stress > 0; holdout > 0;
and walk-forward: mean net R > 0 in at least two-thirds of calendar years. Three rules are tried, so one pass by
luck is plausible. A pass = **forward paper candidate** only (owner rule G: paper results must also support it
before the live candidate pool). Otherwise **REJECTED**.

## Known limitations
Unofficial 1-minute data; stock list survivorship (vendor's 2021 list, A–TATACHEM) flatters longs; stock data ends
2020, so EXP-0070 cannot be checked on 2021–2026; no order book (bar prices plus fixed slippage); ETF tracking error
and spread not modelled; source rules not read in full text (network); broker charges and square-off time not
verified; gaps and halts can lose more than the planned ₹300.

## Changelog
* v0.1 (2026-11-03): first version, pre-registered before any run.
