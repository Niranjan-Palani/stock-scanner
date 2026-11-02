const fs = require('fs');
const path = require('path');
const { execFile } = require('child_process');
const express = require('express');
const { getEconomicEvents, volatilityFlag } = require('./economic-events');

// --- tiny .env loader (no dependency needed) ---
const envPath = path.join(__dirname, '.env');
if (fs.existsSync(envPath)) {
  for (const line of fs.readFileSync(envPath, 'utf8').split('\n')) {
    const m = line.match(/^\s*([\w.-]+)\s*=\s*(.*)?\s*$/);
    if (m && !process.env[m[1]]) process.env[m[1]] = (m[2] || '').trim();
  }
}

const API_KEY = process.env.FINNHUB_API_KEY;
if (!API_KEY) {
  console.error('Missing FINNHUB_API_KEY in .env');
  process.exit(1);
}

const WATCHLIST = [
  'F','T','PLTR','SOFI','NIO','AAL','CCL','PBR','KGC','GRAB',
  'RIG','VALE','WBD','UAA','OPEN','CLSK','RIOT','MARA','AMCR','KVUE',
  'HBAN','KEY','CFG','RF','NCLH','UAL','DKNG','LYFT','PARA','SIRI'
];

const QUOTE_DELAY_MS = 1100;     // paces quote polling under Finnhub's 60/min free-tier limit
const STATIC_REFRESH_MS = 15 * 60 * 1000; // float/avg-volume refresh every 15 min
const PILLAR_REFRESH_EVERY_N_CYCLES = 5;  // today's-volume + news fetched only every 5th quote cycle per symbol, to stay under the rate limit

// Ross Cameron / Warrior Trading "Five Pillars" thresholds — see Obsidian note
// "Ross Cameron Micro Pullback Strategy" for the full rationale.
const PILLARS = {
  priceMin: 2,
  priceMax: 20,
  upBigPct: 25,        // already up this much on the day
  relVolMin: 5,         // today's volume vs. average volume
  floatMaxM: 20,        // shares available to trade, in millions (Finnhub profile2 float is already in millions)
  newsMaxHours: 24       // catalyst must be this fresh
};

const state = {
  quotes: {},   // sym -> { price, change, updatedAt }
  static: {},   // sym -> { name, float, vol10d, vol3m }
  pillars: {},  // sym -> { todayVolume, relVol, newsHeadline, newsAgeHours }
  cycleCount: {}, // sym -> quote-loop cycle counter, used to pace pillar fetches
  lastQuoteCycle: null,
  lastStaticCycle: null,
  economicEvents: { events: [], source: null },
  lastEconomicCycle: null
};

const ECONOMIC_REFRESH_MS = 30 * 60 * 1000; // calendar doesn't change minute to minute

async function economicLoop() {
  try {
    state.economicEvents = await getEconomicEvents();
    state.lastEconomicCycle = Date.now();
    console.log(`[economic] refreshed (${state.economicEvents.source}) ${new Date().toLocaleTimeString()}`);
  } catch (e) {
    console.error('economic events fetch failed', e.message);
  }
  setTimeout(economicLoop, ECONOMIC_REFRESH_MS);
}

function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

async function fetchJSON(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error('http ' + r.status);
  return r.json();
}

// Today's cumulative volume, used to compute real relative volume (pillar 3).
// Note: Finnhub's free tier restricts /stock/candle for some accounts — this
// fails gracefully (relVol just stays null and that pillar won't pass) rather
// than breaking the rest of the scan.
async function fetchTodayVolume(sym) {
  const to = Math.floor(Date.now() / 1000);
  const from = to - 5 * 24 * 3600;
  const c = await fetchJSON(`https://finnhub.io/api/v1/stock/candle?symbol=${sym}&resolution=D&from=${from}&to=${to}&token=${API_KEY}`);
  if (c.s !== 'ok' || !c.v || !c.v.length) return null;
  return c.v[c.v.length - 1];
}

// Freshest news headline today, used for the news-catalyst pillar (pillar 2).
async function fetchLatestNews(sym) {
  const today = new Date().toISOString().slice(0, 10);
  const news = await fetchJSON(`https://finnhub.io/api/v1/company-news?symbol=${sym}&from=${today}&to=${today}&token=${API_KEY}`);
  if (!Array.isArray(news) || !news.length) return null;
  const latest = news.reduce((a, b) => (b.datetime > a.datetime ? b : a));
  return { headline: latest.headline, ageHours: (Date.now() / 1000 - latest.datetime) / 3600 };
}

// Fetched independently (not one try/catch) because Finnhub's free tier commonly
// blocks /stock/candle for US equities (403) while still allowing /company-news —
// a candle failure shouldn't also cost us the news pillar.
async function refreshPillarData(sym) {
  let todayVolume = null;
  try {
    todayVolume = await fetchTodayVolume(sym);
  } catch (e) {
    console.error('today-volume fetch failed', sym, e.message);
  }
  await sleep(QUOTE_DELAY_MS);

  let news = null;
  try {
    news = await fetchLatestNews(sym);
  } catch (e) {
    console.error('news fetch failed', sym, e.message);
  }

  const s = state.static[sym] || {};
  const avgVol = s.vol10d != null ? s.vol10d : s.vol3m;
  state.pillars[sym] = {
    todayVolume,
    relVol: (todayVolume != null && avgVol) ? todayVolume / avgVol : null,
    newsHeadline: news ? news.headline : null,
    newsAgeHours: news ? news.ageHours : null
  };
}

async function quoteLoop() {
  for (const sym of WATCHLIST) {
    try {
      const q = await fetchJSON(`https://finnhub.io/api/v1/quote?symbol=${sym}&token=${API_KEY}`);
      state.quotes[sym] = { price: q.c, change: q.dp, updatedAt: Date.now() };
    } catch (e) {
      console.error('quote fetch failed', sym, e.message);
    }
    await sleep(QUOTE_DELAY_MS);

    state.cycleCount[sym] = (state.cycleCount[sym] || 0) + 1;
    if (state.cycleCount[sym] % PILLAR_REFRESH_EVERY_N_CYCLES === 0) {
      await refreshPillarData(sym);
      await sleep(QUOTE_DELAY_MS);
    }
  }
  state.lastQuoteCycle = Date.now();
  console.log(`[quotes] cycle complete ${new Date().toLocaleTimeString()}`);
  quoteLoop(); // immediately start next cycle, paced by the delays above
}

async function staticLoop() {
  for (const sym of WATCHLIST) {
    try {
      const [profile, metric] = await Promise.all([
        fetchJSON(`https://finnhub.io/api/v1/stock/profile2?symbol=${sym}&token=${API_KEY}`),
        fetchJSON(`https://finnhub.io/api/v1/stock/metric?symbol=${sym}&metric=all&token=${API_KEY}`)
      ]);
      state.static[sym] = {
        name: profile.name || sym,
        float: profile.floatingShare || profile.shareOutstanding || null,
        vol10d: metric.metric ? metric.metric['10DayAverageTradingVolume'] : null,
        vol3m: metric.metric ? metric.metric['3MonthAverageTradingVolume'] : null
      };
    } catch (e) {
      console.error('static fetch failed', sym, e.message);
    }
    await sleep(QUOTE_DELAY_MS);
  }
  state.lastStaticCycle = Date.now();
  console.log(`[static] refreshed ${new Date().toLocaleTimeString()}`);
  setTimeout(staticLoop, STATIC_REFRESH_MS);
}

quoteLoop();
staticLoop();
economicLoop();

const app = express();
app.use(express.static(path.join(__dirname, 'public')));

app.get('/api/watchlist', (req, res) => {
  const rows = WATCHLIST.map(sym => {
    const q = state.quotes[sym] || {};
    const s = state.static[sym] || {};
    const p = state.pillars[sym] || {};
    const vol = s.vol3m != null ? s.vol3m : s.vol10d;
    const ratio = (vol != null && s.float) ? vol / s.float : null;

    const pillars = {
      priceRange: q.price != null && q.price >= PILLARS.priceMin && q.price <= PILLARS.priceMax,
      upBig: q.change != null && q.change >= PILLARS.upBigPct,
      relVolOk: p.relVol != null && p.relVol >= PILLARS.relVolMin,
      lowFloat: s.float != null && s.float <= PILLARS.floatMaxM,
      hasNews: p.newsAgeHours != null && p.newsAgeHours <= PILLARS.newsMaxHours
    };
    const pillarsPassed = Object.values(pillars).filter(Boolean).length;

    return {
      sym, name: s.name || sym,
      price: q.price ?? null, change: q.change ?? null,
      vol10d: s.vol10d ?? null, vol3m: s.vol3m ?? null,
      float: s.float ?? null, ratio,
      relVol: p.relVol ?? null,
      newsHeadline: p.newsHeadline ?? null,
      newsAgeHours: p.newsAgeHours ?? null,
      pillars, pillarsPassed
    };
  });

  rows.sort((a, b) => b.pillarsPassed - a.pillarsPassed || (b.relVol || 0) - (a.relVol || 0));

  res.json({
    rows,
    pillarThresholds: PILLARS,
    lastQuoteCycle: state.lastQuoteCycle,
    lastStaticCycle: state.lastStaticCycle,
    economicVolatility: volatilityFlag(state.economicEvents.events)
  });
});

app.get('/api/economic-events', (req, res) => {
  res.json({
    ...state.economicEvents,
    lastEconomicCycle: state.lastEconomicCycle,
    volatility: volatilityFlag(state.economicEvents.events)
  });
});

// --- Qlib ranking snapshot (fixed paths only, no user input reaches execFile) ---
const QLIB_RANK_JSON = path.join(__dirname, 'data', 'qlib_rank.json');
const QLIB_PYTHON = path.join(process.env.USERPROFILE || require('os').homedir(), 'source', 'ai-quant', 'qlib-env', 'Scripts', 'python.exe');
const QLIB_SCRIPT = path.join(process.env.USERPROFILE || require('os').homedir(), 'source', 'ai-quant', 'scripts', 'qlib_rank.py');

app.get('/api/qlib-rank', (req, res) => {
  if (!fs.existsSync(QLIB_RANK_JSON)) {
    return res.status(404).json({ error: 'No ranking generated yet. Click Refresh.' });
  }
  res.json(JSON.parse(fs.readFileSync(QLIB_RANK_JSON, 'utf8')));
});

app.post('/api/qlib-rank/refresh', (req, res) => {
  execFile(QLIB_PYTHON, [QLIB_SCRIPT], { timeout: 60000 }, (err, stdout, stderr) => {
    if (err) {
      console.error('[qlib-rank] refresh failed', stderr || err.message);
      return res.status(500).json({ error: 'Refresh failed', detail: stderr || err.message });
    }
    if (!fs.existsSync(QLIB_RANK_JSON)) {
      return res.status(500).json({ error: 'Script ran but produced no output' });
    }
    res.json(JSON.parse(fs.readFileSync(QLIB_RANK_JSON, 'utf8')));
  });
});

const PORT = 3300;
app.listen(PORT, () => {
  console.log(`\nTrading dashboard running: http://localhost:${PORT}\n(leave this window open — closing it stops the live updates)\n`);
});
