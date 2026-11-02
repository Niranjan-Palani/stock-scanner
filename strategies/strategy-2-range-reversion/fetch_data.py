"""
Pulls historical intraday bars from Twelve Data and caches them as CSV so the
backtester/optimizer never has to hit the API during a run (free tier is
rate-limited to 8 req/min / 800 req/day).

Usage:
    python fetch_data.py AAPL MSFT SOFI F --interval 15min --bars 5000
"""
import argparse
import os
import re
import time
import json
import urllib.request


def _load_env():
    """Read KEY=value lines from the project-root .env (same file server.js uses)."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".env")
    if os.path.exists(path):
        for line in open(path, encoding="utf-8"):
            m = re.match(r"^\s*([\w.-]+)\s*=\s*(.*?)\s*$", line)
            if m and m.group(1) not in os.environ:
                os.environ[m.group(1)] = m.group(2)


_load_env()
API_KEY = os.environ.get("TWELVE_DATA_API_KEY")
if not API_KEY:
    raise SystemExit("TWELVE_DATA_API_KEY is not set. Add it to .env (see README).")
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")


def fetch_symbol(symbol: str, interval: str, outputsize: int) -> list[dict]:
    url = (
        "https://api.twelvedata.com/time_series"
        f"?symbol={symbol}&interval={interval}&outputsize={outputsize}&apikey={API_KEY}"
    )
    with urllib.request.urlopen(url) as resp:
        payload = json.loads(resp.read().decode())
    if payload.get("status") != "ok":
        raise RuntimeError(f"Twelve Data error for {symbol}: {payload}")
    return payload["values"]


def save_csv(symbol: str, interval: str, values: list[dict]) -> str:
    os.makedirs(DATA_DIR, exist_ok=True)
    path = os.path.join(DATA_DIR, f"{symbol}_{interval}.csv")
    # Twelve Data returns newest-first; write oldest-first for easy chronological reads.
    rows = list(reversed(values))
    with open(path, "w", encoding="utf-8") as f:
        f.write("timestamp,open,high,low,close,volume\n")
        for r in rows:
            f.write(f"{r['datetime']},{r['open']},{r['high']},{r['low']},{r['close']},{r['volume']}\n")
    return path


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("symbols", nargs="+")
    ap.add_argument("--interval", default="15min")
    ap.add_argument("--bars", type=int, default=5000)
    args = ap.parse_args()

    for i, sym in enumerate(args.symbols):
        print(f"fetching {sym} ({args.interval}, {args.bars} bars)...")
        values = fetch_symbol(sym, args.interval, args.bars)
        path = save_csv(sym, args.interval, values)
        print(f"  saved {len(values)} bars -> {path}")
        if i < len(args.symbols) - 1:
            time.sleep(8)  # stay well under the 8 req/min free-tier limit
