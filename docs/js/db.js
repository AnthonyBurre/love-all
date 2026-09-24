// DuckDB-WASM data layer: loads the shipped insights.duckdb once and exposes query(). The
// coverage tiers and the matchup panel read through it.
//
// The library is fetched from the CDN on first query rather than imported statically, so a
// failed fetch only affects the parts that need the database, not the draw.
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

// The serve_tendencies gates still ship in `meta` under serve_* keys — the n80 sample
// thresholds and the tour's own placement mix. Nothing on the site reads them: the sample
// gate is applied in the build as `reliable`, and the one figure the panel took from here,
// the recency window, is now per player on player_serve rather than the tour's largest.

// Where the charted tour sits on each figure the profile band prints (won point length,
// variety, the four shot-mix rates, return-winner rate), since none has a scale a reader
// already knows.
//
// Four numbers per metric: the quartiles are the band the figure is read against, and p5/p95
// are the axis it's drawn on (see figBand() in matchup.js). Cut in SQL, each over its own
// qualifying players (quantile_cont skips nulls per column).
//
// Cached as the promise, so two panels opening at once share one query.
let _spread = null;
export function tourSpread() {
  if (!_spread) _spread = loadSpread();
  return _spread;
}

// The columns a strip is cut over: FIGS `band` in matchup.js plus the rally length
// profileParts reads directly. The groundstroke square has no tour reference, so its rates
// aren't here. These are the file's own literals, so interpolating them into SQL is safe.
const SPREAD_COLS = [
  "bits", "won_rally_len", "ret_winner_rate",
  "slice_pct", "net_pct", "net_winner_pct", "net_err_pct",
];

async function loadSpread() {
  const out = { M: {}, W: {} };
  try {
    // Aliased by position, so a column name with anything awkward in it could never reach
    // the identifier: c3_lo is read back off the same index the name came from.
    const sel = SPREAD_COLS.map((c, i) =>
      `count(${c}) AS c${i}_n,
       quantile_cont(${c}, 0.25) AS c${i}_lo, quantile_cont(${c}, 0.75) AS c${i}_hi,
       quantile_cont(${c}, 0.05) AS c${i}_min, quantile_cont(${c}, 0.95) AS c${i}_max`);
    const rows = await query(
      `SELECT gender, ${sel.join(", ")} FROM player_summary GROUP BY gender`);
    for (const r of rows) {
      if (!out[r.gender]) continue;
      // A band needs a population behind it to be worth quoting. Below that the metric still
      // prints — it is the player's own number — it just goes without a tour to read it against.
      const band = (n, lo, hi, min, max) =>
        Number(n) >= 40 && lo != null && hi != null && min != null && max != null
          ? { lo: Number(lo), hi: Number(hi), min: Number(min), max: Number(max), n: Number(n) }
          : null;
      const g = {};
      SPREAD_COLS.forEach((c, i) => {
        g[c] = band(r[`c${i}_n`], r[`c${i}_lo`], r[`c${i}_hi`],
          r[`c${i}_min`], r[`c${i}_max`]);
      });
      out[r.gender] = g;
    }
  } catch (e) { /* stale insights db: the figures print without their tour band */ }
  return out;
}
