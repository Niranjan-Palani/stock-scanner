"""
Filters a candidate list of small-cap tickers down to names that pass the
"low float" Five Pillar (<20M shares) using Finnhub's profile2 endpoint
(same API the live dashboard already uses).
"""
import json
import os
import re
import sys
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
API_KEY = os.environ.get("FINNHUB_API_KEY")
if not API_KEY:
    raise SystemExit("FINNHUB_API_KEY is not set. Add it to .env (see README).")
FLOAT_MAX_M = 20

# Commonly-cited small-cap/low-float momentum names (not the original mega-cap
# watchlist) — candidates only, still need float verification per-symbol below.
CANDIDATES = [
    'ATER', 'MULN', 'CENN', 'IMPP', 'TOP', 'NAK', 'RSLS', 'PHUN', 'KOSS',
    'GNS', 'SAVA', 'BENF', 'HUBC', 'TIVC', 'GREE', 'SOS', 'ADTX', 'INVO',
    'BTAI', 'APDN', 'SNTI', 'VERB', 'WISA', 'ELTP', 'ONCY',
]


def fetch_float(sym: str):
    url = f"https://finnhub.io/api/v1/stock/profile2?symbol={sym}&token={API_KEY}"
    with urllib.request.urlopen(url) as resp:
        payload = json.loads(resp.read().decode())
    return payload.get("floatingShare") or payload.get("shareOutstanding"), payload.get("name")


def main():
    watchlist = sys.argv[1:] if len(sys.argv) > 1 else CANDIDATES
    results = {}
    for sym in watchlist:
        try:
            fl, name = fetch_float(sym)
        except Exception as e:
            print(f"{sym}: fetch failed ({e})")
            fl, name = None, None
        results[sym] = fl
        print(f"{sym} ({name}): float = {fl}M" if fl is not None else f"{sym}: no float data")
        time.sleep(1.1)

    passing = [s for s, fl in results.items() if fl is not None and fl <= FLOAT_MAX_M]
    print(f"\n{len(passing)}/{len(watchlist)} pass float <= {FLOAT_MAX_M}M: {passing}")

    out_path = os.path.join(os.path.dirname(__file__), "output", "float_filter.json")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w") as f:
        json.dump({"float_millions": results, "passing_low_float": passing}, f, indent=2)
    print(f"written to {out_path}")


if __name__ == "__main__":
    main()
