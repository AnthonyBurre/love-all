// DuckDB-WASM data layer — loads the shipped insights.duckdb once and exposes query().
// The whole site (coverage badges, matchup insights) reads through this.
import * as duckdb from "https://cdn.jsdelivr.net/npm/@duckdb/duckdb-wasm@1.29.0/+esm";

let _conn = null;
let _initing = null;

async function _init() {
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
  if (!_initing) _initing = _init();
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
