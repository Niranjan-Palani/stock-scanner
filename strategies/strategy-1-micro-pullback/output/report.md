# Strategy 1 — Micro Pullback: Backtest Results

**Status:** First pass. Engine built and run; results are directional, not a validated edge.

## Scope caveat (read this first)

This backtests the **entry/exit mechanics** of the Ross Cameron micro-pullback strategy only:
squeeze → 1-2 candle pullback (light volume) → break of prior candle's high, confirmed by MACD
positive/rising, exit on stop / 2:1 target / MACD bearish cross / close below VWAP / close below 9 EMA.

It does **not** implement the "Five Pillars" stock-selection filter (float <10-20M shares, fresh
news catalyst, up 25%+ on the day) — this data source has no float or news-catalyst history, and
the watchlist (F, T, PLTR, AAL, CCL, KO, etc.) is mostly large/mid-cap names, not the low-float
runners the strategy is actually designed around. Treat this as "does the pullback pattern itself
have edge on this universe," not "does the full Ross Cameron system work."

Also: source strategy calls for MACD on the 1-minute chart; only 5-min bars were available
(same data already fetched for strategy-2), so MACD here is on 5-min, which is slower/less
sensitive than intended.

## Setup

- **Universe:** all 30 watchlist tickers, 5-min bars, chronological 70/30 train/test split by session date.
- **Params (defaults, untuned — no grid search run yet):** squeeze = +3% over 6 bars with 1.5x relative
  volume, max 2 pullback candles, target = 2:1 reward:risk, max hold 2h.
- **Costs:** 1bps/side fee, 2bps slippage — same assumptions as strategy-2.

## Results — v1 (fixed 2:1 target)

| | Train | Test |
|---|---|---|
| Trades | 87 | 26 |
| Win rate | 28.7% | 30.8% |
| Expectancy/trade | **-0.150%** | **+0.167%** |
| Profit factor | 0.70 | 1.52 |
| Avg R | -0.18 | 0.19 |
| Avg hold | 19.7 min | 22.9 min |
| Exit breakdown | 17 target / 39 stop / 9 MACD-cross / 16 below-VWAP / 6 below-EMA9 | 7 target / 6 stop / 3 MACD-cross / 6 below-VWAP / 4 below-EMA9 |

## Results — v2 (trailing stop past target, `trail_atr_mult=2.0`)

Change: once price reaches the original 2:1 target, arm an ATR-based trailing stop instead of
exiting immediately, letting winners run further — same change validated for strategy-2.

| | Train | Test |
|---|---|---|
| Trades | 87 | 26 |
| Win rate | 27.6% | 26.9% |
| Expectancy/trade | -0.082% (was -0.150%) | **+0.304%** (was +0.167%) |
| Profit factor | 0.84 (was 0.70) | **1.92** (was 1.52) |
| Avg R | -0.01 (was -0.18) | **0.62** (was 0.19) |
| Avg hold | 38.2 min (was 19.7) | 61.7 min (was 22.9) |
| Exit breakdown | 40 stop / 16 trail / 9 MACD-cross / 16 below-VWAP / 6 below-EMA9 | 6 stop / 7 trail / 3 MACD-cross / 6 below-VWAP / 4 below-EMA9 |

Win rate ticked *down* slightly (fewer trades exit at the fixed target now — some ride the trail
instead), but every profitability metric improved, most sharply avg R and expectancy on test. This
is the expected trade-off: uncapping the win side to compensate for a still-sub-33% win rate. Hold
times roughly doubled, which matters for a day-trading strategy — confirm this doesn't conflict
with the source material's session-based risk rules (3-losses-in-a-row stop, etc.) before treating
this as adopted.

## Read

- Both splits sit near the strategy's own stated breakeven line: at a 2:1 payoff, 33% win rate is
  breakeven (per the Obsidian note). Train (28.7%) falls just under that and is net negative;
  test (30.8%) falls just under it too but is net *positive* because fewer trades got stopped out
  relative to hitting target — this is a thin-sample coin-flip, not a demonstrated edge either way.
- **113 total trades pooled is a small sample** for a strategy with this many independent filters
  (squeeze, pullback count, light-red-volume, MACD, entry trigger) — same caveat as strategy-2's
  first pass. Don't size anything off this.
- Non-target exits dominate (macd-cross + below-vwap + below-ema9 = 31 of 87 train exits) — the
  discretionary-style exit rules are firing a lot, which matches the source material's "any one exit
  signal = get out" design, but means the realized R is usually less than the full 2:1 target R.
- No parameter search has been run yet (unlike strategy-2, which iterated `adx_max`, `range_score_min`,
  etc. against grid search evidence before adopting defaults). These are first-guess parameters.

## Universe fix + grid search (follow-up pass)

**Universe check:** queried Finnhub float data (`filter_universe.py`) for the original 30-ticker
watchlist — **0 of 30** have float under 20M shares (median float in the billions). This confirms
the original backtest's ticker universe cannot represent this strategy at all, regardless of
parameters. Screened 25 commonly-cited small-cap/low-float names and found 7 that actually pass:
**ATER, CENN, PHUN, KOSS, BENF, SOS, SNTI** (float 1.2M–19.7M). Fetched 5-min bars for these via
Twelve Data and re-ran.

**Real low-float universe result — worse, not better:**

| | Train | Test |
|---|---|---|
| Trades | 62 | 22 |
| Win rate | 17.7% | **0.0%** |
| Expectancy/trade | -1.03% | **-1.66%** |
| Profit factor | 0.25 | 0.00 |

Zero winning trades out of 22 on the test split. This is a much more negative result than the
original mega-cap universe produced, not an artifact of small sample size in the usual "not enough
trades" sense — it's a consistent pattern across 7 different tickers.

**Grid search (81 combos: `squeeze_min_pct`, `squeeze_vol_mult`, `pullback_light_vol_mult`,
`reward_risk_min`) on this real universe:** every one of the top 10 combos ranked by train
expectancy is *also* negative on train, and every one of those 10 is negative on test too — several
with a literal 0% test win rate. This is not the "looks great on train, collapses on test" overfit
pattern strategy-2 flagged for parameter changes — it's uniform unprofitability regardless of the
parameters tried. The entry/exit mechanics as coded do not have an edge on genuine low-float names
in this sample.

**What this means:** the earlier working theory — "the mechanics are fine, the universe was just
wrong" — turned out to be wrong. Correcting the universe made results *worse*, which suggests either
(a) low-float small-caps behave differently enough (choppier, more prone to real breakdowns, less
clean pullback structure) that this entry logic doesn't suit them, or (b) 5-min bars are too slow
for genuinely fast low-float momentum moves and 1-min data is a harder requirement here than for the
mega-cap universe, or (c) 7 tickers / ~9 weeks of history is still too small a sample to trust either
way. Can't distinguish between these without more data — most likely candidate given the source
material's own emphasis on 1-min charts for this exact type of stock is (b).

## Honest bottom line

Not evidence of an edge, and can't be — real Five Pillars filtering (low float + fresh catalyst +
already up 25%+) is exactly the part of this strategy that's *not* tested here, and that's the part
Ross Cameron's own material treats as doing most of the filtering work before the pullback pattern
even applies. What this run validates is that the pullback/MACD/VWAP mechanics are implemented
correctly and produce a plausible, not-obviously-broken trade distribution. Next steps if you want to
push further: (1) grid search the squeeze/pullback parameters the way strategy-2 did, (2) get a
true low-float/high-relative-volume intraday dataset (this watchlist isn't it) before trusting any
win-rate number here.

## Files

`C:\Users\niran\trading-dashboard\strategies\strategy-1-micro-pullback\`
- `strategy.py` — engine (`Params`, `run_backtest`)
- `indicators.py` — MACD, session VWAP, EMA (local to this strategy)
- `run_backtest.py` — runs all 30 tickers, writes `output/backtest_results.json`
- `output/backtest_results.json` — full per-symbol + pooled train/test results
