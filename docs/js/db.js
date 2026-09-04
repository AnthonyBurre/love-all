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

// The serve_tendencies gates still ship in `meta` under serve_* keys — the n80 sample
// thresholds and the tour's own placement mix. Nothing on the site reads them: the sample
// gate is applied in the build as `reliable`, and the one figure the panel took from here,
// the recency window, is now per player on player_serve rather than the tour's largest.

// Where the charted tour sits on the figures the profile band prints: the length of the points
// a player wins, the variety of their shot choices, and the eight rates of their shot mix.
// None has a scale a reader arrives knowing, so each is drawn against
// the tour it belongs to — which is what tells you whether 3.2 bits is ordinary or remarkable.
// A percentage looks like it needs no scale and needs one most: 4.1% of strokes played at the
// net is a tour-median baseliner and 6.9% is Federer.
//
// Four numbers per metric, not two. The quartiles are the band the middle half of the tour
// occupies, and they are what the figure is read against; the 5th and 95th percentiles are the
// axis that band is drawn on, because a strip that ran only from p25 to p75 would have no room
// left for the half of the tour that falls outside it and every such player would pile up on an
// end. Ends rather than the true min and max, which are single players and would spend most of
// the strip on ground nobody else stands on; a player past either end is drawn at it and says
// so — see figBand() in matchup.js.
//
// Rally length replaced the 0-100 shot-quality score here, and the band is the reason the
// swap is not a downgrade: that score was an exponential map of conceded win probability that
// correlated -0.84 with rally length and was 91% predicted by the style fingerprint, so a
// reader comparing two players on it was mostly comparing their rally lengths through a
// scale that hid what it was doing. This says the same thing in the unit it is actually in.
//
// The quartiles are cut in SQL rather than by shipping the players down and cutting them here.
// Shipping them would fetch a couple of hundred rows per tour to derive four numbers from.
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

// The columns a strip is cut over, named once and turned into SQL below. A list rather than
// ten hand-written quartile pairs: the query is the same four quantiles and a count per
// column, and written out longhand a column added to the panel meant editing the SELECT, the
// aliases and the reader in three places that could each be got wrong on their own.
//
// The names are this file's own literals, never anything a visitor supplies, so interpolating
// them into the SQL is safe.
const SPREAD_COLS = [
  "bits", "won_rally_len", "ace_rate", "ret_winner_rate",
  "fh_share", "fh_winner_pct", "fh_err_pct",
  "bh_share", "bh_winner_pct", "bh_err_pct",
  "slice_pct",
  "net_pct", "net_winner_pct", "net_err_pct",
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
