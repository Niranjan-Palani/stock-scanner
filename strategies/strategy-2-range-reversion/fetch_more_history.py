"""
Extends cached 15min data further back in time using Twelve Data's date-range
params, then merges with the existing cache (dedup by timestamp, sorted).
"""
import argparse
import json
import os
import re
import time
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


def fetch_range(symbol, interval, start_date, end_date, outputsize=5000):
    url = (
        "https://api.twelvedata.com/time_series"
        f"?symbol={symbol}&interval={interval}&start_date={start_date}&end_date={end_date}"
        f"&outputsize={outputsize}&apikey={API_KEY}"
    )
    with urllib.request.urlopen(url) as resp:
        payload = json.loads(resp.read().decode())
    if payload.get("status") != "ok":
        print(f"  warning: no data for {symbol} in range: {payload}")
        return []
    return payload["values"]


def merge_into_cache(symbol, interval, new_values):
    path = os.path.join(DATA_DIR, f"{symbol}_{interval}.csv")
    existing = {}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            next(f)  # header
            for line in f:
                ts = line.split(",")[0]
                existing[ts] = line.strip()
    for r in new_values:
        existing[r["datetime"]] = f"{r['datetime']},{r['open']},{r['high']},{r['low']},{r['close']},{r['volume']}"
    rows = [existing[k] for k in sorted(existing.keys())]
    with open(path, "w", encoding="utf-8") as f:
        f.write("timestamp,open,high,low,close,volume\n")
        f.write("\n".join(rows) + "\n")
    return len(rows)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("symbols", nargs="+")
    ap.add_argument("--interval", default="15min")
    ap.add_argument("--start_date", required=True)
    ap.add_argument("--end_date", required=True)
    args = ap.parse_args()

    for i, sym in enumerate(args.symbols):
        print(f"fetching {sym} {args.start_date}..{args.end_date}...")
        values = fetch_range(sym, args.interval, args.start_date, args.end_date)
        if values:
            total = merge_into_cache(sym, args.interval, values)
            print(f"  merged {len(values)} new bars -> cache now has {total} total bars")
        if i < len(args.symbols) - 1:
            time.sleep(8)
