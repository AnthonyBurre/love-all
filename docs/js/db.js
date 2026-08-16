// DuckDB-WASM data layer — loads the shipped insights.duckdb once and exposes query().
// The whole site (coverage badges, matchup insights) reads through this.
//
// The library is the site's one cross-origin dependency, and it is fetched on demand rather
// than at module scope. A static `import` of a CDN URL is part of the module graph: if that
// fetch fails — offline, blocked, CDN down — every module that transitively imports this one
// fails to evaluate along with it. app.js imports this file, so a failure there took down the
// draw as well, and the page sat on "Loading current draws…" with the whole bracket already
// on disk in ./data/brackets.json, never asked for. Deferred to the first query, the failure
// is contained to the parts that genuinely need a database: the tier shading and the panel.
const DUCKDB_ESM = "https://cdn.jsdelivr.net/npm/@duckdb/duckdb-wasm@1.29.0/+esm";

let _conn = null;
let _initing = null;

async function _init() {
  const duckdb = await import(/* @vite-ignore */ DUCKDB_ESM);
  const bundles = duckdb.getJsDelivrBundles();
  const bundle = await duckdb.selectBundle(bundles);
  // The bundle worker is cross-origin (CDN); wrap it in a same-origin Blob so the
  // browser will construct the Worker (works locally and on GitHub Pages alike).
  const workerUrl = URL.createObjectURL(
    new Blob([`importScripts("${bundle.mainWorker}");`], { type: "text/javascript" }));
  const worker = new Worker(workerUrl);
  // VoidLogger, not ConsoleLogger: duckdb-wasm's console logger reports every
  // instantiation and query event as a bare object, so a page load left a dozen
  // "[object Object]" lines in the console with nothing else to read them against.
  // Anything this layer actually needs to say, it says at the catch sites.
  const db = new duckdb.AsyncDuckDB(new duckdb.VoidLogger(), worker);
  await db.instantiate(bundle.mainModule, bundle.pthreadWorker);
  URL.revokeObjectURL(workerUrl);
  const buf = new Uint8Array(await (await fetch("./data/insights.duckdb")).arrayBuffer());
  await db.registerFileBuffer("insights.duckdb", buf);
  const conn = await db.connect();
  await conn.query("ATTACH 'insights.duckdb' AS ins (READ_ONLY)");
  await conn.query("USE ins");
  _conn = conn;
  return conn;
}

export async function initDB() {
  if (_conn) return _conn;
  // The in-flight promise is cached so one page load instantiates one database, and it is
  // dropped again if that attempt fails. The usual reason it fails is a network that wasn't
  // there, and a network that wasn't there is often there a minute later — held, a rejected
  // promise would answer every panel opened for the rest of the session with the failure of
  // the first one.
  if (!_initing) _initing = _init().catch((e) => { _initing = null; throw e; });
  return _initing;
}

// Run SQL; params (if any) use a prepared statement so names with quotes/accents are safe.
export async function query(sql, params = []) {
  const conn = await initDB();
  if (params.length) {
    const stmt = await conn.prepare(sql);
    const rows = (await stmt.query(...params)).toArray().map((r) => r.toJSON());
    await stmt.close();
    return rows;
  }
  return (await conn.query(sql)).toArray().map((r) => r.toJSON());
}

// Serve-placement gates and tour baselines, keyed by gender then by what they are
// (n80_wide, tour_deuce_t, …). These are thresholds the serve_tendencies experiment
// owns — how much charted data a placement share needs before it means anything, and
// what the tour does — so the panel reads them rather than carrying its own copy that
// would go stale the next time the experiment is rerun.
export async function serveGates() {
  const out = { M: {}, W: {} };
  try {
    const rows = await query("SELECT key, value FROM meta WHERE key LIKE 'serve_%'");
    for (const r of rows) {
      const m = String(r.key).match(/^serve_(.+)_([MW])$/);
      if (m) out[m[2]][m[1]] = r.value;
    }
  } catch (e) { /* stale insights db: the serve section stays hidden */ }
  return out;
}

// Where the charted tour sits on the three figures the profile band prints: rally length in
// strokes, variety in bits, and shot selection as a σ in percentage points. None of the three
// has a scale a reader arrives knowing, so each is printed against the band the middle half of
// that tour occupies — which is what tells you whether 3.2 bits is ordinary or remarkable.
//
// Rally length replaced the 0-100 shot-quality score here, and the band is the reason the
// swap is not a downgrade: that score was an exponential map of conceded win probability that
// correlated -0.84 with rally length and was 91% predicted by the style fingerprint, so a
// reader comparing two players on it was mostly comparing their rally lengths through a
// scale that hid what it was doing. This says the same thing in the unit it is actually in.
//
// The quartiles are cut in SQL rather than by shipping the players down and cutting them here.
// This used to send every charted player's coordinates to draw a crowd of them behind the two
// in the match; with the crowd gone, that is a couple of hundred rows fetched per tour to
// derive four numbers from.
//
// Each metric is measured over its own qualifying players rather than over the players who
// have both — they are separate experiments with separate thresholds, and intersecting them
// would quote a band for one metric computed off the other's cut. quantile_cont skips nulls
// per column, so the two bands are independent by construction.
//
// Cached as the promise rather than the value, so two panels opening at once share one
// query — the panel awaits this on every open.
let _spread = null;
export function tourSpread() {
  if (!_spread) _spread = loadSpread();
  return _spread;
}

async function loadSpread() {
  const out = { M: {}, W: {} };
  try {
    const rows = await query(
      `SELECT gender,
         count(bits) AS n_bits, count(avg_rally_len) AS n_rally,
         quantile_cont(bits, 0.25) AS b_lo, quantile_cont(bits, 0.75) AS b_hi,
         quantile_cont(avg_rally_len, 0.25) AS r_lo,
         quantile_cont(avg_rally_len, 0.75) AS r_hi
       FROM player_summary GROUP BY gender`);
    for (const r of rows) {
      if (!out[r.gender]) continue;
      // A band needs a population behind it to be worth quoting. Below that the metric still
      // prints — it is the player's own number — it just goes without a tour to read it against.
      const band = (n, lo, hi) => Number(n) >= 40 && lo != null && hi != null
        ? { lo: Number(lo), hi: Number(hi), n: Number(n) } : null;
      out[r.gender] = {
        bits: band(r.n_bits, r.b_lo, r.b_hi),
        avg_rally_len: band(r.n_rally, r.r_lo, r.r_hi),
      };
    }
  } catch (e) { /* stale insights db: the figures print without their tour band */ }
  return out;
}

// League mean serve-win rates (for the matchup strength combine), keyed by gender.
// Read by prefix rather than by testing for "mu_M" and treating everything else as the
// women's value: `meta` is a general key/value table, so the first non-mu row added to it
// would have become mu.W and skewed every women's win probability without erroring.
export async function leagueMu() {
  const rows = await query("SELECT key, value FROM meta");
  const mu = {};
  for (const r of rows) {
    const key = String(r.key);
    if (key.startsWith("mu_")) mu[key.slice(3)] = r.value;
  }
  return mu;
}
