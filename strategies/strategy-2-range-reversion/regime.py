"""
Regime filter: decides whether the market is in a "clean, tradeable range"
vs. chop (frequent false breakouts) or trend (boundaries won't hold).

Produces two per-bar scores:
  range_score      — evidence of directionless/bounded price action (0-1, higher = more range-like)
  boundary_respect  — fraction of recent boundary touches that reversed rather than breached (0-1)

Everything here is computed once, vectorized, over the whole series using only
past data at each row (rolling windows), so it's safe to precompute and then
index into during the event loop without look-ahead.
"""
import numpy as np
import pandas as pd
import indicators as ind


def compute_regime_scores(
    df: pd.DataFrame,
    atr_series: pd.Series,
    lookback: int = 30,
    ema_cross_lookback: int = 30,
) -> pd.DataFrame:
    close = df["close"]
    ema20 = ind.ema(close, 20)
    adx14 = ind.adx(df, 14)
    atr_pct = (atr_series / close) * 100
    atr_pct_median = atr_pct.rolling(30).median()
    eff_ratio = ind.efficiency_ratio(close, lookback)
    boll_width = ind.bollinger_width(close, 20)
    boll_width_median = boll_width.rolling(30).median()
    crosses = ind.ema_cross_count(close, ema20, ema_cross_lookback)

    # Normalize each signal to a 0-1 "range-like-ness" contribution, then average.
    # Each sub-score is built symmetrically around its own rolling median so it
    # centers near 0.5 (not structurally biased low/high) -> 1.0 = value is far
    # below its recent median (calm/compressed), 0.0 = far above (expanding).
    def centered_score(value: pd.Series, median: pd.Series) -> pd.Series:
        ratio = value / median.replace(0, np.nan)
        return (1 - (ratio - 1)).clip(0, 1).fillna(0.5)

    s_adx = (35 - adx14.clip(0, 35)) / 35                      # low ADX -> high score
    s_atrpct = centered_score(atr_pct, atr_pct_median)
    s_crosses = (crosses / ema_cross_lookback).clip(0, 1)      # many crosses -> high score (choppy AND bounded)
    s_eff = (1 - eff_ratio).clip(0, 1)                         # low efficiency -> high score
    s_boll = centered_score(boll_width, boll_width_median)

    range_score = pd.concat([s_adx, s_atrpct, s_crosses, s_eff, s_boll], axis=1).mean(axis=1)

    out = pd.DataFrame({
        "adx": adx14,
        "atr_pct": atr_pct,
        "efficiency_ratio": eff_ratio,
        "ema_crosses": crosses,
        "bollinger_width": boll_width,
        "range_score": range_score,
    }, index=df.index)
    return out


def compute_boundary_respect(touch_outcomes: list[bool], n_recent: int = 10) -> float:
    """
    touch_outcomes: chronological list of True (reversed) / False (breached) for
    every level touch seen so far. Returns fraction reversed among the most
    recent `n_recent` (or all, if fewer exist yet) — called incrementally
    inside the event loop so it only ever sees past touches.
    """
    if not touch_outcomes:
        return 0.5  # neutral prior with no history yet
    recent = touch_outcomes[-n_recent:]
    return sum(recent) / len(recent)
