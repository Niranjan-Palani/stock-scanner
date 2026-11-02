# Trading Dashboard — TODO

## DONE
- Market data: Finnhub quote polling for 30-symbol watchlist, rate-limit paced (`server.js`)
- Market data: float / avg-volume / today's-volume / news refresh loops
- Signal engine: Ross Cameron "Five Pillars" scoring (`PILLARS` thresholds in `server.js`)
- Signal engine: pillar-count ranking + sort
- Dashboard: live-updating watchlist table + "Top 5 setups" cards (`public/index.html`)
- Dashboard: Qlib factor-ranking panel (`public/qlib-rank.html`, separate Python pipeline)
- **Economic Event module (new):** `economic-events.js` — mock macro calendar (CPI, FOMC, jobless
  claims, PPI, NFP, retail sales), `/api/economic-events` endpoint, market-wide
  "volatility catalyst" flag folded into `/api/watchlist`, dashboard panel showing
  this week's releases with a visible "MOCK DATA" badge until a real feed is wired up

## IN PROGRESS
- None currently — economic events slice is feature-complete on mock data.

## BLOCKED
- **Live economic calendar data** — needs an API key for a macro-calendar provider
  (e.g. Financial Modeling Prep `/v3/economic_calendar`, TradingEconomics, or Finnhub's
  `/calendar/economic` if your plan includes it). Until then `economic-events.js` serves
  deterministic mock data. See README "API keys" for exactly what to set.
- **Finnhub `/stock/candle` (today's volume → real relative volume)** — many free-tier
  keys 403 on this endpoint; `relVol` silently stays null for those symbols and that
  pillar just won't pass. Needs a paid/upgraded Finnhub key to fully work.
- **Finnhub `/company-news` reliability** — same free-tier caveat; news pillar can be
  sparse depending on plan.

## NEXT (after live economic-calendar key is provided)
1. Implement `fetchLiveEvents()` in `economic-events.js` against the real provider,
   matching the existing mock shape (`{id, name, country, impact, time, forecast,
   previous, actual}`) — no changes needed in `server.js` or the dashboard.
2. Consider per-symbol event sensitivity (e.g. don't flag volatility for a biotech
   on a pure macro-rates day) if the watchlist grows into sector-specific names.
3. Add a toast/sound alert when a high-impact event flips from upcoming to "live"
   (actual value populated), since that's often when volume spikes hit the scanner.
4. Persist economic-event history (currently in-memory only) if you want to backtest
   whether the "volatility flag" actually correlated with better/worse Five Pillars hits.
