"""
Bar-by-bar event loop: the actual trade logic. Deliberately not vectorized —
range-reversion entries/exits depend on path-dependent state (which level is
active, is a position open, how many consecutive confirm bars have printed)
that vectorized pandas can't express without look-ahead risk. This is the
one place in the engine where "clear bar-by-bar loop" beats "vectorized."

Decision rule at every bar t: only df.iloc[:t+1] is ever read.
"""
from dataclasses import dataclass, field
import pandas as pd
import numpy as np

import indicators as ind
from levels import Level, detect_levels
from regime import compute_regime_scores, compute_boundary_respect


@dataclass
class Params:
    tolerance_mode: str = "pct"          # "pct" | "atr" | "combo"
    tolerance_pct: float = 0.0015
    tolerance_atr_mult: float = 0.5
    min_touches: int = 2
    level_window_days: int = 2
    reversal_confirm_bars: int = 3
    confirm_bars: int = 2                # entry confirmation bars — DO NOT drop to 1, see report §3
    adx_max: float = 25.0                # was 20 — loosened per grid search, consistently more trades + better expectancy at 25-30
    range_score_min: float = 0.50        # kept in the 0.45-0.55 band that works; 0.70+ starves the strategy of setups
    respect_min: float = 0.3             # lowered from 0.5 — acts as an on/off switch above ~0.5 given limited touch history
    ema_cross_lookback: int = 30
    stop_consecutive_closes: int = 2
    max_hold_bars: int = 16              # 4h at 15m bars; caller converts from timeframe
    session_filter: bool = False         # skip first/last 30 min
    volume_filter: bool = False
    volume_min_mult: float = 0.5         # min bar volume vs its 20-bar average, if volume_filter on
    fee_bps: float = 1.0                 # round-trip fee, in basis points of notional, each side
    slippage_bps: float = 2.0            # slippage per fill, in basis points

    # Loss cap: structural stop (level break) can be arbitrarily far in a real
    # breakdown, which is what produced the negative-expectancy asymmetry
    # (small capped wins vs. occasional large losses). Cap it at max_loss_pct
    # of entry price — whichever stop is TIGHTER (closer to entry) wins.
    max_loss_pct: float = 0.006          # 0.6% hard cap on any single trade's initial risk

    # Trailing stop: once price reaches the original range-midpoint target,
    # instead of exiting, arm a trailing stop and let the winner run further.
    # This uncaps the win side to offset the now-capped loss side.
    trail_enabled: bool = True
    trail_atr_mult: float = 2.0          # validated via grid+OOS: 2.0 beat the original 1.0 guess, held up out-of-sample


@dataclass
class Trade:
    entry_idx: int
    entry_time: pd.Timestamp
    exit_idx: int = None
    exit_time: pd.Timestamp = None
    direction: str = None                # "long" | "short"
    entry_price: float = None
    exit_price: float = None
    stop_price: float = None
    target_price: float = None
    exit_reason: str = None              # "target" | "stop" | "time" | "trail"
    r_multiple: float = None
    pnl_pct: float = None


def _bars_per_session_open(session_series, idx, minutes_from_open, bar_minutes):
    # True if bar `idx` falls within `minutes_from_open` minutes of that session's first bar.
    session = session_series[idx]
    session_start = None
    i = idx
    while i >= 0 and session_series[i] == session:
        session_start = i
        i -= 1
    return (idx - session_start) * bar_minutes < minutes_from_open


def run_backtest(df: pd.DataFrame, params: Params, timeframe_minutes: int = 15) -> tuple[list[Trade], pd.Series]:
    n = len(df)
    highs, lows, closes, opens = df["high"].values, df["low"].values, df["close"].values, df["open"].values
    volumes = df["volume"].values
    sessions = df["session"].values
    times = df.index

    atr_series = ind.atr(df, 14)
    regime = compute_regime_scores(df, atr_series, lookback=30, ema_cross_lookback=params.ema_cross_lookback)
    vol_avg20 = pd.Series(volumes, index=df.index).rolling(20).mean().values

    levels = detect_levels(
        df, atr_series,
        tolerance_mode=params.tolerance_mode,
        tolerance_pct=params.tolerance_pct,
        tolerance_atr_mult=params.tolerance_atr_mult,
        min_touches=params.min_touches,
        level_window_days=params.level_window_days,
        reversal_confirm_bars=params.reversal_confirm_bars,
    )
    # Index levels by the bar at which they first qualify (their min_touches-th touch),
    # so the event loop can pick up newly-qualified levels bar by bar without look-ahead.
    levels_sorted = sorted(levels, key=lambda lv: sorted(lv.touches)[params.min_touches - 1])
    level_ready_idx = [sorted(lv.touches)[params.min_touches - 1] for lv in levels_sorted]

    trades: list[Trade] = []
    equity = np.zeros(n)
    equity_val = 0.0
    touch_outcomes: list[bool] = []   # for boundary_respect, updated as touches resolve

    position = None       # dict: direction, entry_idx, entry_price, stop_level, target, entry_bar_count
    active_levels: list[Level] = []
    lvl_pointer = 0
    confirm_streak = 0     # consecutive up/down closes toward entry trigger
    pending_direction = None
    stop_break_streak = {}  # level_price -> consecutive closes beyond it

    fee = params.fee_bps / 10000.0
    slip = params.slippage_bps / 10000.0
    min_period = 35  # let indicators warm up (ATR14, EMA20, 30-bar regime lookback)

    for t in range(min_period, n):
        # 1) bring newly-qualified levels into the active set
        while lvl_pointer < len(levels_sorted) and level_ready_idx[lvl_pointer] <= t:
            active_levels.append(levels_sorted[lvl_pointer])
            lvl_pointer += 1
        # drop levels invalidated by a structural stop-break as of prior bars
        active_levels = [lv for lv in active_levels if lv.active]

        price = closes[t]

        # 2) manage open position first (exits take priority over new entries)
        if position is not None:
            bars_held = t - position["entry_idx"]
            exit_now, exit_price, reason = None, None, None
            atr_now = atr_series.iloc[t]

            if position["direction"] == "long":
                position["best"] = max(position["best"], highs[t])
                if closes[t] < position["stop_level"]:
                    stop_break_streak["pos"] = stop_break_streak.get("pos", 0) + 1
                else:
                    stop_break_streak["pos"] = 0
                # structural stop (capped at entry time, see max_loss_pct) always wins first
                if stop_break_streak.get("pos", 0) >= params.stop_consecutive_closes:
                    exit_now, exit_price, reason = True, price, "stop"
                elif not position["trailing"] and highs[t] >= position["target"]:
                    # reached the original range-midpoint target: arm the trailing stop
                    # instead of taking a fixed exit, so the winner isn't capped here.
                    # Never let the trail sit looser than the capped stop — it can only
                    # ratchet the exit closer to price, never widen the original risk cap.
                    if params.trail_enabled and not pd.isna(atr_now):
                        position["trailing"] = True
                        position["trail_stop"] = max(position["best"] - params.trail_atr_mult * atr_now, position["stop_level"])
                    else:
                        exit_now, exit_price, reason = True, position["target"], "target"
                elif position["trailing"]:
                    new_trail = position["best"] - params.trail_atr_mult * atr_now
                    if not pd.isna(new_trail):
                        new_trail = max(new_trail, position["stop_level"])
                        position["trail_stop"] = max(position["trail_stop"], new_trail)  # ratchets up only
                    if closes[t] < position["trail_stop"]:
                        exit_now, exit_price, reason = True, price, "trail"
            else:  # short
                position["best"] = min(position["best"], lows[t])
                if closes[t] > position["stop_level"]:
                    stop_break_streak["pos"] = stop_break_streak.get("pos", 0) + 1
                else:
                    stop_break_streak["pos"] = 0
                if stop_break_streak.get("pos", 0) >= params.stop_consecutive_closes:
                    exit_now, exit_price, reason = True, price, "stop"
                elif not position["trailing"] and lows[t] <= position["target"]:
                    if params.trail_enabled and not pd.isna(atr_now):
                        position["trailing"] = True
                        position["trail_stop"] = min(position["best"] + params.trail_atr_mult * atr_now, position["stop_level"])
                    else:
                        exit_now, exit_price, reason = True, position["target"], "target"
                elif position["trailing"]:
                    new_trail = position["best"] + params.trail_atr_mult * atr_now
                    if not pd.isna(new_trail):
                        new_trail = min(new_trail, position["stop_level"])
                        position["trail_stop"] = min(position["trail_stop"], new_trail)  # ratchets down only
                    if closes[t] > position["trail_stop"]:
                        exit_now, exit_price, reason = True, price, "trail"

            if not exit_now and bars_held >= params.max_hold_bars:
                exit_now, exit_price, reason = True, price, "time"

            if exit_now:
                fill = exit_price * (1 - slip) if position["direction"] == "long" else exit_price * (1 + slip)
                entry_fill = position["entry_price"]
                if position["direction"] == "long":
                    pnl_pct = (fill - entry_fill) / entry_fill - 2 * fee
                else:
                    pnl_pct = (entry_fill - fill) / entry_fill - 2 * fee
                risk_pct = abs(entry_fill - position["stop_level"]) / entry_fill
                r_mult = pnl_pct / risk_pct if risk_pct > 0 else 0.0

                tr = position["trade"]
                tr.exit_idx, tr.exit_time = t, times[t]
                tr.exit_price, tr.exit_reason = fill, reason
                tr.pnl_pct, tr.r_multiple = pnl_pct, r_mult
                trades.append(tr)
                equity_val += pnl_pct
                touch_outcomes.append(reason in ("target", "trail") and pnl_pct > 0)
                position = None
                stop_break_streak["pos"] = 0
                confirm_streak, pending_direction = 0, None

        equity[t] = equity_val

        if position is not None:
            continue  # one position at a time

        # 3) regime filter
        r = regime.iloc[t]
        if pd.isna(r["range_score"]) or pd.isna(r["adx"]):
            continue
        respect = compute_boundary_respect(touch_outcomes, n_recent=10)
        if not (r["range_score"] >= params.range_score_min and respect >= params.respect_min and r["adx"] <= params.adx_max):
            confirm_streak, pending_direction = 0, None
            continue

        if params.session_filter and _bars_per_session_open(sessions, t, 30, timeframe_minutes):
            continue
        if params.volume_filter and not np.isnan(vol_avg20[t]) and volumes[t] < params.volume_min_mult * vol_avg20[t]:
            continue

        # 4) find nearest active support below / resistance above -> define range
        supports = [lv for lv in active_levels if lv.kind == "support" and lv.price <= price]
        resistances = [lv for lv in active_levels if lv.kind == "resistance" and lv.price >= price]
        if not supports or not resistances:
            confirm_streak, pending_direction = 0, None
            continue
        support = max(supports, key=lambda lv: lv.price)
        resistance = min(resistances, key=lambda lv: lv.price)
        if resistance.price <= support.price:
            continue
        midpoint = (support.price + resistance.price) / 2

        tol_support = support.price * params.tolerance_pct if params.tolerance_mode == "pct" else atr_series.iloc[t] * params.tolerance_atr_mult
        tol_resist = resistance.price * params.tolerance_pct if params.tolerance_mode == "pct" else atr_series.iloc[t] * params.tolerance_atr_mult

        near_support = lows[t] <= support.price + tol_support
        near_resistance = highs[t] >= resistance.price - tol_resist

        # 5) entry trigger: confirmation bars after price wicked/closed back off a level
        if near_support and closes[t] > opens[t]:
            pending_direction = "long"
            confirm_streak = 1
        elif pending_direction == "long" and closes[t] > opens[t]:
            confirm_streak += 1
        elif near_resistance and closes[t] < opens[t]:
            pending_direction = "short"
            confirm_streak = 1
        elif pending_direction == "short" and closes[t] < opens[t]:
            confirm_streak += 1
        else:
            confirm_streak, pending_direction = 0, None

        if pending_direction and confirm_streak >= params.confirm_bars:
            entry_price_raw = price
            direction = pending_direction
            # Guard: the confirmation bars can carry price past the target before
            # entry actually fires (common on tight ranges) — if there's no room
            # left to the midpoint, this isn't a valid setup, so skip it rather
            # than open a trade that's already past its own take-profit.
            min_room = entry_price_raw * 0.0005  # at least 5bps of room to target
            no_room = (direction == "long" and entry_price_raw >= midpoint - min_room) or \
                      (direction == "short" and entry_price_raw <= midpoint + min_room)
            if no_room:
                confirm_streak, pending_direction = 0, None
                continue
            fill = entry_price_raw * (1 + slip) if direction == "long" else entry_price_raw * (1 - slip)
            structural_stop = support.price - tol_support if direction == "long" else resistance.price + tol_resist
            # Cap the initial risk at max_loss_pct of entry price — take whichever
            # stop is tighter (closer to entry) so a real breakdown can't run past
            # the structural level indefinitely before the 2-bar confirm catches it.
            capped_stop = fill * (1 - params.max_loss_pct) if direction == "long" else fill * (1 + params.max_loss_pct)
            stop_level = max(structural_stop, capped_stop) if direction == "long" else min(structural_stop, capped_stop)
            trade = Trade(
                entry_idx=t, entry_time=times[t], direction=direction,
                entry_price=fill, stop_price=stop_level, target_price=midpoint,
            )
            position = {
                "direction": direction, "entry_idx": t, "entry_price": fill,
                "stop_level": stop_level, "target": midpoint, "trade": trade,
                "trailing": False, "trail_stop": None, "best": fill,
            }
            confirm_streak, pending_direction = 0, None

    # close any still-open position at the last bar (mark-to-market, not a real fill)
    if position is not None:
        last = n - 1
        tr = position["trade"]
        tr.exit_idx, tr.exit_time = last, times[last]
        tr.exit_price, tr.exit_reason = closes[last], "eod_open"
        entry_fill = position["entry_price"]
        if position["direction"] == "long":
            pnl_pct = (tr.exit_price - entry_fill) / entry_fill - 2 * fee
        else:
            pnl_pct = (entry_fill - tr.exit_price) / entry_fill - 2 * fee
        risk_pct = abs(entry_fill - position["stop_level"]) / entry_fill
        tr.pnl_pct = pnl_pct
        tr.r_multiple = pnl_pct / risk_pct if risk_pct > 0 else 0.0
        trades.append(tr)
        equity[-1] = equity_val + pnl_pct

    equity_series = pd.Series(equity, index=df.index)
    return trades, equity_series
