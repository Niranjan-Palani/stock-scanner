# Trading Dashboard

> Educational project. Not financial advice; it does not place trades.

A local, single-user live scanner implementing Ross Cameron's (Warrior Trading)
momentum micro-pullback day-trading strategy — the "Five Pillars" — plus a
market-wide economic-event (macro catalyst) overlay. It's decision support only:
it surfaces candidates, you still do chart/MACD/volume/Level-2 confirmation
before entering anything.

## Architecture

```
Economic Event ─┐
                 ├─► Signal Engine ─► Dashboard
Market Data ─────┘
```

- **Economic Event** (`economic-events.js`) — macro calendar (CPI, FOMC, NFP, etc.).
  Currently serves **mock data**; swaps to a live provider once an API key is set
  (see "API keys" below). Produces a market-wide "volatility catalyst" flag.
- **Market Data** (`server.js` — `quoteLoop`, `staticLoop`) — polls Finnhub for
  live quotes, float, and average volume on a 30-symbol watchlist, paced to stay
  under the free-tier rate limit (1 req/1.1s, ~54/min).
- **Signal Engine** (`server.js` — `/api/watchlist` handler) — scores each symbol
  against the Five Pillars (price range, % up today, relative volume, float,
  news freshness) and ranks by pillars passed.
- **Dashboard** (`public/index.html`) — polls the server every 5s (watchlist) /
  60s (economic events) and renders the Top-5 cards, full watchlist table, and
  economic-calendar panel. Plain HTML/CSS/JS, no build step. A separate page
  (`public/qlib-rank.html`) shows output from an independent Python/Qlib ranking
  script.

## Installation

```bash
cd trading-dashboard
npm install
```

(Dependencies: just `express`. Node 18+ is required — the app uses the built-in
`fetch`.)

## Configuration / API keys

Copy `.env.example` to `.env` in the project root and fill in your keys (`.env` is git-ignored, so keys never get committed):

```
FINNHUB_API_KEY=your_finnhub_key_here

# Optional — enables the live economic calendar instead of mock data.
# Leave unset to keep running on mock data (default).
ECONOMIC_CALENDAR_API_KEY=your_key_here
```

- **FINNHUB_API_KEY** (required) — get a free key at https://finnhub.io. Free-tier
  caveats: `/stock/candle` (today's volume, used for real relative volume) and
  `/company-news` are sometimes blocked (403) on free keys — those pillars just
  won't pass for affected symbols rather than crashing anything.
- **ECONOMIC_CALENDAR_API_KEY** (optional, currently unused — blocked) — once you
  pick a macro-calendar provider (Financial Modeling Prep, TradingEconomics, or
  Finnhub's own `/calendar/economic` if your plan covers it), set this and
  implement `fetchLiveEvents()` in `economic-events.js` to match the existing
  mock event shape. See `TODO.md` → NEXT for the exact steps.

## Running the system

```bash
npm start
```

Then open http://localhost:3300. Leave the terminal window open — closing it
stops the live-update loops. Ctrl+C to stop.

## Dashboard

- **Economic calendar panel** — this week's high/medium-impact US releases,
  with a ⚠ banner when a high-impact event is within 6 hours (mock data is
  labeled with a visible "MOCK DATA" badge).
- **Top 5 setups** — highest-scoring symbols currently in your price filter.
- **Full watchlist table** — every symbol, sortable visually by pillars passed.
- `/qlib-rank.html` — separate factor-ranking view fed by the Python/Qlib script
  under `~/source/ai-quant` (click Refresh to re-run it).

## Testing

No automated test suite yet (small single-file server). Manual smoke test:

```bash
node -e "require('./economic-events').getEconomicEvents().then(r=>console.log(r))"
npm start
curl http://localhost:3300/api/watchlist
curl http://localhost:3300/api/economic-events
```

All three should return JSON without errors; the dashboard at
http://localhost:3300 should show live-updating prices within ~5s and the
economic-calendar panel within ~1s of load.

## Backtesting

Not implemented for this scanner itself (it's a live decision-support tool, not
a backtested strategy). The separate Qlib pipeline under `~/source/ai-quant`
handles historical factor ranking — see that project for backtesting.

## Troubleshooting

- **"Missing FINNHUB_API_KEY in .env"** — create `.env` per "Configuration" above.
- **Prices never update / "server unreachable"** — check the terminal running
  `npm start` for fetch errors; Finnhub may be rate-limiting (free tier is
  60/min) or down.
- **Rel Vol / News columns stuck at "—"** — likely a free-tier 403 on
  `/stock/candle` or `/company-news`; see "API keys" above. Not a bug — that
  pillar just won't pass for those symbols.
- **Economic panel shows "MOCK DATA"** — expected until `ECONOMIC_CALENDAR_API_KEY`
  is set and `fetchLiveEvents()` is implemented (see `TODO.md`).
- **Qlib refresh fails** — confirm `~/source/ai-quant/qlib-env/Scripts/python.exe`
  and `~/source/ai-quant/scripts/qlib_rank.py` exist; that's a separate project.

## Strategy research (`strategies/`)

Python backtests for two strategies (micro-pullback and range reversion). Market data is not included in the repo: run `fetch_data.py` with `TWELVE_DATA_API_KEY` set in `.env` to download it into `strategies/strategy-2-range-reversion/data/`.
