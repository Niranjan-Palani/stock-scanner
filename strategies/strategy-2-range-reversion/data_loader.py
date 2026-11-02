"""
Data loading contract for the backtester. Swap `load_bars` for your own
source as long as it returns a DataFrame with this exact shape:

    index: pandas.DatetimeIndex, tz-naive, exchange-local (America/New_York), ascending
    columns: open, high, low, close, volume  (all float64 except volume=int64)

Regular-trading-hours filtering (9:30-16:00 ET) happens here, once, so every
downstream module can assume clean intraday bars with no overnight rows.
"""
import os
import pandas as pd

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")


def load_bars(symbol: str, interval: str = "15min", rth_only: bool = True) -> pd.DataFrame:
    """
    Loads cached CSV bars for `symbol` (produced by fetch_data.py).
    Replace the body of this function to point at your own data source —
    the rest of the engine only depends on the return shape documented above.
    """
    path = os.path.join(DATA_DIR, f"{symbol}_{interval}.csv")
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"No cached data at {path}. Run: python fetch_data.py {symbol} --interval {interval}"
        )
    df = pd.read_csv(path, parse_dates=["timestamp"])
    df = df.set_index("timestamp").sort_index()
    df["volume"] = df["volume"].astype("int64")
    for col in ("open", "high", "low", "close"):
        df[col] = df[col].astype("float64")

    if rth_only:
        df = df.between_time("09:30", "16:00")

    # Tag each bar with a session date so the level detector can reset window
    # boundaries cleanly at the open and avoid straddling logic across gaps.
    df["session"] = df.index.date
    return df


def train_test_split(df: pd.DataFrame, train_frac: float = 0.7) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Chronological split by session date — never shuffles, never leaks future bars into train."""
    sessions = sorted(df["session"].unique())
    cut = int(len(sessions) * train_frac)
    train_sessions = set(sessions[:cut])
    train = df[df["session"].isin(train_sessions)]
    test = df[~df["session"].isin(train_sessions)]
    return train, test
