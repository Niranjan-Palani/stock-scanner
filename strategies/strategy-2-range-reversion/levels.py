"""
Key-level (support/resistance) detection.

A level is a *zone*, not a price point. It's built by clustering "touches" —
bars where price entered the tolerance zone and then reversed away from it
within `reversal_confirm_bars`. This module is intentionally bar-by-bar
(not vectorized) because level state depends on a rolling window of prior
touches that isn't a simple rolling-window arithmetic reduction, and getting
that vectorized correctly without look-ahead is error-prone. Runtime is fine
for the bar counts this project deals with (thousands, not millions).
"""
from dataclasses import dataclass, field
import pandas as pd


@dataclass
class Level:
    price: float
    kind: str            # "support" or "resistance"
    touches: list         # bar indices (int position) where a confirmed touch happened
    last_touch_idx: int
    active: bool = True


def _tolerance(price: float, atr_value: float, mode: str, pct: float, atr_mult: float) -> float:
    if mode == "pct":
        return price * pct
    if mode == "atr":
        return atr_value * atr_mult
    # "combo": whichever the caller marks as more stable for this run; default to pct if ATR is NaN.
    if pd.isna(atr_value):
        return price * pct
    return min(price * pct, atr_value * atr_mult)


def detect_levels(
    df: pd.DataFrame,
    atr_series: pd.Series,
    tolerance_mode: str = "pct",       # "pct" | "atr" | "combo"
    tolerance_pct: float = 0.0015,      # 0.15%
    tolerance_atr_mult: float = 0.5,
    min_touches: int = 2,
    level_window_days: int = 2,
    reversal_confirm_bars: int = 3,
) -> list[Level]:
    """
    Scans the full bar series once and returns every level that qualified at
    any point, each carrying the bar indices of its confirmed touches. The
    caller (strategy.py) is responsible for only treating a level as "active
    as of bar t" if all of its touches occurred at or before t and it hasn't
    since been invalidated by a structural stop-break — that recency check
    happens per-bar in the event loop, not here, to keep this function pure
    and side-effect-free (no look-ahead risk).
    """
    n = len(df)
    highs, lows, closes = df["high"].values, df["low"].values, df["close"].values
    sessions = df["session"].values
    unique_sessions = sorted(set(sessions))
    session_to_ordinal = {s: i for i, s in enumerate(unique_sessions)}
    session_ord = [session_to_ordinal[s] for s in sessions]

    # Candidate "pivot" prices: local extremes over a small neighborhood, since
    # scanning every close as a candidate level is wasteful and noisy.
    pivots = []
    W = 2
    for i in range(W, n - W):
        window_h = highs[i - W:i + W + 1]
        window_l = lows[i - W:i + W + 1]
        if highs[i] == window_h.max():
            pivots.append((i, highs[i]))
        if lows[i] == window_l.min():
            pivots.append((i, lows[i]))

    levels: list[Level] = []

    for pivot_idx, pivot_price in pivots:
        tol = _tolerance(pivot_price, atr_series.iloc[pivot_idx], tolerance_mode, tolerance_pct, tolerance_atr_mult)
        if tol <= 0 or pd.isna(tol):
            continue

        # Count touches: bars within `level_window_days` sessions of this pivot
        # (looking backward only, since a level can't be "known" before it forms)
        # that entered [pivot_price - tol, pivot_price + tol] and then closed
        # back away by >= tol within reversal_confirm_bars.
        touches = []
        min_session_ord = session_ord[pivot_idx] - level_window_days
        for j in range(max(0, pivot_idx - 500), min(n, pivot_idx + 500)):
            if session_ord[j] < min_session_ord:
                continue
            if session_ord[j] > session_ord[pivot_idx]:
                break  # levels only matter as-of their own formation point going forward in strategy.py
            entered = (lows[j] <= pivot_price + tol) and (highs[j] >= pivot_price - tol)
            if not entered:
                continue
            # look forward up to reversal_confirm_bars for a close-away reversal
            for k in range(j + 1, min(n, j + 1 + reversal_confirm_bars)):
                if closes[k] >= pivot_price + tol:  # reversed up -> support-type touch
                    touches.append(k)
                    break
                if closes[k] <= pivot_price - tol:  # reversed down -> resistance-type touch
                    touches.append(k)
                    break

        if len(touches) >= min_touches:
            kind = "support" if closes[pivot_idx] >= pivot_price else "resistance"
            levels.append(Level(price=pivot_price, kind=kind, touches=touches, last_touch_idx=max(touches)))

    return levels
