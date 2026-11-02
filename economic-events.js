// --- Economic calendar module ---
// Goal: surface macro events (CPI, FOMC, jobs report, etc.) that tend to spike
// volatility/volume market-wide, so the signal engine can flag "today is a
// high-volatility catalyst day" independent of any single symbol's news.
//
// Real provider: not wired up yet — needs an API key (see TODO.md / README.md
// "Blocked by credentials" section, e.g. FMP's /v3/economic_calendar or
// TradingEconomics). Until a key is supplied, this module serves deterministic
// MOCK data shaped like the real response so the rest of the pipeline
// (server -> signal engine -> dashboard) can be built and tested end-to-end
// now, then swapped to live data with no changes needed above this file.

const ECONOMIC_CALENDAR_API_KEY = process.env.ECONOMIC_CALENDAR_API_KEY || null;

// Mock calendar: a realistic week of high-impact US macro releases.
// Times are UTC hours on their given day, impact is 'high' | 'medium' | 'low'.
function buildMockEvents() {
  const now = new Date();
  const today = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate()));
  const day = (offsetDays, hourUTC, minuteUTC = 30) => {
    const d = new Date(today);
    d.setUTCDate(d.getUTCDate() + offsetDays);
    d.setUTCHours(hourUTC, minuteUTC, 0, 0);
    return d.getTime();
  };

  return [
    { id: 'cpi', name: 'CPI (Consumer Price Index) m/m', country: 'US', impact: 'high', time: day(0, 12, 30), forecast: '0.2%', previous: '0.2%', actual: null },
    { id: 'fomc', name: 'FOMC Statement & Rate Decision', country: 'US', impact: 'high', time: day(1, 18, 0), forecast: '4.50%', previous: '4.50%', actual: null },
    { id: 'jobless', name: 'Initial Jobless Claims', country: 'US', impact: 'medium', time: day(2, 12, 30), forecast: '220K', previous: '215K', actual: null },
    { id: 'nfp', name: 'Non-Farm Payrolls', country: 'US', impact: 'high', time: day(4, 12, 30), forecast: '180K', previous: '175K', actual: null },
    { id: 'ppi', name: 'PPI (Producer Price Index) m/m', country: 'US', impact: 'medium', time: day(3, 12, 30), forecast: '0.1%', previous: '0.3%', actual: null },
    { id: 'retail', name: 'Retail Sales m/m', country: 'US', impact: 'medium', time: day(-1, 12, 30), forecast: '0.3%', previous: '0.4%', actual: '0.6%' }
  ];
}

// Real-provider stub — fill in once ECONOMIC_CALENDAR_API_KEY is set.
// Keep the same shape as buildMockEvents() so nothing downstream has to change.
async function fetchLiveEvents() {
  throw new Error('Live economic calendar not configured — set ECONOMIC_CALENDAR_API_KEY');
}

async function getEconomicEvents() {
  if (ECONOMIC_CALENDAR_API_KEY) {
    try {
      return { events: await fetchLiveEvents(), source: 'live' };
    } catch (e) {
      console.error('[economic-events] live fetch failed, falling back to mock:', e.message);
    }
  }
  return { events: buildMockEvents(), source: 'mock' };
}

// Signal-engine hook: is there a high-impact event today, or within the next
// N hours? Used to raise a market-wide "volatility catalyst" flag alongside
// each symbol's own Five Pillars score.
function volatilityFlag(events, withinHours = 6) {
  const now = Date.now();
  const windowMs = withinHours * 3600 * 1000;
  const upcoming = events.filter(e =>
    e.impact === 'high' && e.time >= now - 3600 * 1000 && e.time <= now + windowMs
  );
  return {
    active: upcoming.length > 0,
    events: upcoming.map(e => ({ name: e.name, time: e.time }))
  };
}

module.exports = { getEconomicEvents, volatilityFlag };
