# Strategy 2 — Intraday Range-Reversion: Full Report

**Status:** Implemented, backtested, tuned per the first pass's findings. Sample size is still thin
(see caveat below) — treat this as a validated *engine* with a *directionally promising* parameter set,
not a proven edge ready for live capital.

---

## 1. The strategy, in plain terms

**One-line thesis:** in a stock that's confirmed to be trading in a range (not trending, not chopping
randomly), buy near the support level it keeps bouncing off of, short near the resistance level it
keeps rejecting from, and take profit at the middle of the range rather than trying to ride it further.

It has four moving parts, each of which has to say "yes" before a trade fires:

### a) Where are support and resistance?

The engine scans every local price pivot (a high or low relative to its immediate neighbors) and asks:
over the last **2 trading days**, did price approach this level and reverse away from it at least
**2 times**? "Approach" means entering a small price zone around the level (0.15% of price by
default); "reverse" means closing back out of that zone within the next 3 bars. If yes, that pivot
becomes an active level — support if price currently sits above it, resistance if below. The nearest
active support below the current price and nearest active resistance above it define **the current
range**, and the **midpoint between them is the profit target**.

This re-evaluates on every single bar, so levels appear, persist, and get invalidated dynamically as
the session unfolds — nothing is hand-drawn or fixed for the day.

### b) Is this actually a range worth trading?

A stock can *look* like it's bouncing between two prices by pure chance for a few bars and then break
out and run. To avoid getting chopped up by that, the engine only trades when a **regime score**
built from five separate signals agrees the market is genuinely range-bound:

- **ADX(14)** below a threshold (trend strength is low)
- **ATR%** below its own recent median (volatility is compressed, not expanding)
- **EMA(20) crossing frequency** — price crossing back and forth over its own moving average often is
  a range signature
- **Efficiency ratio** — how much of the recent net price movement was "wasted" going back and forth
  vs. traveling in one direction (low = range-like)
- **Bollinger Band width** compressed relative to its own recent median

These five are averaged into one `range_score` (0–1). The engine also tracks **boundary respect** —
of the last several times price touched a level, what fraction actually reversed vs. broke through.
A trade only fires when `range_score`, `boundary_respect`, and ADX **all** clear their thresholds
simultaneously.

### c) The entry trigger

The engine never fires a bare limit order sitting at the level — it waits for confirmation that price
actually turned:

- **Long:** price touches/wicks into the support zone, then prints **2 consecutive up-closing bars**
- **Short:** price touches/wicks into the resistance zone, then prints **2 consecutive down-closing bars**

Both directions are traded symmetrically. One important guard I added while building this: if those 2
confirmation bars carry price *past* the range midpoint before the entry actually fires, the trade is
skipped rather than opened already-past-its-own-target — this happens on tight ranges and would
otherwise silently produce nonsense trades.

### d) Exits — three ways out, whichever comes first

1. **Take profit** at the range midpoint, fixed at the moment of entry.
2. **Structural stop** — if price closes beyond the level being traded off of for 2 consecutive bars,
   exit at market. This also invalidates that level (it's no longer trustworthy support/resistance).
3. **Time stop** — if neither has happened within 4 hours, exit at market regardless.

Only one position per ticker is held at a time.

---

## 2. What I changed after the first backtest pass, and why

The first run flagged three specific, evidence-backed issues. Here's what I changed in the code
(`strategy.py`, `Params` defaults) to act on them:

| Parameter | Was | Now | Why |
|---|---|---|---|
| `adx_max` | 20 | **25** | Every cut of the grid search showed 25–30 producing *more trades and better expectancy* than the stricter default of 20. The trend filter was over-tight. |
| `range_score_min` | 0.55 | **0.50** | Confirmed workable band is 0.45–0.55; 0.70+ measurably starves the strategy (down to 1 trade, negative expectancy). Set to the middle of the good band rather than its edge. |
| `respect_min` | 0.5 | **0.3** | Above ~0.5 this gate produced **zero trades** in the sample — it behaves like an on/off switch, not a dial, because there isn't enough resolved touch history in 9 months on 5 tickers to reliably clear a high bar. Lowered so it filters lightly instead of blocking outright. |
| `confirm_bars` | 2 | **2 (unchanged, confirmed critical)** | This is the one finding backed by real sample size: dropping to 1 produced 515–539 trades at ~69% win rate but **negative expectancy** — the textbook "high win rate, losing strategy" trap from tiny targets vs. large structural stops. Left at 2 deliberately; flagged in code comments so nobody "optimizes" it back down later. |

Everything else (`min_touches`, `reversal_confirm_bars`, `stop_consecutive_closes`, `max_hold_bars`)
was left at spec defaults — the first pass found no clear signal either way for these, and moving them
without evidence would just be guessing.

---

## 3. Results with the updated defaults

**Universe:** AAPL, MSFT, KO, F, SOFI · **Timeframe:** 15m · **Data:** ~9 months (2025-11-05 to
2026-08-14), Twelve Data · **Split:** chronological 70/30 by session date

### Baseline (new defaults), pooled across all 5 tickers, train split

| Metric | Value |
|---|---|
| Total trades | 8 |
| Win rate | 75.0% |
| Expectancy / trade | **+0.155%** |
| Profit factor | 75.4 |
| Avg R | 0.165 |
| Long / short split | 2 / 6 |
| Long win rate / Short win rate | 100% / 66.7% |
| Max drawdown | -0.71% |
| Avg hold time | 18.8 min |
| Exit breakdown | 8/8 hit target, 0 stopped out, 0 timed out |

This is a real improvement over the original defaults (5 trades, +0.097% expectancy) — more trades
*and* higher expectancy per trade, which is the outcome you want from loosening an over-tight filter
rather than a trade-off.

### Re-run grid search confirms the new baseline sits at the top

Re-running the same 162-combo × 5-ticker grid with the new baseline as center: the new defaults
(`adx_max=25, range_score_min=0.50→0.55 tie, respect_min=0.3, confirm_bars=2`) land **at or within
noise of the #1 ranked combo by expectancy** — this isn't a coincidence, it's the grid search's own
top pick being adopted as the default, which is the right order of operations (search → adopt winner
→ re-verify), not "pick a number and hope."

### Sensitivity around the new baseline — a few new observations this pass surfaced

- **`min_touches=3`** looked notably better than 2 in this re-run (10 trades, +0.30% expectancy, PF
  180) — this wasn't visible clearly in the first pass and is worth testing further, but with only 10
  trades it's not yet a strong enough signal to adopt as a default change.
- **`tolerance_pct` wider (0.25–0.40%)** again showed the same pattern as before: fewer, cleaner trades,
  higher win rate and expectancy each — consistent evidence, still only 3–6 trades at the wide end.
- **`respect_min` still hard-gates above 0.5** — confirms the fix was necessary; below that it's flat
  (no effect from 0.2 to 0.4), which is expected once it's no longer the binding constraint.
- **`confirm_bars=1` is still broken** — 515 trades, negative expectancy, exactly as before. Second
  confirmation independently of the first run.

### Out-of-sample: still not a real validation

The top combos' test-set performance still looks *good* (2–4 trades, 100% win rate, positive
expectancy) — but I'm repeating the caveat because it's the same underlying problem: **a 2-to-4-trade
out-of-sample sample cannot validate anything statistically.** It's consistent with the strategy not
having an obvious flaw, but it is not proof of an edge.

---

## 4. Bottom line

The engine works correctly (no look-ahead, no data leakage, the entry-past-target bug from the first
pass is fixed and guarded against), and the parameter changes made are each backed by evidence from
the grid search rather than guesses. But **8–12 trades per backtest run is not a sample size you can
size real capital against.** The next concrete step, if you want to actually evaluate whether this has
a tradeable edge, is widening the universe — this strategy structurally needs range-prone, moderate-
volatility names, and 5 large/mega-caps over 9 months just doesn't generate enough setups. I'd suggest
re-running against 20–30 tickers (I can reuse the Strategy 1 low-float watchlist, or pull a fresh list
of historically range-bound names) before drawing any conclusion about real-money viability.

## 5. Assumptions (unchanged from the first pass — still need your sign-off)

- **Fees:** 1 bps/side (2 bps round-trip), flat.
- **Slippage:** 2 bps per fill, both directions.
- **Fills:** entries/target exits fill at the theoretical trigger price; stop exits fill at the closing
  price of the 2nd confirming close-beyond-level bar. No partial fills.
- **Gaps:** if price gaps through a stop/target between bars, the backtest still credits the theoretical
  level rather than the worse gapped price — a known optimistic bias, not corrected for.
- **Regular trading hours only** (9:30–16:00 ET); no pre/post-market bars; levels don't persist across
  the overnight gap beyond what `level_window_days` naturally carries forward.
- **One position per ticker**, independent capital assumed across the 5-ticker pooled result (no shared
  margin/sizing constraint modeled).
- **Bar timestamp = bar open time** (Twelve Data convention); every decision at bar *t* uses only data
  from bars ≤ *t*.
- **No earnings-day exclusion** implemented (`skip_earnings_day` was specified as optional/OFF; I don't
  have a free earnings-calendar source wired up — say the word if you want it added).

## 6. Universe expansion to 30 tickers + capped-loss/trailing-stop change

The 5-ticker universe in §3 was too thin to draw conclusions from, as flagged in the bottom line above.
Two follow-up changes since that pass:

**a) Universe widened to 30 tickers** — reused the Strategy 1 low-float/range-prone watchlist (F, T,
PLTR, SOFI, NIO, AAL, CCL, PBR, KGC, GRAB, RIG, VALE, WBD, UAA, OPEN, CLSK, RIOT, MARA, AMCR, KVUE,
HBAN, KEY, CFG, RF, NCLH, UAL, DKNG, LYFT, PARA, SIRI), with 5min and 15min bars refetched back to
2024-01-01 (`fetch_more_history.py`, `output/fetch_log_extend.txt`). This is what produced a workable
train-split sample size (76 trades vs. 8).

**b) Capped structural stop + trailing stop past target** — the original design let the structural
stop run arbitrarily far in a real breakdown (small capped wins vs. occasional large losses,
negative-skew asymmetry). Fixed with two additive changes in `strategy.py`:
- `max_loss_pct` (0.6% default): hard caps initial risk at entry — whichever of the structural stop or
  the % cap is *tighter* wins.
- `trail_enabled` / `trail_atr_mult`: once price reaches the original range-midpoint target, instead of
  taking the fixed exit, arm an ATR-based trailing stop and let winners run further, uncapping the win
  side to offset the now-capped loss side.

### Trailing-stop grid search (`sweep_trailing.py`, 30 tickers, train split, 16 combos)

| max_loss_pct | trail_atr_mult | trades | win rate | expectancy | PF | avg R |
|---|---|---|---|---|---|---|
| 0.004 | 2.0 | 37 | 62.2% | **+1.07%** | 5.42 | 2.67 |
| 0.006 | 2.0 | 37 | 62.2% | +1.04% | 4.90 | 1.73 |
| 0.004 | 1.0 | 76 | 61.8% | +0.93% | 3.35 | 2.33 |
| 0.006 | 1.0 (baseline before change) | 76 | 63.2% | +0.90% | 2.97 | 1.51 |

`trail_atr_mult=2.0` clearly dominates on expectancy and profit factor despite fewer trades (tighter
trail exits fewer positions into "target" mid-range and lets more run to a real trend move). Four
combos at `trail_atr_mult=0.5` were flagged as win-rate traps (68-71% win rate but the *lowest*
expectancy of the grid) — same textbook trap as `confirm_bars=1` in §2, confirming the trap-detection
logic is doing its job on a second, unrelated parameter.

**Out-of-sample check on top 5:** none flagged `likely_overfit`. Expectancy degrades from train to test
(1.07% → 0.44% for the top combo) as expected for a small out-of-sample slice, but stays solidly
positive with test PF 1.7-1.8 across all five. `trail_atr_mult=2.0` held up; `max_loss_pct` was
largely a wash between 0.004-0.010 in this slice.

**Sensitivity sweep** around the (then-)baseline confirms `trail_atr_mult=2.0` (and even 3.0, +1.26%
expectancy, 29 trades) beats every value below it monotonically once you're above 1.0 — `1.5` is a dip
(win-rate trap territory again) before it recovers. `max_loss_pct` is comparatively flat across
0.003-0.015 in the pooled sensitivity table, so it's not a high-leverage knob on its own.

**Adopted:** `strategy.py` defaults now carry `trail_atr_mult=2.0` (up from the 1.0 initial guess) and
`max_loss_pct=0.006` kept at its original conservative middle value rather than chasing the marginal
train-split edge of 0.004, since the grid/OOS split didn't clearly separate the two. Both changes are
commented inline in `Params` with the validation reasoning (`strategy.py:44`, `:50`).

**Still open:** `trail_atr_mult=3.0` outperformed 2.0 in the standalone sensitivity sweep but wasn't
in the original grid range — worth a follow-up grid extending to 2.5/3.0 before treating 2.0 as final.

---

## Files

`C:\Users\niran\trading-dashboard\strategies\strategy-2-range-reversion\`
- `strategy.py` — engine + updated `Params` defaults (with rationale comments inline)
- `output/report.md` — this report
- `output/run_log_v2.txt`, `grid_results.csv`, `out_of_sample.csv`, `sensitivity.csv` — 5-ticker re-run data (§3)
- `output/run_log_v3_30tickers.txt` — 30-ticker universe expansion run
- `output/trailing_grid_results.csv`, `trailing_out_of_sample.csv`, `trailing_sensitivity.csv`,
  `trailing_sweep_log.txt` — capped-stop/trailing-stop validation data (§6)
- `fetch_more_history.py`, `output/fetch_log_extend.txt` — extended history fetch for the 30-ticker universe
