// The matchup drawer: a card per player, and on a charted match the experimental win
// probability through it, all queried from insights.duckdb via DuckDB-WASM.
import { query, tourSpread } from "./db.js";
import { patternSvg, pairSvg, retSvg, shotLine } from "./court.js";
import { dayLong } from "./schedule.js";

const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const CHART_GUIDE =
  "https://www.tennisabstract.com/blog/2015/09/23/the-match-charting-project-quick-start-guide/";
const last = (name) => String(name || "").split(" ").slice(-1)[0];
// One decimal, except at the two ends where that decimal is always a zero and says nothing
// it hasn't already: a rate that rounds to the top prints "100%", and one that rounds to
// nothing prints a bare "0" — no decimal, and no percent sign either, because a percentage
// of nothing is nothing however it is measured and the sign is qualifying a magnitude that
// isn't there. Rounded first and then read, so the rule keys off what the reader is shown:
// 99.97% has no business printing "100.0%" and then keeping a decimal to prove it.
const pct = (x) => {
  const v = Math.round(Number(x) * 1000) / 10;
  return v === 0 ? "0" : v === 100 ? "100%" : v.toFixed(1) + "%";
};
// The same two slot markers bracket.js treats as non-entrants: they fill a side of a card,
// but there is no player behind them to look anything up for.
const isEntrant = (s) => !!s.name && s.name !== "TBD" && s.name !== "Bye";

// Country name (ESPN's flag alt text) → ISO 3166-1 alpha-2, so we can show a flag emoji
// instead of the country name. Covers every nation that turns up in the draws; anything
// unmapped falls back to the plain name.
const ISO2 = {
  Andorra: "AD", Argentina: "AR", Armenia: "AM", Australia: "AU", Austria: "AT",
  Belarus: "BY", Belgium: "BE", Bolivia: "BO", "Bosnia and Herzegovina": "BA", Brazil: "BR",
  Bulgaria: "BG", Canada: "CA", Chile: "CL", China: "CN", "Chinese Taipei": "TW",
  Colombia: "CO", Croatia: "HR", Czechia: "CZ", "Czech Republic": "CZ", Denmark: "DK",
  Egypt: "EG", Estonia: "EE", Finland: "FI", France: "FR", Georgia: "GE", Germany: "DE",
  "Great Britain": "GB", Greece: "GR", Hungary: "HU", India: "IN", Indonesia: "ID",
  Israel: "IL", Italy: "IT", Japan: "JP", Kazakhstan: "KZ", Korea: "KR", "South Korea": "KR",
  Laos: "LA", Latvia: "LV", Liechtenstein: "LI", Lithuania: "LT", Luxembourg: "LU",
  Macedonia: "MK", "North Macedonia": "MK", Mexico: "MX", Monaco: "MC", Montenegro: "ME",
  Netherlands: "NL", "New Zealand": "NZ", Norway: "NO", Paraguay: "PY", Peru: "PE",
  Philippines: "PH", Poland: "PL", Portugal: "PT", Romania: "RO", Russia: "RU", Serbia: "RS",
  Slovakia: "SK", Slovenia: "SI", "South Africa": "ZA", Spain: "ES", Sweden: "SE",
  Switzerland: "CH", Thailand: "TH", Tunisia: "TN", "Türkiye": "TR", Turkey: "TR",
  USA: "US", "United States": "US", Ukraine: "UA", Uzbekistan: "UZ",
};

// A country name → its 🇫🇷 flag emoji (a pair of regional-indicator letters), or "" when
// the name isn't mapped so the caller can fall back to the text.
function flagEmoji(country) {
  const cc = ISO2[country];
  return cc ? String.fromCodePoint(...[...cc].map((c) => 0x1f1e6 + c.charCodeAt(0) - 65)) : "";
}

// A finished/scheduled match's date, formatted short ("Jul 13, 2026"). "" when absent
// (older archived draws carry no per-match date) or unparseable. Read in UTC (ESPN's
// datetimes are Z): the day a match was played is fixed, not the viewer's timezone.
function matchDate(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  return isNaN(d) ? "" :
    d.toLocaleDateString([], { year: "numeric", month: "short", day: "numeric", timeZone: "UTC" });
}

async function playerData(name, gender) {
  if (!name) return null;
  const s = await query("SELECT * FROM player_summary WHERE player = ? AND gender = ?", [name, gender]);
  if (!s.length) return null;
  let triggers = [];
  try {
    triggers = await query(
      "SELECT tag, context, att_rate, att_lift, conversion, conv_delta, n, attempts " +
      "FROM player_triggers WHERE player = ? AND gender = ?", [name, gender]);
  } catch (e) { /* stale insights db: show the card without tendencies */ }
  let openings = [];
  try {
    openings = await query(
      "SELECT side, role, anchor, context, tag, att_rate, att_lift, conversion, " +
      "conv_delta, n, attempts FROM player_openings WHERE player = ? AND gender = ? " +
      "ORDER BY att_lift DESC", [name, gender]);
  } catch (e) { /* insights db predates the openings table: skip the section */ }
  let patterns = [];
  try {
    patterns = await query(
      "SELECT family, state, response, state_depth, inc_code, resp_code, lift, count, n_state, " +
      "win_rate, tour_win_rate, field_share, state_win_rate, serve_side, serve_dir, " +
      "state_kind, resp_kind " +
      "FROM player_patterns WHERE player = ? AND gender = ? ORDER BY evidence DESC",
      [name, gender]);
  } catch (e) { /* stale insights db: show the card without patterns */ }
  let serve = [];
  try {
    serve = await query(
      "SELECT side, wide, t, n_eff, matches, years, career_wide, career_t, reliable, " +
      "drift_ratio FROM player_serve WHERE player = ? AND gender = ? AND reliable = 1",
      [name, gender]);
  } catch (e) { /* stale insights db: show the card without serve direction */ }
  let years = [];
  try {
    years = await query(
      "SELECT year, matches, points FROM player_years WHERE player = ? AND gender = ? " +
      "ORDER BY year", [name, gender]);
  } catch (e) { /* stale insights db: the coverage band prints its counts without the chart */ }
  let ymatches = [];
  try {
    ymatches = await query(
      "SELECT year, points FROM player_matches WHERE player = ? AND gender = ? " +
      "ORDER BY year, seq", [name, gender]);
  } catch (e) { /* insights db predates player_matches: each season bar stays one solid block */ }
  return { s: s[0], triggers, openings, patterns, serve, years, ymatches };
}

// --- charted-match mode ---------------------------------------------------------------
// The sidecar for one charted match: its win-probability curve and a two-sided box score,
// written by `site build-match-details` and served as a static file per match. Fetched only
// when the panel opens on a match that already carries a chart_id, so a visitor who never
// opens one never pays for it.
//
// A failed fetch caches as null and the panel falls back to the career sections — the site
// is deployed without the sidecars whenever the Release asset is missing, exactly as it is
// for insights.duckdb, so absence is a state to fall back from rather than to report.
const _details = new Map();

async function matchDetail(id) {
  if (!id) return null;
  if (_details.has(id)) return _details.get(id);
  let out = null;
  try {
    const res = await fetch(`./data/matches/${encodeURIComponent(id)}.json`);
    if (res.ok) out = await res.json();
  } catch (e) { /* offline, or no sidecars published: the career panel stands */ }
  _details.set(id, out);
  return out;
}

// The sidecar is written from the chart's player1 forward; the draw orders the same meeting
// by bracket slot, and the two disagree about who comes first in roughly half of all matches
// (48 of the 121 the site currently holds). `chart_flip` is the feed's answer, decided in the
// build where the name normalisation lives — see build_brackets._chart_of.
//
// Mirrored rather than re-keyed, so everything downstream can go on reading index 0 as the
// panel's side A. A win probability is one player's, so the other's is its complement;
// leverage is the size of the swing and belongs to the point rather than to either player,
// so it is carried across untouched.
function orientDetail(det, flip) {
  if (!det || !flip) return det;
  const w = det.wp;
  return {
    ...det,
    p: [det.p[1], det.p[0]],
    s: [det.s[1], det.s[0]],
    wp: {
      ...w,
      prior: [w.prior[1], w.prior[0]],
      pre: +(1 - w.pre).toFixed(4),
      won: w.won === 1 ? 2 : 1,
      curve: w.curve.map(([pt, p, lev]) => [pt, +(1 - p).toFixed(4), lev]),
    },
  };
}

// This match's own rates, under the field names the rings and figures already read — so the
// same donut() and the same profileParts() draw a match and a career without branching.
//
// No coverage floor applies to any of these, which is the opposite of the career path's
// RATE_MIN_PTS. That floor exists because a career rate is an estimator of a latent skill
// and 173 points is too thin an estimate of one. A match rate is not an estimate: 70 service
// points is every service point there was, and 71.4% is what happened rather than a guess at
// what would happen. Withholding it would be withholding a measurement for failing a test
// written for estimates.
function matchSide(det, i) {
  if (!det || !det.s || !det.s[i]) return null;
  const s = det.s[i], o = det.s[1 - i];
  const rate = (w, n) => (n ? Number(w) / Number(n) : null);
  return {
    player: det.p[i],
    ret_winner_rate: rate(s.ret_winners, s.ret_pts),
    hold_rate: rate(s.held, s.sv_games),
    // Break rate is read off the *other* player's service games: the games this player
    // broke, over the games they had the chance to.
    break_rate: o && o.sv_games ? (o.sv_games - o.held) / o.sv_games : null,
    first_in_pct: rate(s.first_in, s.serve_pts),
    second_in_pct: rate(s.second_pts - s.dfs, s.second_pts),
    // What landing the delivery was worth, on the same two denominators as the in-rates
    // above: first-serve points over the first serves that landed, second-serve points over
    // every point that reached a second serve — a double fault among them, since it is a
    // service point lost and quoting the rate over only the second serves that landed would
    // be quoting it over the ones the player got away with.
    first_won_pct: rate(s.first_won, s.first_in),
    second_won_pct: rate(s.second_won, s.second_pts),
    len_won: s.len_won == null ? null : Number(s.len_won),
    dirs: s.dirs, dirs2: s.dirs2,
    aces: s.aces, dfs: s.dfs, serve_pts: s.serve_pts,
    // Counts, not rates. Seven break points is the median a player faces in a match and the
    // tenth percentile is two, so a save rate would be printing "50%" off two points for a
    // good part of the draw. "1 of 2" is the same fact without the false precision.
    bp_faced: s.bp_faced, bp_saved: s.bp_saved,
    // The raw serve tallies the anatomy bar splits — see serveSplit(). The two ace counts
    // ride with them because they are the cores drawn inside those same columns.
    first_in: s.first_in, first_won: s.first_won,
    second_pts: s.second_pts, second_won: s.second_won,
    aces_first: s.aces_first, aces_second: s.aces_second,
    ...shotMix(s),
  };
}

// The shot mix and what each wing did with it, off the per-stroke tallies the sidecar
// carries (build_match_details._fold_point, over the shared walk in notation.fold_shot_mix).
//
// Two denominators, and which one a rate is on is the only thing here a reader could get
// wrong, so the counts ride along with the rates and the figure prints the one it was divided
// by. Four of them, because four is what gets printed: `shots` and `net_shots` are the FIGS
// `den` values, and the two wing counts sit under the square's own labels (gsBar). A count
// nothing prints is a count that can drift from the rate beside it unnoticed.
//
// The mix is over every stroke that was not a serve — the return among them
// — because that is the whole of what the player hit and a share has to be a share of
// something whole. The outcome rates are over the groundstrokes of that wing, since "how
// often does the forehand end the point" is a question about forehands and not about how
// many of them there were.
//
// Null throughout on a sidecar written before these tallies existed: `rate` needs a
// denominator, and an absent one is not a zero. The figure then falls back to the player's
// career reading, which is the same shape a figure the match cannot measure already has.
function shotMix(s) {
  const n = Number(s.rally_shots) || 0;
  const gs = (Number(s.fh_gs) || 0) + (Number(s.bh_gs) || 0);
  const rate = (w, d) => (d ? Number(w) / Number(d) : null);
  return {
    shots: s.rally_shots == null ? null : n,
    net_shots: s.net_shots == null ? null : Number(s.net_shots),
    fh_gs: s.fh_gs == null ? null : Number(s.fh_gs),
    bh_gs: s.bh_gs == null ? null : Number(s.bh_gs),
    fh_share: rate(s.fh_gs, gs),
    fh_winner_pct: rate(s.fh_winners, s.fh_gs),
    fh_err_pct: rate(s.fh_errs, s.fh_gs),
    bh_share: rate(s.bh_gs, gs),
    bh_winner_pct: rate(s.bh_winners, s.bh_gs),
    bh_err_pct: rate(s.bh_errs, s.bh_gs),
    slice_pct: rate(s.slice_shots, n),
    net_pct: rate(s.net_shots, n),
    net_winner_pct: rate(s.net_winners, s.net_shots),
    net_err_pct: rate(s.net_errs, s.net_shots),
  };
}

// No shot-quality verdict prints here. class_rel_z still ships in player_summary and
// nothing renders it: it correlates -0.99 with the raw score it is a residual of and 66% of
// its variance is rally length, so it grades players on how long their points run. Rendering
// it would mean orthogonalising against style_expected first, and even then the
// style-stripped split-half is 0.43/0.60, which will not carry three bands. See
// experiments/class_relative_wpa.

// A collapsed mini-court under a pattern: tap to see where the lead-up shots landed,
// drawn on the fly from the notation (client twin of viz.rally_svg). Empty when the
// pattern has no chartable direction, so there's nothing to draw.
function rallyDrawer(pattern, mirror = false, court = "deuce") {
  const svg = patternSvg(pattern, mirror, court);
  return svg ? `<details class="rally"><summary>ball path</summary>
    <div class="court">${svg}</div></details>` : "";
}

// One decision, two outcomes: a green light converts, a trap is taken bait. The cue is
// the lead-up sequence; the two numbers are the aggressive shot frequency it provokes and
// how often that shot pays. Courts stay collapsed here — a trigger is a 2–4 stroke
// sequence, and a column of full sequence drawings would bury the court patterns above,
// which are what the panel leads with.
// The cue's two numbers, drawn as the one bar they are: its length is the aggressive shot
// frequency the cue provokes, where it changes colour is how much of that landed,
// and the tick is the rate the shot gets played at *without* the cue — so the lift the
// sentence states as "3.0× their norm" is about the gap between the tick and the bar's end.
//
// About, and not exactly. The tick is the player's pooled no-cue rate, while a cue confirmed
// in only one of the two held-out folds ships that fold's rate and that fold's lift, measured
// against the half of their matches it was confirmed on. A half's baseline sits up to a couple
// of points off the pooled one, so on about a third of cues the printed multiple and the gap
// on the bar disagree a little. The tick still draws at the pooled rate, because it is the one
// reference the whole column is read against: a tick that moved per row would put five bars in
// a column against five different references, each of them visibly out of line with the
// baseline bar at the top that is meant to be that same rate.
//
// Deliberately the same construction as the comparison strip's winners-and-errors row,
// down to the drained second segment and the haloed reference tick, because it is the same
// measurement: the notation key already tells the reader these are "the same pair of
// numbers the strip up top splits into one bar, read per cue". They should look like it.
// The domain is 0–1 rather than the strip's 0.05–0.32, though: a cue that does anything at
// all pushes the frequency far past the range a player's rally balls average out to, and
// on the strip's scale every one of these would sit clamped at the end of the bar.
// `base` is the reference to draw the tick at. Pooled cues are handed the player's own
// no-cue rate; opening cues have no such figure — each is against its own court-and-shot
// norm — so they leave it out and the norm is recovered from the cue's own two numbers.
function trigMeter(t, base) {
  const att = Number(t.att_rate);
  if (!isFinite(att)) return "";
  const conv = t.conversion == null ? null : Number(t.conversion);
  const lift = Number(t.att_lift);
  const ref = Number(base);
  const norm = isFinite(ref) && ref > 0 ? ref
    : isFinite(lift) && lift > 0 ? att / lift : null;
  const segs = conv == null ? `<span style="flex:1"></span>`
    : `<span style="flex:${conv}"></span><span class="miss" style="flex:${1 - conv}"></span>`;
  const tick = norm == null ? "" : `<u style="left:${(norm * 100).toFixed(1)}%"></u>`;
  return `<div class="tmeter"><i style="width:${(att * 100).toFixed(1)}%">${segs}</i>${tick}</div>`;
}

// `hand` is the player's, and every row here needs it: both trigger families store their
// contexts in the player's own frame, mirrored for a left-hander so that one cue string
// means one piece of tennis whoever plays it. The drawing is the one place that wants the
// real court back, so it mirrors again on the way out.
function trigLine(t, hand, base) {
  // Every cue here is a two-shot lead-up. No starred 3-4 shot tier ships: on serve-blind
  // ground two of 1,752 three-shot candidates survive a held-out screen, and both belong to
  // retired players. See experiments/rally_patterns.
  const trap = t.tag === "trap";
  const cls = trap ? "bait" : "green";
  const conv = Math.round(t.conversion * 100);
  // A cue's conversion is measured against the player's *other* cues, not against their
  // all-strokes rate. Conditional on a lead-up raising the frequency at all, conversion
  // already sits well above that rate — the balls you attack on are the ones you were well
  // placed to attack — so the all-strokes line would sit far below the middle of the class
  // it is splitting and call the bottom of a normal spread a trap.
  const payoff = trap
    ? `converts only <b>${conv}%</b>
       <span class="lift">${Math.round(t.conv_delta * 100)}pp vs their other cues</span>`
    : `converts <b>${conv}%</b>`;
  const against = "their norm";
  // Two denominators, both printed. The frequency is over every stroke from this lead-up
  // (n); the conversion is over the aggressive shots among them (attempts), which runs
  // about a third of n — and it was the unprinted one, so a conversion resting on 33
  // shots read as though it rested on 93.
  const att = num(t.attempts);
  const counts = att == null ? `n=${Number(t.n)}`
    : `n=${Number(t.n)}, ${att} attempt${att === 1 ? "" : "s"}`;
  return `<div class="trig ${cls}">
    <p class="tcue">after <code>${esc(t.context)}</code></p>
    <p class="tnum">aggressive <b>${Math.round(t.att_rate * 100)}%</b>
      <span class="lift">${Number(t.att_lift).toFixed(1)}× ${against}</span> ·
      ${payoff} <span class="lift">${counts}</span></p>
    ${trigMeter(t, base)}
    ${rallyDrawer(t.context, hand === "L")}</div>`;
}

// Where they aim the first serve. Only wide and T are printed: the body share is
// partly a charter's opinion (charters disagree about it by ±4-6 points on the same
// players), so the two shown do not add to 100 and the remainder is deliberately
// unnamed. Rows appear per court side only where the player has enough charted serves
// for the share to be mostly signal — the `reliable` flag the experiment ships, which
// is already applied in the query, so a thinly-charted player shows nothing here
// rather than a number that is really sampling noise.
function serveHtml(d) {
  const rows = (d && d.serve) || [];
  if (!rows.length) return "";
  const pct = (v) => `${Math.round(Number(v) * 100)}%`;
  const order = { deuce: 0, ad: 1 };
  const sorted = [...rows].sort((a, b) => order[a.side] - order[b.side]);
  // Laid out the way the server sees it. The deuce box is screen-left and the ad box
  // screen-right, and inside each one the zones run outside-in on the deuce side and
  // inside-out on the ad side, because the centre line is between the two boxes. So
  // reading the strip left to right walks the four service-box thirds in the order they
  // sit on the court — the same mapping court.js uses to place a serve bounce.
  // --p drives a faint backfill behind each number, growing from the court line that
  // zone belongs to — so the share reads as a bar without a second element to lay out.
  const zone = (label, v) =>
    `<span class="srvzone" style="--p:${(Number(v) * 100).toFixed(1)}%">
      <span class="zl">${label}</span><b>${pct(v)}</b></span>`;
  const box = (r) => {
    const zones = r.side === "ad"
      ? zone("T", r.t) + zone("wide", r.wide)
      : zone("wide", r.wide) + zone("T", r.t);
    return `<div class="srvbox">${zones}
      <span class="srvlabel">${r.side} · n≈${Number(r.n_eff).toLocaleString()}</span></div>`;
  };
  // The window, in the reader's terms. The year span is the honest thing to print
  // next to it: for a thinly-charted player "recent" can still reach back years, and
  // that changes how much the number should be trusted.
  //
  // This player's own window, off the row. The decay reaches as far back as a career
  // goes, so the count is the matches still carrying a tenth of the newest one's
  // weight — which is 34 for a long career and a dozen for a short one. The build also
  // ships the tour's largest window as a gate, and printing that against every player
  // read "last 34 charted matches" over a player who has been charted eleven times.
  const win = Number(sorted.find((r) => r.matches)?.matches) || null;
  const span = sorted.find((r) => r.years)?.years?.replace("-", "–");
  const caption = `<p class="srvwin">${win ? `last ${win} charted matches` : "recent matches"}${span ? ` (${span})` : ""}</p>`;

  // A career average would be a different number for the players who moved, so say so
  // rather than quietly showing only the recent one.
  let moved = "";
  const big = sorted
    .filter((r) => Number(r.drift_ratio) >= 1.5 && Math.abs(r.t - r.career_t) >= 0.05)
    .sort((a, b) => Math.abs(b.t - b.career_t) - Math.abs(a.t - a.career_t))[0];
  if (big) {
    moved = `<p class="tnum">${big.side} court: T share ${big.t > big.career_t ? "up from" : "down from"} <b>${pct(big.career_t)}</b>
      across their whole career</p>`;
  }
  // Break points: side-adjusted, since break points skew to the ad court and the court
  // moves placement more than the score does. Most players show nothing here, because
  // most players' break-point placement is indistinguishable from their normal-point
  // placement once the multiplicity correction is applied.
  let bp = "";
  const delta = d.s && d.s.serve_bp_wide_delta;
  // Significant *and* big enough to act on. The experiment's test is correctly
  // multiplicity-corrected, but significance on a player with a thousand charted break
  // points certifies shifts of three or four points that no returner can prepare against —
  // eleven of fifty-eight qualifying lines. A returner adjusts to "he goes wider here", so
  // the line only appears where the shift reaches five points.
  const BP_MIN = 0.05;
  if (d.s && Number(d.s.serve_bp_sig) === 1 && delta != null && Math.abs(delta) >= BP_MIN) {
    const pts = Math.round(Math.abs(delta) * 100);
    // Its own window, said out loud. Everything else in this section is the recency-weighted
    // window named in the caption above; this one is computed across the whole charted
    // career, and sitting silently under "last 34 charted matches" it read as though it
    // shared it.
    bp = `<p class="srvbp" title="a shift this size clears the experiment's significance
      test and is large enough to play against; most players show nothing here">on break
      points, <b>${pts} points</b> ${delta > 0 ? "wider" : "less wide"} than their own norm
      <span class="srvbpwin">across their whole charted career</span></p>`;
  }
  return `<div class="srv">
    <div class="srvcourt">${sorted.map(box).join("")}</div>
    ${caption}${moved}${bp}</div>`;
}

// The same strip, filled from the match. Three zones rather than the career section's two:
// wide and T are what the career mix models, but a match has a real body count and dropping
// it would leave two shares that don't sum to what was served.
//
// Counts lead and the share follows, because the count is the honest unit here — "17 of 62"
// carries its own sample where "27%" hides it — and the career share sits under each zone as
// the anchor, so a serve pattern that moved for this match reads as having moved.
//
// First deliveries, landed or faulted, which is the same convention the career mix uses
// (serve_tendencies reads the direction off the raw first-serve column). Second serves are
// counted separately in the sidecar and print as a line under the strip.
function serveMatchHtml(d, md) {
  if (!md || !md.dirs) return "";
  const career = new Map(((d && d.serve) || []).map((r) => [r.side, r]));
  const NAMES = ["wide", "body", "T"];
  const zone = (label, n, tot, ref) => {
    const f = tot ? n / tot : 0;
    // A zone nobody served to says so once. The count above it is already a nought, and a
    // "0%" under it is the same nothing a second time — kept as an empty line rather than
    // dropped, so the zone beside it keeps its own share on the row it belongs on.
    return `<span class="srvzone" style="--p:${(f * 100).toFixed(1)}%">
      <span class="zl">${label}</span><b>${n}</b>
      <span class="zpc">${n ? `${Math.round(f * 100)}%` : ""}</span>
      ${ref == null ? "" : `<i class="zref">career ${Math.round(Number(ref) * 100)}%</i>`}</span>`;
  };
  const box = (dirs, side, serve, anchored) => {
    const c = (dirs || {})[side] || [0, 0, 0];
    const tot = c[0] + c[1] + c[2];
    if (!tot) return "";
    const ref = anchored ? career.get(side) : null;
    // Outside-in on the deuce side, inside-out on the ad side — the order the four service
    // box thirds actually sit in when read left to right, as in the career strip above.
    const order = side === "ad" ? [2, 1, 0] : [0, 1, 2];
    // career_wide / career_t, not wide / t: the latter pair is the recency-weighted window
    // the career section prints under its own "last N charted matches" caption, and a line
    // that says "career" has to be one. Both are shares of all three deliveries — they sum
    // to about 0.87 across the corpus, with body taking the rest — so the match share and
    // the anchor are the same measurement over different windows.
    const refOf = (i) => (!ref ? null : i === 0 ? ref.career_wide : i === 2 ? ref.career_t : null);
    return `<div class="srvbox">${order.map((i) => zone(NAMES[i], c[i], tot, refOf(i))).join("")}
      <span class="srvlabel">${side} · ${tot} ${serve} serves</span></div>`;
  };
  const boxes = ["deuce", "ad"].map((k) => box(md.dirs, k, "first", true)).join("");
  if (!boxes) return "";
  // The second serve is split by court like the first, not pooled across the two. Pooling
  // buys precision this panel is not spending: these are counts of what was struck, not
  // estimates of a tendency, and forty deliveries over a match are forty however they are
  // grouped. What pooling costs is the distinction the split exists for — the two courts
  // open opposite wings, so a mix read across both is the average of two different serves,
  // which is the argument the opening-cues section already makes about first serves. It
  // holds harder here: a second serve is aimed at the returner's weaker side more
  // deliberately than a first, and which side that is changes with the court.
  //
  // No career anchor under these. The shipped placement mix is first serves only
  // (build_insights._serve_placement filters to them), so there is nothing to set them
  // against, and a blank "career —" would read as a missing number rather than an absent one.
  const second = ["deuce", "ad"].map((k) => box(md.dirs2, k, "second", false)).join("");
  return `<div class="srv">
    <div class="srvcourt">${boxes}</div>
    ${second ? `<div class="srvcourt second">${second}</div>` : ""}
    <p class="srvwin">this match only</p></div>`;
}

// Court-state patterns (court_response experiment): how the player answers a given
// incoming ball, vs the field's answers to the same ball. Zones are named relative to
// the player's own hands, run-arounds get their tennis names, and every pattern
// repeated in both halves of the player's charted matches to earn its place here.
//
// The court is the point of the card, so it sits in the card rather than behind a
// disclosure, with the lift — the finding — promoted out of the parenthetical it used
// to share with three other numbers.
function patternCard(p) {
  // Payoff: their point-win rate playing this response against their own rate answering
  // the same incoming ball however else they answer it. Baselining against the tour's rate
  // for that response would mostly rank players rather than choices — that gap runs about
  // +0.43 with a player's overall serve-plus-return rate, so the strongest thirty would beat
  // the tour on nearly every pattern they own whatever the shot is worth. Both numbers here
  // are the same player on the same ball, so the difference is the choice.
  // Level is stated rather than left blank, so a missing arrow always means the
  // comparison is genuinely unavailable and never that the gap rounded to zero.
  let payoff = "";
  if (p.win_rate != null) {
    const w = `wins <b>${Math.round(p.win_rate * 100)}%</b>`;
    // The reference prints as a figure rather than as a phrase. In a 160px column on a
    // phone "▲5 vs their other answers" is three lines of card for one comparison, and
    // it has to be nowrap or it breaks mid-phrase — so the card carries the two numbers
    // and the section note above carries the sentence, once, for all six cards.
    const ref = num(p.state_win_rate);
    if (ref == null) {
      payoff = ` · ${w}`;
    } else {
      const d = Math.round((p.win_rate - ref) * 100);
      const r = `${Math.round(ref * 100)}%`;
      payoff = ` · ${w} ` + (d === 0 ? `<span class="lvl">= their ${r}</span>`
        : `<span class="${d > 0 ? "up" : "down"}">${d > 0 ? "▲" : "▼"}${Math.abs(d)}
           vs ${r}</span>`);
    }
  }
  // What the lift is taken against. "3.4x the tour" is two very different claims off a
  // 27% base and off a 0.4% one; without the share, a mild over-index on the tour's own
  // favourite shot and a genuine oddity look alike.
  const share = num(p.field_share);
  const vs = share == null ? "" : ` <span class="pshare">tour ${share < 0.01
    ? "under 1" : Math.round(share * 100)}%</span>`;
  // The return family is the serve+1: its state names the court and often the serve, so
  // the drawing starts at the serve rather than at the return. retSvg falls back to the
  // pair drawing for a pattern surfaced with the sides pooled.
  // The two stroke kinds go with the codes: a volley is met in the air, so a drawing that
  // does not know which balls were volleys puts a bounce under one that never landed.
  const court = p.family === "ret"
    ? retSvg(p.serve_side, p.serve_dir, p.inc_code, p.resp_code, p.state_depth,
      p.state_kind, p.resp_kind)
    : pairSvg(p.inc_code, p.resp_code, p.state_depth, p.state_kind, p.resp_kind);
  // Both denominators. The count alone cannot say whether this is what they do with the
  // ball or a corner of it: 277 answers looks the same printed on its own whether the
  // ball came 970 times or 300. n_state is what the frequency claim is actually over.
  const of = num(p.n_state);
  const n = `n=${Number(p.count).toLocaleString()}${of
    ? `<span class="pof">/${of.toLocaleString()}</span>` : ""}`;
  return `<div class="pcard2">
    <div class="pcourt">${court}</div>
    <div class="pmeta">
      <p class="plift">${Number(p.lift).toFixed(1)}×<span> the tour</span>${vs}</p>
      <p class="pdesc">${esc(p.state)}<b>→ ${esc(p.response)}</b></p>
      <p class="pfoot">${n}${payoff}</p>
    </div>
  </div>`;
}

const familyCards = (d, fam, n) => !d ? "" :
  d.patterns.filter((p) => p.family === fam).slice(0, n).map(patternCard).join("");

// The player's own rate, with no cue at all: their aggressive shot frequency over every
// rally ball they hit, and how much of that lands.
//
// It headed the comparison strip as a ring of its own, and a ring was the wrong instrument
// for it. Every player on either tour sits near a fifth, so the arc was a stub at the foot
// of an all-but-empty circle, and the one thing a reader wanted to do with the number —
// hold it against the cue rates below, which run three and four times higher — needed two
// screens of scrolling and a change of scale.
//
// Here it is the first bar in the player's own column, drawn on the same 0–1 domain and
// from the same left edge as every cue bar under it. So the section's whole claim is one
// glance: this is the rate, and these are the lead-ups that move it. It is also, exactly,
// the reference tick each of those bars carries.
function trigBase(d) {
  const att = num(d.s.trig_att_rate);
  if (att == null) return "";
  const conv = num(d.s.trig_conversion);
  const segs = conv == null ? `<span style="flex:1"></span>`
    : `<span style="flex:${conv}"></span><span class="miss" style="flex:${1 - conv}"></span>`;
  return `<div class="trig base">
    <p class="tcue">every rally stroke, no cue</p>
    <p class="tnum">aggressive <b>${(att * 100).toFixed(1)}%</b>${conv == null ? ""
      : ` · converts <b>${Math.round(conv * 100)}%</b>`}
      ${/* This *is* the tick below: trigSets hands this same rate to every bar in the
           column to draw its tick at, so the bar here ends where those ticks stand. */""}</p>
    <div class="tmeter"><i style="width:${(att * 100).toFixed(1)}%">${segs}</i></div>
  </div>`;
}

// One opening cue. Same currency as a pooled trigger — a lead-up that shifts the
// player's aggressive shot frequency — but every number is against their own norm for that
// same shot on that same service court, which is what the pooled row above cannot say. The
// court is named in the row rather than left to the drawing, because the drawing is
// collapsed by default and the court is the whole point of the row.
//
// The service court is also passed to the drawing, which pooled cues cannot do: a wide
// serve is a different physical ball on the two sides, so drawing an ad-court cue on the
// deuce court would contradict the row above it.
function openLine(o, hand) {
  const trap = o.tag === "trap";
  const conv = Math.round(o.conversion * 100);
  const att = num(o.attempts);
  const counts = att == null ? `n=${Number(o.n)}`
    : `n=${Number(o.n)}, ${att} attempt${att === 1 ? "" : "s"}`;
  const payoff = trap
    ? `converts only <b>${conv}%</b> <span class="lift">${Math.round(o.conv_delta * 100)}pp
       vs their other opening cues</span>`
    : `converts <b>${conv}%</b>`;
  return `<div class="trig ${trap ? "bait" : "green"}">
    <p class="tcue"><span class="ocourt">${esc(o.side)} court · ${esc(o.anchor)}</span>
      after <code>${esc(o.context)}</code></p>
    <p class="tnum">aggressive <b>${Math.round(o.att_rate * 100)}%</b>
      <span class="lift">${Number(o.att_lift).toFixed(1)}× their ${esc(o.side)}
      ${esc(o.anchor)} norm</span> · ${payoff} <span class="lift">${counts}</span></p>
    ${trigMeter(o)}
    ${rallyDrawer(o.context, hand === "L", o.side)}</div>`;
}

// Greens first then traps, matching the section above; two of each at most, so a player
// with cues on both courts does not push the other player's column out of step.
function openSets(d) {
  if (!d || !d.openings || !d.openings.length) return "";
  const greens = d.openings.filter((o) => o.tag === "green")
    .sort((a, b) => b.att_lift - a.att_lift).slice(0, 2);
  const traps = d.openings.filter((o) => o.tag === "trap")
    .sort((a, b) => a.conv_delta - b.conv_delta).slice(0, 2);
  return [...greens, ...traps].map((o) => openLine(o, d.s.hand)).join("");
}

// A player's triggers, in the order the panel shows them: their own baseline rate, then the
// green lights and traps, then the note that earns its place by absence.
//
// The baseline comes from player_summary rather than from the trigger table, so it prints for
// a player charted enough to have a rate but not enough for any cue to clear the significance
// test — which is most of the tour. Otherwise their column would say only "nothing at this
// player's coverage".
function trigSets(d) {
  if (!d) return "";
  const base = trigBase(d);
  if (!d.triggers.length) return base;
  const greens = d.triggers.filter((t) => t.tag === "green")
    .sort((a, b) => b.att_lift - a.att_lift).slice(0, 3);
  const traps = d.triggers.filter((t) => t.tag === "trap")
    .sort((a, b) => a.conv_delta - b.conv_delta).slice(0, 2);
  // n_traps comes from the experiment's own per-player table and the rows come from the
  // top-N selection above, so the banner checks both rather than trusting one: a count
  // that disagreed with the rows would print "nothing baits them" directly above a ⚠.
  const immune = d.s.n_traps != null && Number(d.s.n_traps) === 0
    && !d.triggers.some((t) => t.tag === "trap")
    ? `<div class="trig immune">no trap sequences — every lead-up that raises their
       aggressive shot frequency converts at least as well as their other cues do</div>` : "";
  // Bound explicitly rather than passed to .map directly, which would hand trigLine the
  // array index as its second argument and mirror every drawing on an odd row.
  const hand = d.s.hand;
  const norm = num(d.s.trig_att_rate);
  return base + [...greens, ...traps].map((t) => trigLine(t, hand, norm)).join("") + immune;
}

// --- "side by side": one ring ---------------------------------------------------------
// One shared axis, bent into a circle. 6 o'clock is zero for both players, A sweeps up the
// left of it and B up the right, and a half-turn each is the top. They grow from a shared
// origin and the comparison is still "whose reaches further" — read as a sweep rather than as
// a length, with the unreached part of the scale left as open track at the foot.
//
// The numbers carry the exact values, set against the marks they are read off. A sweep is
// read less precisely than a length, so the picture is for the comparison and the digits are
// for the value, and neither is asked to do the other's job.
//
// Games, not points. Points are where tennis is close: the middle half of the charted men's
// tour wins between 63% and 68% of its service points, so 66.5% against 68.1% is under three
// degrees of ring — a whole circle spent drawing two arcs of the same length. Counted in
// games the same advantage is not close at all, because a game is a race the better player
// keeps re-entering: three points in a hundred is about twenty games in a hundred. The ring
// draws the games, and the points are not on the panel as a figure at all — the serve plot
// below is what a service point is actually made of, at the resolution that question has.
//
// Both figures on the ring are games won, which is why they share one ring instead of taking
// one each. The arc is the service games the player held. The tick laid across the band is
// the return games they broke, at the point on the same scale it reaches. Same axis,
// different denominator — their own service games against the opponent's — and the distance
// between arc and tick is the shape of a player at a glance: a server sits high on the ring
// with a short tick far behind them, a returner lower with the tick close up.
//
// The ring runs from zero to a real 100%: both ends are reachable, players have held every
// service game of a match and broken every return game of one, and `top` prints the ceiling
// over the arc climbing toward it.
//
// `mark` is a function of the player's own row rather than a scalar on the row spec, since it
// is a second figure per player. `better` says which direction wins, and the tick rides it
// too — holding more and breaking more are both worth more.
const clamp01 = (x) => Math.max(0, Math.min(1, x));
const num = (v) => (v == null ? null : Number(v));

// The coverage floor a career hold and break rate have to clear before this panel will print
// them, in charted points — the same 2,000 the win probability's confidence bands already use
// as their lower edge.
//
// It is a floor on obvious nonsense rather than a claim that everything above it is precise:
// these rates are career-long and never adjusted for the opponents a volunteer chose to
// chart, so the number above the floor is still a charted rate and not a true one. Roughly a
// dozen charted matches sit behind it.
//
// The floor is also what makes shrinkage unnecessary. Pulling the rates toward the tour mean
// would bias a displayed measurement toward a prior the reader cannot see, and the thin
// players it would protect are already excluded, so the ring shows each player's own charted
// rate. The build applies a second floor of its own — 100 games on each side — which at this
// gate excludes nobody.
const RATE_MIN_PTS = 2000;
const wellCharted = (d) => !!d && (Number(d.s.points_charted) || 0) >= RATE_MIN_PTS;

function tapeRows() {
  return [
    {
      k: "hold_rate", label: "service games held", short: ["games", "won"],
      hi: 1, top: "100", better: "hi", fmt: pct, unit: "serve",
      mark: { k: "break_rate", label: "return" },
    },
  ];
}

// Ring geometry, in the 100×100 field every donut is drawn in.
const DN_R = 36, DN_W = 10, DN_C = 50;
const DN_LEN = 2 * Math.PI * DN_R;          // circumference, in those same units

// A point `rad` out from the centre, at `deg` clockwise from 12 o'clock.
function dnPoint(deg, rad) {
  const t = (deg - 90) * Math.PI / 180;
  return [DN_C + rad * Math.cos(t), DN_C + rad * Math.sin(t)];
}

// Where a sweep of `s` degrees lands, in those same clock degrees. Both players leave the
// foot of the ring — 6 o'clock — and climb, A up the left side and B up the right, so more
// is up and each player's arc is on the side their own numbers are.
const dnAt = (s, side) => (side === "a" ? 180 + s : 180 - s);

// One player's sweep, as a dash on a full circle rather than as an arc path. A circle's own
// path starts at 3 o'clock and runs clockwise, so one group transform — a quarter turn to
// bring that start down to 6 o'clock, plus a mirror for the player climbing the other side —
// points it the right way. The sweep after that is a length along that path, which means no
// arc flags and no large-arc special case at exactly half a turn.
function dnArc(deg, side) {
  if (!(deg > 0)) return "";
  const spin = side === "b"
    ? `translate(${DN_C * 2},0) scale(-1,1) rotate(90 ${DN_C} ${DN_C})`
    : `rotate(90 ${DN_C} ${DN_C})`;
  const seg = DN_LEN * deg / 360;
  return `<g transform="${spin}"><circle class="dseg ${side}" cx="${DN_C}" cy="${DN_C}"
    r="${DN_R}" stroke-dasharray="${seg.toFixed(2)} ${DN_LEN.toFixed(2)}"/></g>`;
}

// A spoke across the ring at `deg`, reaching `out` units past its outer edge and `inn` past
// its inner one. The two default to the same, which is what a mark laid across the band wants;
// the scale ends below pass `inn: 0` because they share the hole with a label and a spoke that
// reached into it would be a line through the top of the type.
function dnSpoke(deg, out, cls, inn = out) {
  const [x1, y1] = dnPoint(deg, DN_R - DN_W / 2 - inn);
  const [x2, y2] = dnPoint(deg, DN_R + DN_W / 2 + out);
  return `<line class="${cls}" x1="${x1.toFixed(2)}" y1="${y1.toFixed(2)}"` +
    ` x2="${x2.toFixed(2)}" y2="${y2.toFixed(2)}"/>`;
}

// The player's own break rate, laid across the band where it falls on the ring's scale — see
// the `mark` note above. Two spokes on the same line, the wider dark one under the narrower
// light one, which is the strip's haloed tick drawn in SVG. It stands on both of the ring's
// grounds — inside the arc for a player who breaks about as often as they hold, out on open
// track well short of the arc's end for everyone else — and it is the halo that carries it
// across them: on a violet or red arc the white core does the work, and on the pale track the
// ink halo does.
const dnTick = (deg) => dnSpoke(deg, 1.6, "dtickhalo") + dnSpoke(deg, 1.6, "dtick");

// Zero, cut into the foot of the ring. The two sweeps leave in opposite directions from this
// point, so without it they abut and the ring reads as one continuous band that happens to
// change colour somewhere — with the origin, which is the thing both sweeps are measured
// from, left to be inferred from the colour change. It is the polar version of the hairline
// that stood between the two bars, and it is drawn in the card's own colour so it reads as a
// gap in the ring rather than as one more mark laid on top of it.
const dnOrigin = () => dnSpoke(180, 0.5, "dorigin");

// The two ends of the scale, marked on the drawing: 12 o'clock, where both sweeps finish, and
// 6 o'clock, where they start. The numbers naming them now sit inside the hole, and a number
// floating in a hole says what the end is worth without saying where it is — an arc that stops
// a few degrees short of the top is not visibly short of anything until the top is a mark.
//
// Ink, and the only marks on the band set in it. That is the distinction being drawn: the
// origin seam is cut out of the ring in the card's own colour, and the tick is drawn in the
// same muted grey as the figure it belongs to beside the ring — a gap and a measurement, both
// of them things happening inside the scale. These two are the scale, so they are laid on.
//
// At the foot this lands inside the origin seam, which is 2.2 units of card colour to this
// line's 1.1 — so the seam keeps a hairline of white either side and gains a definite edge
// instead of competing for the same spot. Drawn after it, for exactly that stacking.
//
// `inn: 0` stops it flush with the inner edge of the band. The scale labels sit about 1.3
// units further in (see .dncap), and the tick's 1.6 of inward reach would put an ink line
// through the top of "100%".
const DN_END_OUT = 1.2;
const dnEnds = () => dnSpoke(0, DN_END_OUT, "dend", 0) + dnSpoke(180, DN_END_OUT, "dend", 0);

// --- the floating labels -------------------------------------------------------------
// Both figures are set beside the mark they are read off: the holds figure where its arc
// stops, the breaks figure beside the tick — so the number and the thing it measures are one
// object, and neither has to be matched back to a column of small print by colour or by side.
//
// The two could not go in one column and stay tied to the ring: they are two different places
// on it, and a stacked list puts them in reading order rather than in the order the ring
// makes.
//
// `left`/`top` are percentages of a box that is exactly the drawing's size, so they resolve
// against the same square the viewBox does and hold at every ring size. Anchored on a circle
// just outside the band, then pushed clear of it by the transform: side A's labels end at
// their anchor and reach left, side B's start at theirs and reach right, which is the half of
// the ring each player's arc climbs. That is also what keeps the two players' labels apart at
// the foot, where their anchors are closest.
const DN_LR = 45;

function dnLabel(x, y, side, cls, html) {
  return `<span class="dlab ${side} ${cls}"
    style="left:${x.toFixed(2)}%;top:${y.toFixed(2)}%">${html}</span>`;
}

// The clear space the two figures need between them, in viewBox units, when the values they
// sit at are close enough on the ring to put them on the same line of type.
//
// Both labels reach outward from the same side, so a small angular gap does not separate them:
// near the top of the ring it moves them sideways, one behind the other. What has to be clear
// is the vertical, and it needs the two half-heights plus air — about 17.5px.
//
// Written in viewBox units against the *smallest* ring the panel draws, so the separation is
// sufficient at every size rather than only at the one it was measured on. On a wider ring the
// same fraction is a few more pixels than strictly needed, which costs nothing; calibrated the
// other way it would come up short on a phone.
//
// Holds and breaks land far apart for nearly everyone — the two sit either side of half the
// ring — so this bites for 2 of the 363 players the ring prints for, both of them returners
// who break about as often as they hold, which is a real thing about how they win and not a
// fault in the drawing. Where it applies the two labels move apart around their own midpoint,
// so neither ends up further than half the shortfall from its own mark, with the tick glyph
// and the arc's own end still directly beside them.
const DN_SEP = 10.5;

function dnSpread(a, b) {
  const d = b.y - a.y;
  if (Math.abs(d) >= DN_SEP) return [a, b];
  const push = (DN_SEP - Math.abs(d)) / 2 * (d < 0 ? -1 : 1);
  return [{ x: a.x, y: a.y - push }, { x: b.x, y: b.y + push }];
}

// A ring cell. The ring is the whole cell now — there are no flanking columns left to lay out
// beside it, so nothing here has to hold three tracks in balance.
const dnCell = (art) => `<div class="dn">${art}</div>`;

function donut(r, sa, sb) {
  const va = sa ? num(sa[r.k]) : null;
  const vb = sb ? num(sb[r.k]) : null;
  if (va == null && vb == null) return "";
  // Which side has the better figure of a pair — "" when either is missing, they tie, or the
  // metric has no better end. Used for the arc's figure and, the same way, for the figure
  // across the band: both are games won, and more of either is worth more.
  const leadOf = (xa, xb) => r.better && xa != null && xb != null && xa !== xb
    ? ((xa > xb) === (r.better === "hi") ? "a" : "b") : "";
  const lead = leadOf(va, vb);
  const at = (v) => clamp01(v / r.hi) * 180;
  // Read out of the player's row once and used by both the drawing and the label beside it:
  // the tick and the number against it are the same value twice, off one lookup.
  const markOf = (s) => (!r.mark || !s ? null : num(s[r.mark.k]));
  const markLead = leadOf(markOf(sa), markOf(sb));
  const anchor = (deg, side) => {
    const [x, y] = dnPoint(dnAt(deg, side), DN_LR);
    return { x, y };
  };
  // One player's labels. A side with no rate gets a single em dash where its arc would have
  // left the foot: the half is empty on purpose, and an empty half beside a full one should
  // say so on the drawing rather than only in the note under it.
  const labels = (v, s, side) => {
    if (v == null) return `<span class="dlab ${side} dnone">—</span>`;
    const m = markOf(s);
    // Word before figure on side A, figure before word on side B — so the number ends up
    // nearest the ring on both sides, against the mark it is read off. Side A's labels are
    // right-aligned and reach in toward the band; side B's reach out from it, so number-first
    // already lands its digits by the ring there.
    const flank = (word, fig) => esc(side === "a" ? `${word} ${fig}` : `${fig} ${word}`);
    // Placed as a pair, because whether either can sit exactly on its own mark depends on
    // where the other one is — see dnSpread().
    let pa = anchor(at(v), side), ga = m == null ? null : anchor(at(m), side);
    if (ga) [pa, ga] = dnSpread(pa, ga);
    const unit = r.unit ? `<span class="dvu">${esc(r.unit)}</span>` : "";
    const held = side === "a" ? `${unit}${r.fmt(v)}` : `${r.fmt(v)}${unit}`;
    const out = [dnLabel(pa.x, pa.y, side, `darc${lead === side ? " lead" : ""}`, held)];
    if (ga) {
      // No key glyph. The figure is set against the tick it names, close enough that a
      // second copy of the mark beside the number was labelling the label. Bolded on the side
      // that breaks more, the same lead mark the arc's own figure carries.
      out.push(dnLabel(ga.x, ga.y, side, `dtck${markLead === side ? " lead" : ""}`,
        flank(r.mark.label, pct(m))));
    }
    return out.join("");
  };

  // "no data" only in the label a screen reader hears — set on the drawing it would be a
  // sentence where every other mark is a figure, which is what the em dash is for. Both of
  // the ring's figures are spoken, since both are the ring rather than an ornament on it.
  const say = (v) => (v == null ? "no data" : r.fmt(v));
  const aria = `${r.label} — ${say(va)} against ${say(vb)}`
    + (r.mark ? `; ${r.mark.label} ${say(markOf(sa))} against ${say(markOf(sb))}` : "");
  // The ring's name, shrunk and shortened to sit in its own hole rather than over the row —
  // the one place beside the arc itself a reader is already looking.
  const title = r.short
    ? `<p class="dnttl">${r.short.map(esc).join("<br>")}</p>` : "";
  // The two ends of the scale, at the two ends of the ring, inside the hole. Every other
  // figure sits outside the band against its own mark, so the hole holds only the two that
  // belong to the ring rather than to either player.
  return dnCell(`<div class="dnring">
      <svg viewBox="0 0 100 100" xmlns="http://www.w3.org/2000/svg" role="img"
        aria-label="${esc(aria)}">
        <circle class="dtrack" cx="${DN_C}" cy="${DN_C}" r="${DN_R}"/>
        ${va == null ? "" : dnArc(at(va), "a")}${vb == null ? "" : dnArc(at(vb), "b")}
        ${dnOrigin()}${dnEnds()}
        ${/* one per side, and only where that side has a sweep to read it against — a lone
             tick on an empty half marks a conversion of nothing */""}
        ${va == null || markOf(sa) == null ? "" : dnTick(dnAt(at(markOf(sa)), "a"))}
        ${vb == null || markOf(sb) == null ? "" : dnTick(dnAt(at(markOf(sb)), "b"))}
      </svg>
      <span class="dncap top">${esc(r.top)}</span>
      ${title}
      <span class="dncap zero">0</span>
      ${labels(va, sa, "a")}${labels(vb, sb, "b")}
    </div>`);
}

// --- the match, as a win-probability curve -------------------------------------------------
// What replaces the charted-history pyramid when the match in front of the panel is itself
// charted. The pyramid answers "how much of these two players does the charting have"; once
// this match is charted that question is settled for the one match being looked at, and the
// question worth the same space is how the match actually went.
//
// Diverging about the halfway line rather than a single line climbing an axis, because the
// quantity has a neutral: 50% is the midpoint the swing happens around, and which side of it
// the curve sits on is the thing being read. Above the line the fill is player A's colour and
// below it player B's — the same two the header rule, the coverage bars and every card cap in
// the panel already use for these two players, so the split needs no legend to be read. They
// carry ΔE 26 apart under protanopia and 32 under normal vision against this surface, and
// unlike --acc they don't move with the tournament theme.
//
// The curve opens on career form rather than at even odds. Anchored at 50% it would be
// claiming every match starts a coin toss, and the gap between where the two players' charted
// records put the match and where it ended up is most of what the drawing has to say.
//
// Strokes are non-scaling, so every width below is CSS pixels at any panel width — a viewBox
// unit here is not a pixel, and the box is stretched across whatever the panel gives it.
const WP_W = 720, WP_H = 168, WP_MID = WP_H / 2;

function wpPath(curve) {
  const n = curve.length;
  const x = (i) => (n < 2 ? 0 : (i / (n - 1)) * WP_W);
  // Player B climbs. The curve carries A's probability, so A's certainty is the *bottom*
  // of the box: the scoreline above the chart stacks B's row over A's, and a drawing whose
  // high side belonged to the lower name made the reader flip the panel over in their head
  // to read it. Every other two-player mark in the panel takes its order from that header.
  const y = (wp) => clamp01(Number(wp)) * WP_H;
  const line = curve.map((c, i) => `${i ? "L" : "M"}${x(i).toFixed(2)},${y(c[1]).toFixed(2)}`).join("");
  // The area is the same run of points closed back along the midline, so the two clipped
  // copies of it below meet exactly on the line rather than overlapping by a hairline.
  const area = `M${x(0).toFixed(2)},${WP_MID}L${line.slice(1)}` +
    `L${x(n - 1).toFixed(2)},${WP_MID}Z`;
  return { line, area, x, y };
}

function wpChart(det, a, b) {
  const w = det && det.wp;
  if (!w || !w.curve || w.curve.length < 2) return "";
  // Who won, from the draw rather than from the charting. The sidecar infers it from the
  // last charted point, which is right whenever a match ends by someone winning one — and
  // wrong when it ends any other way. A retirement is the case: Musetti led Djokovic two
  // sets to love in the 2026 Australian Open quarter-final and retired, so the draw's
  // winner is the player two sets down, and no reading of the point record says so.
  // The feed carries the result on every charted match the site holds.
  const won = a.winner === true ? 1 : b.winner === true ? 2 : w.won;
  const { line, area, x, y } = wpPath(w.curve);
  const n = w.curve.length;
  // Set boundaries as rules on the plot. They are the only structure the horizontal axis
  // has that a reader already knows how to use — "the third set" is a place, "point 210"
  // is not — so they are ruled and the point index is left to the readout.
  const idxOf = (pt) => w.curve.findIndex((c) => c[0] >= pt);
  const bounds = (w.sets || []).map(idxOf).filter((i) => i > 0);
  const rules = bounds.map((i) => `<line class="wpset" x1="${x(i).toFixed(2)}" y1="0"
      x2="${x(i).toFixed(2)}" y2="${WP_H}" vector-effect="non-scaling-stroke"/>`).join("");
  // The rules are the only structure the horizontal run has that a reader already knows how
  // to use, and unlabelled they only say "something changed here". Named, the axis becomes
  // the thing a reader navigates by: "the third set" is a place on this chart, where "point
  // 210" is a number they would have to count out.
  //
  // Each label is centred in its own band, in percent of the plot, so it lands with its set
  // however long that set ran and whatever width the panel is. A set is a span rather than a
  // tick — the boundary belongs to neither of the sets it separates — so the label sits
  // between two edges rather than on one.
  const edges = [0, ...bounds, n - 1];
  const setLabels = edges.slice(0, -1).map((start, k) => {
    const mid = n < 2 ? 0 : ((start + edges[k + 1]) / 2) / (n - 1) * 100;
    return `<span class="wpsetn" style="left:${mid.toFixed(2)}%">set ${k + 1}</span>`;
  }).join("");
  // Where it ended. Every wp in the list is the state *before* a point is played, so the
  // last one is not the result — the result is the sidecar's own `won`, and the curve is
  // carried the last step to 0 or 1 rather than left hanging at the final serve.
  const endY = won === 1 ? WP_H : 0;
  const endX = WP_W;
  const winner = won === 1 ? a : b;
  // Quoted for the player the chart climbs toward, so "higher" and "more likely" agree.
  // The stored curve is A's probability throughout; B's is its complement.
  const pre = Math.round((1 - Number(w.pre)) * 100);
  return `<div class="wp" data-n="${n}">
    <div class="wpplot">
      <svg viewBox="0 0 ${WP_W} ${WP_H}" preserveAspectRatio="none" role="img"
        aria-label="${esc(`Win probability through the match: ${b.name} started at ${pre}%, ${winner.name} won`)}">
        <defs>
          <clipPath id="wpup"><rect x="0" y="0" width="${WP_W}" height="${WP_MID}"/></clipPath>
          <clipPath id="wpdn"><rect x="0" y="${WP_MID}" width="${WP_W}" height="${WP_MID}"/></clipPath>
        </defs>
        <path class="wpfill fb" d="${area}" clip-path="url(#wpup)"/>
        <path class="wpfill fa" d="${area}" clip-path="url(#wpdn)"/>
        ${rules}
        <line class="wphalf" x1="0" y1="${WP_MID}" x2="${WP_W}" y2="${WP_MID}"
          vector-effect="non-scaling-stroke"/>
        <path class="wpline" d="${line}" vector-effect="non-scaling-stroke"/>
        <path class="wpline wptail" d="M${x(n - 1).toFixed(2)},${y(w.curve[n - 1][1]).toFixed(2)}L${endX},${endY}"
          vector-effect="non-scaling-stroke"/>
        <line class="wpcross" x1="0" y1="0" x2="0" y2="${WP_H}" vector-effect="non-scaling-stroke"/>
      </svg>
      ${/* The marker is an HTML element placed in percent, not an SVG circle. The box is
           stretched to whatever width the panel gives it (preserveAspectRatio="none"), which
           stretches the coordinate system with it — strokes survive that because they are
           non-scaling, but a circle would come out an ellipse at every width but one. A
           percentage of the plot resolves in real pixels, which is the same arithmetic the
           coverage band does for the same reason. */""}
      <span class="wpdot"></span>
      <span class="wpcap top">${esc(shortName(b.name))}</span>
      <span class="wpcap bot">${esc(shortName(a.name))}</span>
    </div>
    <div class="wpaxis">${setLabels}</div>
    <p class="wpread"><span class="wprl">before a ball was struck</span>
      <b>${pre}%</b> <span class="wprn">${esc(shortName(b.name))}</span></p>
  </div>`;
}

// Surname alone. The chart's captions and its readout are set against the plot at 10-11px
// and repeat every time the pointer moves; the header two inches above is where the full
// names are, and a reader does not need them twice.
const shortName = (name) => last(name || "") || String(name || "");

// The crosshair. A line chart in a browser is an interactive thing whether or not it is
// built as one, and the reader's question at any point of the curve — what was the score
// here, who was ahead — is answered by the drawing only within about five percent. Wired
// after render, on the fresh nodes, so it goes when the panel body is replaced.
//
// Pointer events rather than mouse ones, so a touch drag scrubs the curve on a phone. The
// plot keeps its own last index so a re-entering pointer doesn't flash the pre-match state.
function wireWpChart(root) {
  const wrap = root.querySelector(".wp");
  if (!wrap) return;
  const plot = wrap.querySelector(".wpplot"), svg = wrap.querySelector("svg");
  const read = wrap.querySelector(".wpread");
  const cross = wrap.querySelector(".wpcross"), dot = wrap.querySelector(".wpdot");
  // The oriented copy, handed over by the caller — _details holds the raw one, which is
  // the wrong way round for half of all matches.
  const w = root._wp;
  if (!w) return;
  const curve = w.curve, n = curve.length;
  const home = read.innerHTML;
  const topName = read.querySelector(".wprn").textContent;
  const { x, y } = wpPath(curve);
  // Which set a point index falls in, from the same boundaries the rules are drawn at.
  const setOf = (i) => (w.sets || []).filter((pt) => curve[i][0] >= pt).length + 1;
  const move = (ev) => {
    const box = plot.getBoundingClientRect();
    if (!box.width) return;
    const f = clamp01((ev.clientX - box.left) / box.width);
    const i = Math.min(n - 1, Math.round(f * (n - 1)));
    const wp = Number(curve[i][1]);
    cross.setAttribute("x1", x(i).toFixed(2));
    cross.setAttribute("x2", x(i).toFixed(2));
    dot.style.left = `${((n < 2 ? 0 : i / (n - 1)) * 100).toFixed(3)}%`;
    dot.style.top = `${(clamp01(wp) * 100).toFixed(3)}%`;
    wrap.classList.add("live");
    read.innerHTML = `<span class="wprl">set ${setOf(i)}, point ${curve[i][0]}</span>
      <b>${Math.round((1 - wp) * 100)}%</b> <span class="wprn">${esc(topName)}</span>`;
  };
  const rest = () => {
    wrap.classList.remove("live");
    read.innerHTML = home;
  };
  svg.addEventListener("pointermove", move);
  svg.addEventListener("pointerdown", move);
  svg.addEventListener("pointerleave", rest);
}

// --- charted history, as a pyramid ---------------------------------------------------------
// How much of each player the charting actually has, under the title that names what these
// counts are. An uncharted player is the site's whole invitation, so the ask sits here too
// rather than only in the empty columns below.
//
// No name and no flag: the scroll-locked match header above carries those, and each side of
// this band is the same player in the same position. The player colours (--a / --b) are
// declared by the split rule under that header, its left half player A and its right half
// player B; the rule across the top of this band is the same one, and it is the same mark
// that caps each column further down.
//
// "2015–2024: 61 matches" is a span and a total, and a span and a total cannot tell those two
// apart: sixty matches in one breakout season, or six a year for ten. They read the same on the
// line and they are not the same denominator — the first is a snapshot of one year's form
// wearing a decade's date range, and every pattern, trigger and rate in the panel below is
// drawn from it. So the counts get a shape as well as a sum: one row per season, each player's
// bar the points charted in it, running out from a shared centre.
//
// One time axis down the middle, both players hung off it, rather than a strip per player side
// by side. Two strips put the same year at two places on the screen ~400px apart, so comparing
// a season meant carrying a bar's height across the gap; they also spent four labels printing
// the same two end years twice, and had room for no label in between — the exact year behind a
// bar was reachable only by hovering it, which on a phone means not at all. Turned on its side
// the axis is a column of its own, every season named in it, and the two players' bars for a
// season are adjacent and share a baseline. Length off a common edge is the comparison the eye
// is best at, and it is the one the reader actually wants here.
//
// It also trades the scarce dimension for the cheap one. Width is what a phone has least of and
// the strips needed two columns of it; height is what a panel five screens tall has plenty of.
//
// Points rather than matches, because points are what the rest of the panel is actually built
// out of — a trigger needs strokes, not fixtures — and a three-setter and a five-setter are one
// match each. The match count is the number people say out loud, so it rides in each bar's
// readout rather than being lost.
//
// Both players are drawn on one domain and one length scale, set across the pair. Two charts
// each fitted to their own data would put a lightly-charted player's best season at the same
// length as a heavily-charted one's, in a band whose whole subject is that the two are not
// equally known.
function yearScale(...rowsets) {
  let lo = Infinity, hi = -Infinity, max = 0;
  for (const rows of rowsets) {
    for (const r of rows || []) {
      const y = Number(r.year);
      if (!Number.isFinite(y)) continue;
      if (y < lo) lo = y;
      if (y > hi) hi = y;
      max = Math.max(max, Number(r.points) || 0);
    }
  }
  return lo <= hi && max > 0 ? { lo, hi, max } : null;
}

// Where the rulers go. Without one, a bar is only ever as long as its neighbour and the band
// can say "more" but never "how much" — and the readout, which can, is a press away. Three
// hairlines down each half give every bar lengths to be read against.
//
// A quarter, half and three-quarters of the busiest bar: evenly spaced, always three, always
// reaching toward the tip. The figures under them are those points rounded to two significant
// figures (see kfmt) — the ruler is meant to be about right, and the exact count of any bar
// is a tap away.
const rulersAt = (max) => (max > 0 ? [0.25, 0.5, 0.75].map((f) => max * f) : []);

// A ruler's figure: its value to two significant figures, then shortened — 2352 -> "2.4k",
// 446 -> "450". Not an exact count of anything; the readout carries those.
function kfmt(n) {
  const mag = Math.pow(10, Math.floor(Math.log10(n)) - 1);
  const r = Math.round(n / mag) * mag;
  return r >= 1000 ? `${r / 1000}k` : `${r}`;
}

// One season's bar for one player. A season with no charted match draws nothing at all, but
// its row is still there — the axis runs top to bottom in even year steps, so a blank row is
// a year the charting missed, sitting at its right place between the seasons that have bars.
// That gap is the finding on a player the charting picked up late or let go of for a while.
//
// Length is a percentage of the row's half, floored in CSS rather than here (see .covbar i) so
// the floor is a pixel count and not a share of whatever width the half happens to be. Without
// it a season of one charted match against a peak of nine thousand points draws two thirds of a
// pixel, and "barely charted" and "not charted at all" become the same mark — which is the one
// distinction this chart exists to make.
//
// `segs` is that season's matches as point counts, in the order they were played (see
// coverPyramid). A season of more than one is drawn as that many blocks end to end, the
// first match against the centre axis and the season running out toward the tip, each block
// a hairline of grey apart — so the same bar now also shows whether a year was
// one long match or six short ones, and roughly when in the year the charting was busy. The
// blocks only divide the length the solid bar already had: only the first is floored (see
// `.covbar > i`), so splitting a season never stretches it past its points and the pyramid
// keeps its outline. Below SEG_MIN_PCT of the peak the cuts would be sub-pixel, so it stays
// one block and the count rides in the readout as before.
const SEG_MIN_PCT = 2;
function coverBar(r, sc, tag, segs) {
  if (!r) return `<span class="covbar ${tag}"></span>`;
  const pts = Number(r.points) || 0, mt = Number(r.matches) || 0;
  // `title` is a mouse affordance; `data-lbl` carries the same string to a readout that opens
  // on hover, on press, and on tap (see .covbar[data-lbl] in the stylesheet and onCovTap), so
  // a thumb can get at it. The bars stay out of the tab order deliberately — a thirty-season
  // career would otherwise put sixty stops inside a modal.
  //
  // It leads with the year. The axis names only its first and last season, so for every one
  // between them this readout is the only place the year is written. Then the match count —
  // the number people say out loud, and the one thing the drawing cannot show — and the point
  // total the bar is drawn from.
  //
  // The readout hangs on the half rather than on the bar it names: a bar is eight pixels of
  // height and some seasons are three of length, which is not a thing a thumb can be asked to
  // land on. The half is the row's full height and the width of a column, it belongs to one
  // player throughout, and pressing anywhere along a season's left side asks about A's season.
  const lbl = `${r.year} · ${mt} ${mt === 1 ? "match" : "matches"} · ${pts.toLocaleString()} points`;
  // Blocks run left to right in the DOM; flex packs them against the centre axis (A to its
  // right edge, B to its left). `segs` arrives oldest match first, so B is drawn as-is and A
  // is reversed — either way the first match of the season sits on the axis and the year runs
  // out toward the tip, the same direction on both sides. One block below the threshold, or
  // when the per-match list is missing (an older insights db), and it is the single floored
  // bar it always was.
  const wide = segs && segs.length > 1 && (pts / sc.max) * 100 >= SEG_MIN_PCT;
  const parts = wide ? (tag === "a" ? segs.slice().reverse() : segs) : [pts];
  const bars = parts
    .map((p) => `<i style="width:${(p / sc.max * 100).toFixed(2)}%"></i>`).join("");
  return `<span class="covbar ${tag}" title="${esc(lbl)}" data-lbl="${esc(lbl)}">${bars}</span>`;
}

// The busiest season, for the description a screen reader gets — where the drawing says nothing.
function peakOf(d) {
  let best = null;
  for (const r of (d && d.years) || []) {
    const pts = Number(r.points) || 0;
    if (!best || pts > best.pts) best = { y: Number(r.year), pts, mt: Number(r.matches) || 0 };
  }
  return best;
}

// Each side's totals, hung on its own outer edge — how much of the player exists in the data,
// not how much tennis they have played, which is what the title above and the note at the foot
// of the panel are for.
//
// Singular where it is one. This line is at its most conspicuous on exactly the player it reads
// worst for: a qualifier with a single charted match got "1 matches" at the top of a panel
// whose entire subject is how little is known about them.
//
// No date range on this line. The axis is the date range, and it labels every year of its
// length. Printed here as well it would be a second span a few pixels above a different one —
// the axis spans *both* players, so a player charted from 2014 sits under a "2013" — and two
// ranges that near each other read as a contradiction rather than as two facts. The one case
// that needs it is a build with no player_years table at all, which never reaches here.
function coverSum(d, tag) {
  if (!d) {
    return `<span class="covsum ${tag}">not charted yet —
      <a href="${CHART_GUIDE}" target="_blank" rel="noopener">chart a match →</a></span>`;
  }
  const mt = Number(d.s.matches_charted) || 0;
  return `<span class="covsum ${tag}">${mt} ${mt === 1 ? "match" : "matches"} ·
    ${Number(d.s.points_charted).toLocaleString()} points</span>`;
}

// Newest season at the top. A career's early seasons are the thin ones and the shared axis
// stretches to whichever player started first, so the rows that are empty on one side or both
// collect at the far end of the axis from "now" — at the bottom they trail off, and at the top
// they would stand between the reader and the seasons every rate below is actually drawn from.
// On a phone that is the difference between the current season being the first row and it being
// a scroll away.
//
// The axis is two labels, not a column: the newest year over the midline, the oldest under it,
// and the two players' bars meeting at that midline with nothing between them. Every year
// between the ends is still a row in even steps, so height is the date — a reader finds a
// season by where it sits on the run from top to bottom, and the exact year is in the readout.
function coverPyramid(da, db, sc) {
  const by = (d) => new Map(((d && d.years) || []).map((r) => [Number(r.year), r]));
  // Each season's matches as a list of point counts, so coverBar can split that year's bar
  // into a block apiece. In play order (the query sorts by seq) and absent on an older
  // insights db, where every season falls back to one solid block.
  const bySeg = (d) => {
    const m = new Map();
    for (const r of (d && d.ymatches) || []) {
      const y = Number(r.year);
      if (!m.has(y)) m.set(y, []);
      m.get(y).push(Number(r.points) || 0);
    }
    return m;
  };
  const A = by(da), B = by(db), Aseg = bySeg(da), Bseg = bySeg(db);
  const rows = [];
  for (let y = sc.hi; y >= sc.lo; y--) {
    rows.push(`<div class="covrow">${coverBar(A.get(y), sc, "a", Aseg.get(y))}${coverBar(B.get(y), sc, "b", Bseg.get(y))}</div>`);
  }
  // Three gridlines per half, at a quarter, half and three-quarters of the peak (see
  // rulersAt). Each line and the figure under it are placed by the same inline offset — a
  // percentage of the half — so the type can't drift off the rule it names.
  const ticks = rulersAt(sc.max);
  // Only over a half that has something in it. A player the charting has never reached gets an
  // empty half, and tick marks down the middle of it with figures under them are a scale
  // offered for nothing — the emptiness is the finding and it does not need one.
  const on = (d) => !!(ticks.length && d && d.years && d.years.length);
  // dir: -1 draws player A's half, out to the left of the midline; +1 draws B's, to the right.
  const at = (v, dir) => 50 + dir * (v / sc.max * 50);
  const marks = (d, tag, dir) => on(d)
    ? ticks.map((v) => `<i class="covrule ${tag}" style="left:${at(v, dir).toFixed(2)}%"></i>`).join("")
    : "";
  const scale = (d, tag, dir) => on(d)
    ? ticks.map((v) => `<span class="${tag}" style="left:${at(v, dir).toFixed(2)}%">${kfmt(v)}</span>`).join("")
    : "";
  const ruler = marks(da, "a", -1) + marks(db, "b", 1);
  // The tick figures under each half, both sides, no unit word — the title above the band
  // already says these are points, and "points" printed twice more here is a label the chart
  // can be read without.
  const foot = ruler
    ? `<p class="covfoot">${scale(da, "a", -1)}${scale(db, "b", 1)}</p>` : "";
  const say = [`charted points by season, ${sc.lo} to ${sc.hi}`]
    .concat([[da, "left"], [db, "right"]].map(([d, side]) => {
      const p = peakOf(d);
      return p ? `${last(d.s.player)}, ${side}: busiest ${p.y}, ${p.mt} ${p.mt === 1 ? "match" : "matches"}` : "";
    }).filter(Boolean)).join("; ");
  // A season is a row of ~13px and thirty of them is a chart taller than the phone it is on.
  // Past eighteen the rows step down rather than the chart being cut short or scrolled inside
  // itself — every season the axis spans still holds a row.
  const dense = sc.hi - sc.lo + 1 > 18 ? " dense" : "";
  return `<div class="cov${dense}">
    <b class="covend hi" aria-hidden="true">${sc.hi}</b>
    <div class="covgrid" role="img" aria-label="${esc(say)}">${ruler}${rows.join("")}</div>
    <b class="covend lo" aria-hidden="true">${sc.lo}</b>
    ${foot}</div>`;
}

// Without a player_years table — a build too old to have one — there is no axis to carry the
// span, so the summary line says it itself. This is the only place that range still prints.
function coverPlain(d, tag) {
  if (!d) return coverSum(null, tag);
  const s = d.s, mt = Number(s.matches_charted) || 0;
  const span = s.year_min == null ? ""
    : (s.year_min === s.year_max ? `${s.year_min}: ` : `${s.year_min}–${s.year_max}: `);
  return `<span class="covsum ${tag}">${span}${mt} ${mt === 1 ? "match" : "matches"} ·
    ${Number(s.points_charted).toLocaleString()} points</span>`;
}

function profileBand(da, db) {
  if (!da && !db) return "";
  // The scale is computed once, over both players, and handed down — so neither side can
  // quietly draw itself against a different axis than the other.
  const sc = yearScale(da && da.years, db && db.years);
  const head = sc ? coverSum(da, "a") + coverSum(db, "b")
    : coverPlain(da, "a") + coverPlain(db, "b");
  return `<div class="pband">
    <p class="covtop">${head}</p>
    ${sc ? coverPyramid(da, db, sc) : ""}</div>`;
}

// The per-player figures the two style columns print: what this player is, as numbers, rather
// than what the two of them did to each other. Each belongs with the player, which is why they
// sit in the columns and not on the ring between them.
//
// Bits and rates alike are drawn against the band the middle half of the tour occupies, quoted
// once in the definitions the section can open (see figureKey) rather than restated beside
// every figure.
//
// Kept as a list because everything downstream wants the same things — the key, how to print
// it, what to call it — and a second copy of "times 100, one decimal" in the definitions is
// the copy that drifts.
//
// The serve's own three figures are not here: 1st serves in, 2nd serves in and double faults
// are one measurement on three denominators, which is a thing a drawing says in one shape and
// a column of figures cannot — see serveSplit().
//
// A figure's value for one player: the column the figure names, off that player's row.
const figOf = (f, s) => (!s ? null : num(s[f.k]));

// `better` marks the figures with a right side, so the phone comparison can set the winner in
// ink and let the other go quiet. Variety and rally length have no better end and stay level.
const FIGS = [
  {
    k: "bits", label: "variety", unit: "bits", band: "bits",
    fmt: (v) => v.toFixed(1),
  },
  // The shot mix, as four figures in the column. They are the last thing about how a player
  // plays rather than what they won with it, so they sit under variety and ahead of the
  // outright win below them — the column then runs style, then choice, then outcome.
  //
  // `den` names the count a *match* reading was divided by, printed under the figure as its
  // note. A match is a small enough window that the denominator is part of the figure: 33% of
  // three net shots and 33% of thirty are the same number and not the same fact. Only the mix
  // figures carry it, because only they are taken over a count that can be that small — an
  // ace rate on a charted match has every service point behind it.
  //
  // The slice is a share and no outcomes. Neither of its rates is steady enough to draw, and
  // what its misses cost is already in the groundstroke square, charged to the hand that
  // played the ball — see build_insights._shot_mix.
  {
    k: "slice_pct", label: "slice share", unit: "", band: "slice_pct",
    fmt: pct, den: "shots",
  },
  {
    k: "net_pct", label: "net share", unit: "", band: "net_pct",
    fmt: pct, den: "shots",
  },
  // Both ends of the net shot, in the order the wing rates in the groundstroke square run. Coming
  // forward is worth it and is a risk, and the two rates are all but uncorrelated (r = -0.00),
  // so neither is recoverable from the other and the panel has to print both.
  {
    k: "net_winner_pct", label: "net winner rate", unit: "", band: "net_winner_pct",
    fmt: pct, better: "hi", den: "net_shots",
  },
  {
    k: "net_err_pct", label: "net error rate", unit: "", band: "net_err_pct",
    fmt: pct, better: "lo", den: "net_shots",
  },
  // Return winners: a point the returner took without playing it out, over every point they
  // returned, which is how it is normally quoted. The other outright win — the ace rate — is
  // on the serve plot now, pooled under the two cores it splits into, so the column carries
  // the return end and the plot carries the serve end.
  //
  // It is also the one figure on this panel that says something the serve does not: it
  // correlates 0.03 (men) and -0.01 (women) with return points won, where an ace rate largely
  // explains why a server wins the ones they do.
  {
    k: "ret_winner_rate", label: "return winners", unit: "", band: "ret_winner_rate",
    fmt: pct, better: "hi",
  },
  // No "shot selection" figure (sigma) ships. It correlates -0.81 (men) / -0.59 (women) with
  // rally length, two thirds of the men's spread is the player's own baseline aggressive shot
  // frequency — which the triggers section prints in plain percent further down — and the top
  // of its leaderboard is a serve-volley artifact: restricted to rally-only lead-ups Rafter
  // falls from 14.9pp, top of the tour, to a below-median 3.8pp. It is also independent of
  // whether the extra aggression pays (rho = -0.07 with trap count), so one number described
  // an adaptive player and a baited one identically. The triggers section answers the same
  // question concretely and with a direction.
];

// --- the serve, as a two-axis plot -------------------------------------------------------
// Every service point a player played, on two axes at once. Across is how often a delivery
// happens: the first serves that landed, then the second serves that landed, then the double
// faults where neither did — three parts that account for every service point, running outward
// from the midline in the order a point reaches them. Up is what that delivery won, as a share
// of its own column.
//
// The two axes are the reason it is not a stacked bar. On one axis a block can only show its
// share of the bar, and not one of these rates is that: how often the first serve went in and
// how often it won once it did are different questions on different denominators, and a single
// stack has to pick one of them and leave the other to a printed figure. Given a width and a
// height it carries both — and the area of the shaded part comes out as a quantity in its own
// right, the player's share of every service point they played:
//
//   area = w1·h1 + w2·h2 + w3·0 = first_won/n + second_won/n = serve points won
//
// The deepened part inside it is the same identity again, one level down: the two ace cores
// are shares of their own columns, so together they come to every ace over every service
// point — which is the pooled ace rate printed in the style column beside the ring.
//
//   deep = w1·a1 + w2·a2 = (aces on 1st + aces on 2nd)/n = ace rate
//
// The first holds to 1.1e-16 everywhere, and so does the second on a charted match, where all
// four counts come out of one walk over the notation. On a career the second is close rather
// than exact — a hundredth of a point for the median player and four hundredths at the 95th —
// because the ace total is counted off the charted stats and the split off the parsed points,
// and 3% of points do not parse. The two counts disagree most for the players charted before
// the notation settled: the worst case is 1.2 points, on a player only 77% of whose points
// parse.
//
// They are properties of the drawing rather than marks on it: no rule is drawn across the plot
// to say either, which would be a line and a label spent on a number the panel is not
// otherwise short of.
//
// The second-serve column is the second serves that *landed*, so its rate is over those rather
// than over every point that reached a second serve — which is the rate a scoreboard quotes.
// The two differ by the double faults, and they have to: a double fault is its own column here,
// and counting it in the one beside it as well would put those points on the plot twice. Both
// are printed, one as the column's height and one as its own row.
//
// `a` is the part of that column's fill the serve took outright — the aces, as a share of the
// same denominator the fill's own height is on. It is a subset of what the delivery won, so it
// rises from the floor inside the fill rather than sitting beside it, and the two columns
// answer the question the pooled ace rate cannot: a first serve is hit to be unreturnable and
// a second one is not, and the two rates run about an order of magnitude apart.
//
// Clamped to the fill it sits in. The career path takes its heights from the charted stats
// totals and its ace shares from the parsed notation, and the two agree to well within a
// percentage point across all 819 careers — but they are two counts of the same points, and a
// core drawn taller than the fill it is a part of would be a drawing contradicting itself.
function serveSplit(s) {
  if (!s) return null;
  const band = (h, r, a, hn, hd, rn, rd, an) => ({ h, r, a: Math.min(a || 0, r), hn, hd, rn, rd, an });
  const n = num(s.serve_pts);
  // A charted match: the tallies themselves, and the plot is a count of what happened.
  if (n && s.first_in != null && s.first_won != null && s.second_won != null) {
    const fi = Number(s.first_in), fw = Number(s.first_won);
    const df = Number(s.dfs), si = Number(s.second_pts) - df, sw = Number(s.second_won);
    // The ace split is absent from sidecars written before it was counted; the cores then go
    // undrawn and the rest of the plot is unaffected.
    const a1 = num(s.aces_first) || 0, a2 = num(s.aces_second) || 0;
    if (fi < 0 || si < 0 || fw > fi || sw > si) return null;
    return {
      n, counts: true,
      bands: [band(fi / n, fi ? fw / fi : 0, fi ? a1 / fi : 0, fi, n, fw, fi, a1),
      band(si / n, si ? sw / si : 0, si ? a2 / si : 0, si, n, sw, si, a2),
      band(df / n, 0, 0, df, n, 0, df, 0)],
      // Kept beside the band rates because it is the figure a scoreboard quotes and the one a
      // reader arrives with — see the note above on why it is not the band's own width.
      second_in: si + df ? si / (si + df) : null,
    };
  }
  // A career: the same three bands, recovered from the four rates. Each is a product of shares
  // that sit on the denominator above it, so the three heights sum to one without being
  // renormalised. The second band's own win rate is the one figure that has to be divided back
  // out — the shipped rate is over every point that reached a second serve, and the band is
  // only the ones that landed. It cannot exceed one: a double fault is never a point won, so
  // the numerator of the first is a subset of the numerator of the second.
  const fi = num(s.first_in_pct), fwp = num(s.first_won_pct);
  const si = num(s.second_in_pct), swp = num(s.second_won_pct);
  if ([fi, fwp, si, swp].some((x) => x == null)) return null;
  // The ace shares ship on the same two denominators as the win rates beside them, so the
  // second one is divided back out by second_in_pct the same way — see build_insights
  // ._SERVE_ACE_SQL. Null on a build that predates them, and the cores go undrawn.
  const fap = num(s.first_ace_pct), sap = num(s.second_ace_pct);
  const second = 1 - fi;
  return {
    n: null, counts: false,
    bands: [band(fi, fwp, fap),
    band(second * si, si ? Math.min(1, swp / si) : 0,
      si && sap != null ? Math.min(1, sap / si) : 0),
    band(second * (1 - si), 0, 0)],
    second_in: si,
  };
}

// The three columns, ordered outward from the midline: the first serve against it, the second
// serve beyond that, the double faults at the far end. Widest nearest the centre, so the two
// players' first serves meet along the midline and are read against each other directly, and
// the band that is four per cent of a service game sits where it costs nothing.
const SVBAND = ["first", "second", "df"];
// What each column is, for the tooltip that carries its counts.
const SVSAY = ["1st serves in", "2nd serves in", "double faults"];
// The width the gaps between columns cost, always reserved for all three whether or not all
// three are drawn. A plot with no double faults has one gap fewer to draw, and measuring its
// columns against the width *its own* gaps leave would put it on a frequency axis 1.2% wider
// than its opponent's — on a drawing whose whole point is reading two of them against each
// other. Reserved, every plot shares one scale, and a player who never double-faulted leaves
// the two pixels at the far end of theirs empty.
const SV_GAPS = 4;
// The height a two-line figure needs to sit inside a band, as a share of the plot's height —
// under it the figure stands above that band's top instead. 24px of a 112px plot, which is the
// shortest the square plot gets: it is as tall as it is wide, and half a phone panel is wider
// than that. Taller plots only send a figure outside its band a little earlier than they had
// to, and above the band is a place it always fits.
//
// Two figures are placed by it, and they are not the same height: the win rate against its
// fill at 24px, and the ace share against its core inside that fill at 21px, a tier smaller.
// Both are set a little over what they measure — 22.4px and 19.5px on the narrowest phone —
// so the swap happens a pixel early rather than a pixel late.
const SV_FIG_H = 24 / 112;
const SV_ACE_H = 21 / 112;

// One player's plot. Each column spans the full height in the drained tone, so its own extent
// is the axis its fill is read against — the ring's vocabulary, where the player's colour is
// what they won and the same colour drained is what they did not. Every column stands on the
// same baseline and both players' plots share it, so a fill height means the same thing
// anywhere on the drawing.
//
// Mirrored about the midline: A's columns run leftward from it and B's rightward, both from
// the same origin, the way the two arcs leave the foot of a ring and climb opposite sides. The
// mirror is where a plot sits and which way it runs — the columns are in the same order on
// both sides, because reflecting that would make the two incomparable.
//
// Everything is measured from the plot's *outer* edge, which makes the two sides one set of
// numbers: the double faults are the first slice of that measure on both, the second serve the
// next, the first serve the rest. Only which edge the CSS hangs them off differs.
//
// svGeom.at() is a distance along the plot from its outer edge, in the units the columns are
// laid out in: the share of the width the gaps leave, plus the whole gaps already passed. It
// places each figure's centre (--c) over its own column.
//
// The gap reserve is for three columns; a plot missing one draws one gap fewer and has two
// pixels of slack. Both plots pack toward the midline, so the slack always falls at the outer
// edge — which is the edge every distance here is measured from, so every figure carries it.
// gp() is how many gaps a point sits past, one for each column drawn outside it: not a constant
// per column, because a player with no double faults has no gap after that column either, and
// assuming the full three puts every figure two pixels off its column.
function svGeom(sp) {
  const slack = (3 - sp.bands.filter((x) => x.h).length) * 2;
  return {
    at: (share, gapsPassed) =>
      `calc((100% - ${SV_GAPS}px) * ${share.toFixed(5)} + ${gapsPassed * 2 + slack}px)`,
    gp: (k) => sp.bands.slice(k + 1).filter((x) => x.h).length,
  };
}

// The word for the double-faults column, long form and the short one a narrow block swaps in.
const DF_KEY = '<span class="svlong">double</span><span class="svabbr">dbl</span> faults';

// The pooled ace rate: aces over every service point, which is the two cores added back
// together — (first_share x first_ace) + (second_share x second_ace). It is the figure a
// scoreboard quotes and the one this panel used to carry beside variety; here it sits under
// the plot, braced to the two cores it is the sum of, so the split above and the total
// below are the same quantity at two grains.
const acePooled = (sp) =>
  sp.bands[0].h * sp.bands[0].a + sp.bands[1].h * sp.bands[1].a;

function serveBar(sp, tag, cmp) {
  if (!sp) return `<div class="svcol ${tag} empty"></div>`;
  if (!sp.bands.some((x) => x.h)) return `<div class="svcol ${tag} empty"></div>`;
  const { at, gp } = svGeom(sp);
  const cols = [0, 1, 2].map((i) => {
    const x = sp.bands[i];
    if (!x.h) return "";
    const aces = !x.a ? "" : sp.counts
      ? `, ${x.an} of those aces` : `, ${pct(x.a)} of them aces`;
    const say = (sp.counts
      ? `${x.hn} of ${x.hd} service points — ${SVSAY[i]}, ${x.rn} of ${x.rd} won`
      : `${pct(x.h)} of service points — ${SVSAY[i]}, ${pct(x.r)} won`) + aces;
    // The win rate rides on the column it belongs to on a narrow block, where there is no
    // margin to stand it in: set on the fill, at the fill's own top, so the figure is at the
    // height it names and needs no leader to say so. Nothing for the double faults, whose
    // height is nought by construction and not a rate anyone read.
    //
    // Under a short fill it sits above the top instead, in ink on the drained tone rather than
    // in the card colour on the fill. One of the two always has the room: the fill and the
    // drain are 112px between them and the figure needs 24 of it.
    //
    // Where the ace core reaches almost the whole of the fill there is no room between the two
    // figures, and the ace figure rides inside this one as a third line rather than standing
    // on a mark a few pixels below it — see svAce().
    //
    // A tucked pair always goes above the fill, whether or not the fill alone had the room for
    // one figure. Two figures reading down from the fill's top need twice the room, and the
    // tuck only happens when the win rate is under twice this threshold — so inside the fill
    // is exactly where the stack does not fit, and the second line would land on the drained
    // tone in the card's own colour, which is nothing at all.
    const ace = svAce(x, i, tag, cmp);
    const won = i < 2
      ? `<b class="svwin${x.r < SV_FIG_H || ace.tucked ? " over" : ""}${sup(cmp, `w${i}`, tag)}">${pct(x.r)}<em>won</em>${ace.tucked}</b>` : "";
    return `<span class="svseg ${SVBAND[i]}"
      style="--w:calc((100% - ${SV_GAPS}px) * ${x.h.toFixed(5)});--f:${(x.r * 100).toFixed(2)}%;--ace:${(x.a * 100).toFixed(2)}%"
      title="${esc(say)}"><i class="svfill"></i>${ace.core}${won}${ace.fig}</span>`;
  }).join("");
  // The double-faults figure belongs to the hatch column at the plot's outer edge, so it is
  // drawn with the plot rather than in the row of figures below: turned on its side and run
  // along that column on a wide block, dropped under it with a hairline to the middle of its
  // edge on a narrow one. --dfm is that midpoint, measured from the plot's outer edge.
  const df = sp.bands[2];
  const dfLab = `<b class="svdf${sup(cmp, "df", tag)}" style="--dfm:${at(df.h / 2, 0)}"
    >${pct(df.h)}<em>${DF_KEY}</em></b>`;
  // The pooled ace figure hangs below the plot at --acm (the midpoint of the two core
  // centres), joined to the two ace cores by a pair of hairline tines that leave the figure
  // and meet each core tangent to the vertical — one soft brace, no straight run and no
  // corner. The CSS pulls the first-serve tine in from --acsp (half the core-centre gap) to
  // clear the "1st serves in" label — that core is wide, its centre far under the label. The
  // second-serve tine goes to --acout, a hair inside that core's midline-facing edge: the
  // furthest out it can land and still touch a core that sits wholly under its own label, so
  // that arm reads longer. Both drop a row on the narrow layout so they never share a strip
  // with the double-fault label. Each tine is an <svg> box spanning exactly one figure-to-top
  // gap, so its ends land without any arithmetic here. A serve with no second-serve aces
  // (.one) has one core: the figure sits under it on a straight hairline.
  const c0 = sp.bands[0].a
    ? at(sp.bands[1].h + sp.bands[2].h + sp.bands[0].h / 2, gp(0)) : null;
  const c1 = sp.bands[1].a ? at(sp.bands[2].h + sp.bands[1].h / 2, gp(1)) : null;
  const one = !(c0 && c1);
  const acm = one ? (c0 || c1) : `calc((${c0} + ${c1}) / 2)`;
  const acsp = one ? "0px" : `calc((${c0} - (${c1})) / 2)`;
  // 0.95 of the way across the second-serve band: just inside its midline-facing edge.
  const acout = one ? "" : `;--acout:${at(sp.bands[2].h + sp.bands[1].h * 0.95, gp(1))}`;
  // The two ogees, handed to the side: on A the tine box measures from the left edge and on B
  // from the right, so the "in" tine (figure → first-serve core, against the midline) and the
  // "out" tine (figure → second-serve core, toward the edge) trade their path with the side.
  const tine = (cls, d) =>
    `<svg class="svtn ${cls}" viewBox="0 0 12 12" preserveAspectRatio="none" aria-hidden="true"
      ><path d="${d}" vector-effect="non-scaling-stroke"/></svg>`;
  const tines = one ? "" : tag === "a"
    ? tine("in", "M0 12C0 7 12 5 12 0") + tine("out", "M12 12C12 7 0 5 0 0")
    : tine("in", "M12 12C12 7 0 5 0 0") + tine("out", "M0 12C0 7 12 5 12 0");
  const aceLab = (c0 || c1)
    ? `<div class="svacetot${one ? " one" : ""}${sup(cmp, "atot", tag)}" style="--acm:${acm};--acsp:${acsp}${acout}">
        ${tines}<b>${pct(acePooled(sp))}<em><span class="svlong">total </span>ace rate</em></b></div>`
    : "";
  return `<div class="svcol ${tag}">
    <div class="svplot">${cols}</div>
    ${dfLab}${aceLab}
  </div>`;
}

// The ace core inside one column's fill, and the figure that names it. Returns the three
// pieces separately because the figure has three places it can go and only one of them is
// inside the win figure's own element.
//
// The core is the fill's own colour deepened, which is the mark this panel already uses for a
// point won without playing it out: there is no failed half to drain, so the part that was
// taken outright reads as emphatic rather than the rest reading as faint.
//
// Where the figure goes, in order:
//
//   inside the core   whenever the core is tall enough to hold it, at the core's own top
//   above the core    when it is not, standing on the fill just over the core's top edge
//   in the win figure when there is no room there either, as a third line under "won"
//
// What counts as room above the core is the fill up to its own top, less the win figure's
// reach down from that top — where the win figure is standing inside the fill. Where the fill
// is too short for it and it has gone above, the whole of the fill above the core is clear.
//
// The first two are the same swap .svwin makes for a short fill. The third is for the serve
// that won little it did not ace, where the two figures' own marks are within a line of type
// of each other and standing them on both would overlap them. It reaches 8 of the 819 careers
// the plot draws and 10 of the 484 columns on the matches this site ships. Riding inside the
// win figure's element it inherits its position and its colours, and the pair reads as the
// stack it has become — see serveBar for why that stack always goes above the fill.
function svAce(x, i, tag, cmp) {
  const none = { core: "", fig: "", tucked: "" };
  if (i > 1 || !x.a) return none;
  const fig = `${pct(x.a)}<em>aces</em>`;
  const bold = sup(cmp, `a${i}`, tag);
  const core = `<i class="svace"></i>`;
  if (x.a >= SV_ACE_H) return { ...none, core, fig: `<b class="svacefig${bold}">${fig}</b>` };
  const head = x.r - x.a - (x.r < SV_FIG_H ? 0 : SV_FIG_H);
  if (head >= SV_ACE_H) {
    return { ...none, core, fig: `<b class="svacefig over${bold}">${fig}</b>` };
  }
  return { ...none, core, tucked: `<i class="svacetuck${bold}">${fig}</i>` };
}

// What the plot says, said in words under it: the two in-rates, each centred under the column it
// is the width of. The win rates are not here — a rate that is a height is said at that height,
// on the fill itself — and the double faults ride the plot's outer edge (see serveBar).
const SVDIM = [
  { key: '1st<span class="svlong"> serves</span> in', band: 0, dim: "h", cmp: "h0" },
  { key: '2nd<span class="svlong"> serves</span> in', band: 1, dim: "second_in", cmp: "h1" },
];

// --- which of the two is the better figure -------------------------------------------------
// Eight rates are drawn twice here, once per player: the two win rates and the two ace shares
// on the fills, the pooled ace rate braced under them, the two in-rates under the plots,
// and the double faults along the outer edge. Each pair is set in one weight, and the better
// of the two in bold — so who serves better, and on which figure, reads off the drawing
// before any of the numbers themselves are.
//
// More is better on seven of them and fewer on the eighth: a double fault is a point given
// away. A tie bolds neither — two equal figures with one of them in bold claims a difference
// that is not there — and so does a half of the pair that has no plot, where there is nothing
// to be ahead of.
const SVCMP = [
  ["w0", (x) => x.bands[0].h && x.bands[0].r, false],
  ["w1", (x) => x.bands[1].h && x.bands[1].r, false],
  ["a0", (x) => x.bands[0].h && x.bands[0].a, false],
  ["a1", (x) => x.bands[1].h && x.bands[1].a, false],
  ["atot", (x) => (x.bands[0].a || x.bands[1].a) && acePooled(x), false],
  ["h0", (x) => x.bands[0].h, false],
  ["h1", (x) => x.second_in, false],
  ["df", (x) => x.bands[2].h, true],
];

function serveCmp(sa, sb) {
  const out = {};
  if (!sa || !sb) return out;
  for (const [k, get, lower] of SVCMP) {
    const va = get(sa), vb = get(sb);
    if (va == null || vb == null || va === vb) continue;
    out[k] = (lower ? va < vb : va > vb) ? "a" : "b";
  }
  return out;
}

const sup = (cmp, key, tag) => (cmp && cmp[key] === tag ? " sup" : "");

function serveLabels(sp, tag, cmp) {
  if (!sp) return `<div class="svlabels ${tag} empty"></div>`;
  const fig = (v, key, cn, cd) => `<b class="svfig${sup(cmp, key, tag)}">${pct(v)}</b>` +
    (cn == null ? "" : `<span class="svn">${cn} of ${cd}</span>`);
  // Both shares sit centred under their columns on one line. --c is the column's own middle,
  // measured from the plot's outer edge — everything outside the column, plus half of it — and
  // the CSS centres the figure on it, held inside the plot.
  const { at, gp } = svGeom(sp);
  const dims = SVDIM.map((r) => {
    const b = sp.bands[r.band];
    const v = r.dim === "second_in" ? sp.second_in : b.h;
    if (v == null || (r.dim === "h" && !b.h)) return `<p class="svdimlab"></p>`;
    const c = at(sp.bands.slice(r.band + 1).reduce((t, x) => t + x.h, 0) + b.h / 2, gp(r.band));
    return `<p class="svdimlab" style="--c:${c}">${fig(v, r.cmp, sp.counts && r.dim === "h" ? b.hn : null, b.hd)}<em>${r.key}</em></p>`;
  }).join("");
  return `<div class="svlabels ${tag}"><div class="svdimlabs">${dims}</div></div>`;
}

// The whole block: the two plots either side of a midline, each with its figures outside it.
//
// No names over the plots and no legend under them. The two players are already told apart by
// the colours and the sides, which the scoreboard, the rings and the style columns all use the
// same way; and with every quantity named and pointed at there is nothing left for a legend to
// say.
// The window rides in the head, the same way the groundstroke block marks its own. It earns
// the space here: the next section, "serve direction", is a recency-weighted window and says
// so in its own caption, and a reader crossing from one to the other assumes they match
// unless each says which it is. This one is every service point in the player's charted
// history — the same span the hold rate on the ring above is taken over, which is what makes
// the plot what that hold is made of.
function serveAnatomy(da, db, ma, mb) {
  const sa = serveSplit(ma || (da && da.s)), sb = serveSplit(mb || (db && db.s));
  if (!sa && !sb) return "";
  const cmp = serveCmp(sa, sb);
  const win = ma || mb ? "this match" : "whole charted career";
  // The pooled-ace figure and its tines need room reserved under the plots — see .svpair.aces
  // — so long as either player has a core to point at.
  const aces = [sa, sb].some((s) => s && (s.bands[0].a || s.bands[1].a)) ? " aces" : "";
  return `<div class="svblock">
    <p class="svhead">every service point · ${win}</p>
    <div class="svpair${aces}">
      ${serveLabels(sa, "a", cmp)}${serveBar(sa, "a", cmp)}${serveBar(sb, "b", cmp)}${serveLabels(sb, "b", cmp)}
    </div>
  </div>`;
}

// Where a figure sits on its tour, as a strip: the middle half of the charted tour shaded, the
// player's own mark on it. Bits and strokes are not units anyone arrives knowing, and the band
// is the difference between "3.2" and "unusually varied" — which is what the number is for.
//
// The strip runs p5 to p95 and the shading is p25 to p75, both read off the build rather than
// written in, so a rebuild moves the band instead of quietly invalidating a sentence. A player
// outside the strip is drawn at the end they went past and marked as being past it: clamping
// silently would put the tour's most unusual player level with its 95th percentile, which is
// the one player the band exists to show is unusual.
// `fmt` is the figure's own formatter, so the band's ends are quoted in the unit the figure
// above is printed in. Without it a rate's band read "runs 0.5 to 0.5" — the raw fraction, at
// a decimal place that rounds every percentage on the panel to the same two numbers.
function figBand(x, band, fmt = (v) => v.toFixed(1)) {
  if (!band || x == null || !(band.max > band.min)) return "";
  const at = (v) => (v - band.min) / (band.max - band.min);
  const f = at(x);
  const out = f < 0 ? " out lo" : f > 1 ? " out hi" : "";
  const pos = Math.max(0, Math.min(1, f));
  return `<i class="pbband${out}"
    style="--lo:${(at(band.lo) * 100).toFixed(1)}%;--hi:${(at(band.hi) * 100).toFixed(1)}%;--at:${(pos * 100).toFixed(1)}%"
    title="the middle half of the charted tour runs ${esc(fmt(band.lo))} to ${esc(fmt(band.hi))}"
  ></i>`;
}

// Who these two players are: what kind of player this is, which hand they hold the racket in,
// and the scores that belong with them rather than in a comparison. It carries the facts
// the rest of the panel is read through, so it sits ahead of the rings rather than after them
// — the court patterns two sections further on name their zones by the player's own hand ("the
// BH corner" is a different corner for a lefty), so the key to reading those drawings has to
// arrive before them.
//
// It moved into "side by side" from its own band under "Charted history" — the counts up there
// are what every number in the panel is measured against and earn the title to themselves;
// style, hand, and the figures here are the first *comparison*, which is what this section is
// for.
// The column's contents pulled out as data, so the wide flanking columns (profileSide) and
// the narrow stacked comparison (profileCompare) build from one extraction rather than two
// that drift.
function profileParts(d, md, spread) {
  if (!d && !md) return null;
  const s = (d && d.s) || {};
  const sp = spread || {};
  // Printed for right-handers too, though most players are one: a key that only appears
  // sometimes leaves the reader to guess what its absence meant.
  const hand = s.hand ? `${s.hand === "L" ? "left" : "right"}-handed` : "";
  // The archetype is only printed where the clustering actually placed the player. Style is a
  // continuum — the clusters score a silhouette near 0.12 — and for about a third of players
  // the nearest two archetypes fit equally well. Naming one of them there is a coin toss
  // reported as a finding, and it was: those are the players whose label changed when a fifth
  // of a percent of the charting corpus was removed and their own fingerprint had not moved.
  // "Between styles" is the true statement, and unlike the name it doesn't move.
  const arch = s.archetype
    ? (Number(s.style_confident) === 0 ? "Between styles" : s.archetype) : "";
  // Strokes in the points this player won: the serve that starts a point and the shot that
  // ends it, averaged over the ones they took. One decimal, because the tour's middle half
  // spans well under a stroke and whole numbers would collapse most of the field onto "4".
  //
  // The points they *won* in both modes, where the career column used to average every point
  // either player played. That figure was a fact about the matchup as much as about the player
  // — on a charted match it is literally one number describing both of them, which is why the
  // match panel already asked the narrower question — and having the two modes print different
  // quantities under labels a reader could not tell apart was the worse half of it. Little is
  // lost by the swap: across the players who qualify the two correlate 0.989 (men) and 0.981
  // (women), so the career column shows the same shape of the same fact, and now it is the
  // shape the match column shows too. Nine players of the 359 who had the old figure fall
  // under the new one's floor.
  //
  // Labelled "won point length" rather than "won rally length": the figure counts the serve
  // and the return like every other stroke, and "rally" invites a reader to assume those are
  // left out. The unit says "shots", so the label only has to say what is averaged.
  //
  // On a match the figure is that match's own and carries the career reading beneath it as the
  // anchor, which is what says whether 4.4 shots was long or short for this player rather than
  // for tennis. The tour strip goes the other way, to the career reading only: one match is
  // not a draw from the distribution of careers the strip is cut over.
  const r = md ? md.len_won : num(s.won_rally_len);
  const career = num(s.won_rally_len);
  const rally = r == null ? null
    : {
      v: Number(r).toFixed(1), unit: "shots", raw: Number(r), fmt: (v) => v.toFixed(1),
      band: md ? null : sp.won_rally_len,
      anchor: md && career != null ? career.toFixed(1) : null,
      label: "avg winning rally"
    };
  // Independently gated. The figures come from different experiments with different
  // qualification thresholds, so a player can easily have one and not the other; a figure
  // held back because its neighbour is missing is a fact withheld for no reason.
  //
  // In match mode a figure the match can measure is taken from the match and carries the
  // career value beneath it as the anchor — "67%" alone has no scale, and "67%, career 62%"
  // is the whole story. A figure the match cannot measure keeps its career value and says
  // so on the line. Variety is the one that cannot: it is a mean per-shot surprise under a
  // tour-wide model, so it is unbiased at any sample size, but one match moves it by 0.18
  // bits against a tour whose middle half spans 0.26 — two match figures side by side would
  // be showing a gap that is mostly noise, and the career pair is the honest comparison.
  const figs = FIGS.map((f) => {
    const career = figOf(f, s);
    const mv = md ? figOf(f, md) : null;
    const v = mv != null ? mv : career;
    if (v == null) return null;
    // The band belongs to whichever reading is on the line. A match figure is one match and
    // the tour strip is cut over careers, so a figure taken from the match goes without it and
    // the career anchor underneath carries the scale instead.
    const den = f.den && mv != null ? num(md[f.den]) : null;
    return {
      v: f.fmt(v), raw: v, unit: f.unit, label: f.label, better: f.better, fmt: f.fmt,
      band: mv != null ? null : (f.band ? sp[f.band] : null),
      note: den != null ? `of ${den}` : null,
      anchor: mv != null && career != null ? f.fmt(career) : null,
      careerOnly: !!(md && mv == null)
    };
  }).filter(Boolean);
  const bp = bpFig(md);
  if (bp) figs.push(bp);
  return { arch, hand, rally, figs };
}

// Break points, as the count they are. A rate would be the wrong shape twice over: the median
// player-match faces seven of them and the tenth percentile faces two, so a good part of any
// draw would be printing a percentage off two points — and a match figure on this panel is a
// measurement rather than an estimate, so "saved 1 of 2" is the whole truth and "50%" is a
// claim about a player.
//
// Only the saving side prints. The other half of the exchange is the same two numbers read
// across the panel: with the two columns side by side, "saved 5 of 9" against "saved 4 of 6"
// says Alcaraz converted 2 of the 6 and Sinner 4 of the 9. Reading a row across is what this
// section is built to do, so shipping the converted pair as well would fill a second row with
// a fact the first row already carries.
//
// No `better`. One player facing more break points than the other is mostly a fact about who
// was serving under pressure, and a bolded winner would read as a verdict on a pair of numbers
// that are not on the same denominator.
function bpFig(md) {
  if (!md || md.bp_faced == null) return null;
  const faced = Number(md.bp_faced), saved = Number(md.bp_saved);
  return {
    v: faced ? `${saved} of ${faced}` : "none faced", raw: faced ? saved / faced : null,
    unit: "", label: "break points saved"
  };
}

// --- the groundstrokes, as a square --------------------------------------------------------
// Every groundstroke a player hit, on two axes, the way the serve plot puts every service
// point on two. Across is which hand played it: the two wings split the width by their share
// of the player's groundstrokes. Up and down from the midline is what the stroke did — winners
// stacking up, unforced errors sinking down — each read as a share of that wing's own strokes.
//
// Winners up. It is the direction every other reading on this page already runs: the rings
// climb for what a player won, the serve plot's fills rise off a baseline for the points the
// delivery took. A drawing where the good half hangs downward would be the one object on the
// panel a reader has to invert before they can read it.
//
// The two axes are the reason it is not four bars. How often a player runs around to the
// forehand and how often that forehand ends the point are different questions on different
// denominators, and four bars have to pick one of them to be the length. Given a width and a
// height the plot carries both, and the area comes out as a quantity in its own right: the
// shaded share of the half is the player's rate over *all* their groundstrokes.
//
//   above = (fh_share x fh_win) + (bh_share x bh_win) = groundstroke winner rate
//
// A player who misses a lot off a wing they rarely play shows a tall band on a narrow column,
// which is a small area — and that is the honest answer, because it is a small part of their
// tennis. Four bars would have shown the same tall bar as a player whose main wing breaks down.
//
// The wings sit where the player's hands are: a right-hander's forehand on the right of their
// plot, a left-hander's on the left. It costs nothing — both are labelled — and it means the
// two plots of a lefty-righty matchup are mirror images when the two play alike, which is the
// shape the matchup actually has. Unknown handedness draws as a right-hander, since it is the
// common case and the labels carry the truth either way.
//
// A cap, not a full 0-100%. Unforced error rates run about 6-13% and winner rates 2-10%, so
// a half drawn to 100% would put every band inside four pixels and the whole comparison inside
// one. 20% is a little past the tour's 95th on both, so nearly every player is drawn inside the
// box, and the two halves share it — a band the same height means the same rate whichever half
// or whichever player it is on.
const GS_CAP = 0.2;
// How much of a half a band can fill before its figure stops fitting past the end of it. The
// plot is 150px tall at every width (see .gsplot), so the half is 75px and the figure wants
// about 16 of them — leaving 0.78 of the half for the band. Past that the figure sits on the
// band instead, in the card colour with a halo, the same swap .svwin makes.
const GS_FIG_OVER = 0.78;

// One player's plot, off the career row and — on a charted match — the match's own rates. Null
// where the two shares are missing, which is the one thing the drawing cannot be drawn without:
// they are its width.
function gsSplit(s, md) {
  const read = (k) => {
    const mv = md ? num(md[k]) : null;
    return mv != null ? mv : num(s && s[k]);
  };
  const fhs = read("fh_share"), bhs = read("bh_share");
  if (fhs == null || bhs == null) return null;
  const wing = (w, name, share) => ({
    w, name, share,
    err: read(`${w}_err_pct`), win: read(`${w}_winner_pct`),
    n: md ? num(md[`${w}_gs`]) : null,
  });
  const fh = wing("fh", "FH", fhs), bh = wing("bh", "BH", bhs);
  // Left to right as the player's own hands are.
  return {
    wings: (s && s.hand) === "L" ? [fh, bh] : [bh, fh],
    hand: (s && s.hand) || "R", match: !!md,
  };
}

// Which of the two is the better figure, per wing and per outcome — the same one-weight,
// one-bold rule the serve plot and the rings use. More winners is better and fewer errors is;
// the shares have no better end, being which hand a player prefers rather than how well it
// goes, so they are not in here.
const GSCMP = [["fh", "win", false], ["fh", "err", true],
["bh", "win", false], ["bh", "err", true]];

function gsCmp(ga, gb) {
  const out = {};
  if (!ga || !gb) return out;
  const of = (g, w) => g.wings.find((x) => x.w === w);
  for (const [w, k, lower] of GSCMP) {
    const va = of(ga, w)[k], vb = of(gb, w)[k];
    if (va == null || vb == null || va === vb) continue;
    out[`${w}_${k}`] = (lower ? va < vb : va > vb) ? "a" : "b";
  }
  return out;
}

// One wing: a column the width of its share, spanning the full height in the drained tone so
// its own extent is the axis the two bands are read against — the ring's vocabulary, and the
// serve plot's. The winner band is solid, the error band carries the 45-degree hatch the double
// faults wear two blocks up, for the same reason: it is the half of the drawing that went the
// other way.
function gsWing(x, cmp, tag) {
  const band = (k, cls, say) => {
    const v = x[k];
    if (v == null) return "";
    const f = clamp01(v / GS_CAP);
    const over = f >= GS_FIG_OVER;
    const n = x.n == null ? "" : ` of ${x.n}`;
    const fig = `<b class="gsfig ${cls}${over ? " on" : ""}${sup(cmp, `${x.w}_${k}`, tag)}" style="--h:${(f * 50).toFixed(2)}%">${pct(v)}</b>`;
    return `<i class="gsb ${cls}" style="--h:${(f * 50).toFixed(2)}%"
      title="${esc(`${pct(v)}${n} ${x.name} groundstrokes — ${say}`)}"></i>${fig}`;
  };
  // No tour reference inside the plot. The strips elsewhere on the panel carry that, and a
  // dashed line per wing per half was four more lines across a box already holding two bands,
  // two figures and a midline — it cost the drawing more legibility than the fact was worth
  // here.
  return `<div class="gswing" style="--w:${(x.share * 100).toFixed(3)}%">
    ${band("win", "w", "winners")}${band("err", "e", "unforced errors")}
  </div>`;
}

function gsBar(g, tag, cmp) {
  if (!g) return `<div class="gscol ${tag} empty"></div>`;
  return `<div class="gscol ${tag}">
    <div class="gsplot">${g.wings.map((x) => gsWing(x, cmp, tag)).join("")}
      <i class="gsmid"></i></div>
    <p class="gslabs">${g.wings.map((x) => `<span style="--w:${(x.share * 100).toFixed(3)}%"><b>${pct(x.share)}</b><em>${x.name}</em>${
    // What the match rates were divided by, under the wing they belong to. A match is a short
    // window and the denominator is part of the figure; a career one has a floor behind it
    // instead, and the count would only restate the coverage band heading the panel.
    x.n == null ? "" : `<i>${esc(`${x.n} shots`)}</i>`}</span>`).join("")}</p>
  </div>`;
}

// The block: two plots either side of a midline, the same pairing the serve block uses, so a
// reader who has just read that one already knows how to read this. It is its own section now,
// under "serve + 1", and carries its own key the way serveAnatomy does.
function groundAnatomy(da, db, ma, mb) {
  const ga = gsSplit(da && da.s, ma), gb = gsSplit(db && db.s, mb);
  if (!ga && !gb) return "";
  const cmp = gsCmp(ga, gb);
  const win = ma || mb ? "this match" : "whole charted career";
  // The two halves are named down the midline itself: "winners" reading up the top half the
  // way the winner bands climb, "unforced errors" reading down the bottom half the way the
  // error bands fall. The word sits on the axis it describes, so there is no swatch legend to
  // carry a direction across to the drawing.
  return `<div class="gsblock">
    <p class="svhead">groundstroke outcomes · ${win}</p>
    <div class="gspair">${gsBar(ga, "a", cmp)}${gsBar(gb, "b", cmp)}
      <i class="gsaxis" aria-hidden="true"><b class="w">winners</b><b class="e">unforced errors</b></i>
    </div>
  </div>`;
}

// Which of two paired figures carries the win — "a" is the first argument, "b" the second, ""
// when neither: no better end, a value missing, a tie, or two values that print the same.
// Shared by the wide columns and the phone comparison so the bolding matches.
function figWinner(xa, xb) {
  const bd = (xa || xb || {}).better;
  if (!xa || !xb || !bd || xa.v === xb.v) return "";
  return (xa.raw > xb.raw) === (bd === "hi") ? "a" : "b";
}

// Empty for an uncharted player: the invitation to go chart them already ran under "Charted
// history", and a second empty box here would only repeat it.
//
// Rally length leads at headline size and the rest sit a tier down: three numbers all set at
// 22px would be three headlines and no hierarchy. Each figure prints on its own line rather
// than two-up — half a phone column is not wide enough for a two-word label beside a figure.
//
// `opp` is the other player, passed so a figure with a better end can set the winner in ink
// and let this side go quiet where it loses — the same lead/trail split the rings and the
// phone comparison use.
const EMPTY_PARTS = { arch: "", hand: "", rally: null, figs: [] };

// Every row either player has is a row both of them have, and the side without it says so:
// the figures are independently gated — variety needs 800 charted strokes and plenty of
// first-round entrants do not have them — so letting a player's remaining figures close the
// gap would set one player's break-point count level with the other's variety, in a band
// whose whole purpose is reading a row across.
//
// (The other thing that pulls the columns out of step is a style label wrapping to two lines,
// which is a layout problem and is answered by the subgrid these rows feed — see .tapemain.)
// The rows the two columns share, in a fixed order, built from both sides at once.
//
// Career figures ahead of the match's own. Style and hand are career facts and they open the
// column; on a charted match, variety is one too — it stays a career figure there because one
// match moves it by 0.18 bits against a tour whose middle half spans 0.26 — and left in FIGS
// order it landed between the length of the points won and the break points saved, so the
// column ran career, career, match, career, match and a reader had to check the small print on
// each line to know which window they were reading. Grouped, the column says who these players
// are and then what they did on the day, and the "career figure" note under variety is the
// boundary rather than an exception in the middle.
//
// Nothing moves on an uncharted match, where every figure is a career figure and none is
// marked as one: `careerOnly` is only ever set when there is a match to be the other thing.
function profilePlan(pa, pb) {
  const rows = [];
  const has = (p, l) => p.figs.some((x) => x.label === l);
  const isCareer = (l) => [pa, pb].some((p) => {
    const x = p.figs.find((y) => y.label === l);
    return x && x.careerOnly;
  });
  if (pa.arch || pb.arch) rows.push({ kind: "arch" });
  if (pa.hand || pb.hand) rows.push({ kind: "hand" });
  // FIGS first and in its own order, then anything either side carries that FIGS does not
  // name — the break-point count, which exists only on a charted match. Ordered off the
  // sides rather than off a second constant list, so a figure that starts being produced
  // gets a row without a second place to remember to add it to.
  const seen = new Set();
  const labels = [];
  const push = (l) => {
    if (seen.has(l) || !(has(pa, l) || has(pb, l))) return;
    seen.add(l);
    labels.push(l);
  };
  for (const f of FIGS) push(f.label);
  for (const x of pa.figs.concat(pb.figs)) push(x.label);
  for (const l of labels) if (isCareer(l)) rows.push({ kind: "fig", label: l });
  if (pa.rally || pb.rally) rows.push({ kind: "rally" });
  for (const l of labels) if (!isCareer(l)) rows.push({ kind: "fig", label: l });
  return rows;
}

function profileSide(p, o, tag, plan) {
  if (!plan.length) return "";
  const oppFigs = new Map(o.figs.map((x) => [x.label, x]));
  const fig = (x, cls) => {
    const trail = x.better && figWinner(x, oppFigs.get(x.label)) === "b" ? ' class="trail"' : "";
    // The anchor rides under the figure rather than beside it: the column is ~150px and a
    // second number on the same line pushed the label to a third row. `note` is the general
    // case of the same slot — a figure that wants to say one more small thing about itself.
    const note = (x.note ? `<i class="pbanch">${esc(x.note)}</i>` : "")
      + (x.anchor ? `<i class="pbanch">career ${esc(x.anchor)}</i>`
        : x.careerOnly ? `<i class="pbanch">career figure</i>` : "");
    // The tour strip goes under the label rather than under the value: it is a fact about
    // the unit, and above the label it would read as a second figure the label named.
    return `<p class="${cls}"><b${trail}>${x.v}</b>${x.unit ? `<span>${esc(x.unit)}</span>` : ""}<em>${esc(x.label)}</em>${figBand(x.raw, x.band, x.fmt)}${note}</p>`;
  };
  // An em dash where this player has no figure, the same mark the phone comparison already
  // uses for the same absence — the label rides with it, so the row still says which figure
  // is missing rather than leaving an unexplained gap opposite a number.
  const none = (cls, label) => `<p class="${cls} pbnone"><b>—</b>` +
    (label ? `<em>${esc(label)}</em>` : "") + `</p>`;
  const cell = (r) => {
    if (r.kind === "arch") return p.arch ? `<p class="pbstyle">${esc(p.arch)}</p>` : none("pbstyle");
    if (r.kind === "hand") return p.hand ? `<p class="pbhand">${esc(p.hand)}</p>` : none("pbhand");
    if (r.kind === "rally") return p.rally ? fig(p.rally, "pbq") : none("pbq", "avg winning rally");
    const x = p.figs.find((y) => y.label === r.label);
    return x ? fig(x, "pbfig") : none("pbfig", r.label);
  };
  return `<div class="pbside ${tag}" data-side="${tag}">${plan.map(cell).join("")}</div>`;
}

// The same figures for a phone, where the two flanking columns are a ~150px pair and every
// label prints twice. One grid row per figure — A's value, the label once, B's value — so the
// two numbers sit across a centre line and read against each other directly. Renders whenever
// either side has anything, filling the other side with an em dash; the flanking columns take
// the wide layout, where the rings run between them and each figure sits by its own mark.
function profileCompare(A, B, plan) {
  const any = (p) => p.arch || p.hand || p.rally || p.figs.length;
  if (!any(A) && !any(B)) return "";
  const map = (p) => {
    const m = new Map();
    if (p.rally) m.set(p.rally.label, p.rally);
    for (const x of p.figs) m.set(x.label, x);
    return m;
  };
  const ma = map(A), mb = map(B);
  // Read off the same plan the wide columns are built from, rather than re-derived here. The
  // two layouts are the same rows in the same order by construction then, which is what
  // stopped being true the moment there were two orderings to keep in step.
  const seq = plan.filter((r) => r.kind === "rally" || r.kind === "fig")
    .map((r) => (r.kind === "rally" ? (A.rally || B.rally).label : r.label));
  // The career anchor rides under the value here too, so the phone layout says the same
  // thing the wide one does rather than dropping the half that gives the figure its scale.
  const val = (x) => x == null ? "—"
    : `${x.v}${x.unit ? ` <span class="pbcu">${esc(x.unit)}</span>` : ""}` +
    figBand(x.raw, x.band, x.fmt) +
    (x.note ? `<i class="pbanch">${esc(x.note)}</i>` : "") +
    (x.anchor ? `<i class="pbanch">career ${esc(x.anchor)}</i>`
      : x.careerOnly ? `<i class="pbanch">career</i>` : "");
  // For a figure with a better end (serve-in rates, double faults) the winner keeps the ink
  // and the other side goes quiet — see figWinner().
  const rows = seq.map((l) => {
    const xa = ma.get(l), xb = mb.get(l), win = figWinner(xa, xb);
    const cls = (side) => side + (win && win !== side ? " trail" : "");
    return `<div class="pbcmp-row"><b class="${cls("a")}">${val(xa)}</b>` +
      `<span class="pbcl">${esc(l)}</span><b class="${cls("b")}">${val(xb)}</b></div>`;
  }).join("");
  const head = (a, b, cls) => a || b
    ? `<div class="pbcmp-head ${cls}"><span class="a">${esc(a || "—")}</span>` +
    `<span class="b">${esc(b || "—")}</span></div>` : "";
  const tops = head(A.arch, B.arch, "arch") + head(A.hand, B.hand, "hand");
  // Two siblings, not one box. On the phone layout the style and handedness lines go above
  // the games-won ring and the figure rows below it — two separate rows of .tapemain's grid,
  // which a single wrapper could not be split across. Both hidden on the wide layout, where
  // the flanking columns carry all of this.
  return (tops ? `<div class="pbtops">${tops}</div>` : "") +
    `<div class="pbcmp">${rows}</div>`;
}

// The one line over the whole body. The scoreboard above it never says "this match" — it
// can't, nothing under here is about this match — so the body has to say what it is itself,
// before any of its numbers do.
//
// It heads the whole body rather than riding inside the strip, because everything below is
// the same thing: what the charting has of these two players.
//
// It reads "their charted matches, not this one" rather than "career totals", because serve
// direction is a recent-form window rather than a career total, and a subtitle covering the
// body has to be true of every section in it. Each section names its own window in its
// caption.
//
// The asterisk is the other half of COV_NOTE below, which opens with one. It had no
// counterpart anywhere in the panel, so the note at the foot read as a footnote to nothing
// and the caveat never attached to the counts it qualifies.
const CHARTED_TITLE = `<p class="tapetitle">Charted history<span class="tapestar">*</span></p>`;

// The asterisk on "Charted history": these are a sample assembled by volunteers picking
// matches worth charting, not a random one, so it isn't the player's record. It reads once
// per panel and applies to every number above it, so it closes the panel rather than
// competing with the title for the first thing a reader sees under it.
const COV_NOTE = `<p class="covnote">* Charting is volunteer work, so these are the matches
    someone chose to chart. That weights the numbers toward big occasions rather than
    sampling a career evenly.</p>`;

// The strip's own heading. It had none while the title above sat inside it; with the title
// promoted to head the body, the one chart here without a name would have been this one.
// "Side by side" names the form rather than the contents, because the form is what tells it
// from its neighbours: every other section gives each player a column, and this is the one
// place the two are measured on a shared axis.
//
// One ring, holding the one comparison that is genuinely shared: how often each of them wins
// a game, on serve and on return. Every other per-player figure is a fact about that player
// and prints in their own column beside it.
//
// The two style columns flank the ring rather than sitting in a row above it, wide enough
// allowing: three tracks (style, ring, style) instead of the two rows a narrower panel needs.
// Centred on that row, the ring lands in the gap a style column already has between its own
// archetype line and its first figure — so on a wide panel it reads as filling that gap rather
// than as a block dropped in below it. See .tapemain in the stylesheet for the two
// grid-template-areas this switches between.
// What the figures in the two style columns are, collapsed. A definition is a thing a reader
// wants once and then never again, so it opens on request rather than spending the panel's
// width on prose every reader has already read.
//
// The tour bands supply a scale. Bits and percentage points are not units anyone arrives
// knowing, and the band the middle half of the tour occupies says in a clause what a scatter
// of the whole field would take a chart to say. It is read off the build rather than written
// into the sentence, because a hardcoded "2.9 to 3.2" is correct until the next rebuild and
// quietly wrong after it.
//
// Only the figures at least one of these two players actually has get defined. A key that
// explains a number nowhere on screen sends the reader looking for it.
function figureKey(sa, sb, spread, match) {
  const has = (k) => {
    const f = FIGS.find((x) => x.k === k);
    return [sa, sb].some((s) => s && (f ? figOf(f, s) : num(s[k])) != null);
  };
  // The style line is a string, not a figure, so it needs its own test — num() on an
  // archetype name is NaN and `has` would drop the entry that most needs to exist.
  const hasStyle = [sa, sb].some((s) => s && s.archetype);
  // The same rule for an object that is drawn rather than printed: define it only where it
  // is on screen. The serve plot carries no key of its own — every figure on it is named and
  // pointed at where it sits.
  const hasBp = [sa, sb].some((s) => s && s.bp_faced != null);
  // Return winners are the one outright-win figure still in the column — the ace rate moved to
  // the serve plot.
  const hasOutright = has("ret_winner_rate");
  const sp = spread || {};
  // One entry covers all four shot-mix figures, so one of them on screen is enough to earn it.
  // They arrive together off the same stroke walk but are gated apart — a career under its
  // floor, a match where nobody came in — and gating the definition on all four would take the
  // explanation away from the ones that survived.
  const MIX_KEYS = ["slice_pct", "net_pct", "net_winner_pct", "net_err_pct"];
  const hasMix = MIX_KEYS.some(has);
  // The groundstroke square carries no key of its own; its shares still gate the shared
  // error-rate entry below, which speaks for the square and the net figures at once.
  const hasGround = [sa, sb].some((s) => s && num(s.fh_share) != null);
  // The tour bands, in the words the strip is drawn from. Only for the figures at least one
  // of these two players actually has a strip for — on a charted match the rally figure is
  // the match's own and carries no strip, so its band is not quoted there either.
  const bands = [["bits", sp.bits, "Variety", (v) => v.toFixed(1) + " bits"],
  ["won_rally_len", match ? null : sp.won_rally_len, "Won point length",
    (v) => v.toFixed(1) + " shots"],
  ["ret_winner_rate", match ? null : sp.ret_winner_rate, "The return-winner rate", pct],
  ["slice_pct", match ? null : sp.slice_pct, "The slice share", pct],
  ["net_pct", match ? null : sp.net_pct, "The net share", pct],
  ["net_winner_pct", match ? null : sp.net_winner_pct, "The net winner rate", pct],
  ["net_err_pct", match ? null : sp.net_err_pct, "The net error rate", pct]]
    .filter(([k, band]) => band && [sa, sb].some((s) => s && num(s[k]) != null))
    .map(([, band, name, f]) =>
      `${name}'s middle half runs ${f(band.lo)} to ${f(band.hi)}.`);

  const defs = [
    // The style line leads the key because it leads the column, and because it is the one
    // item here that sometimes declines to answer. A reader who meets "Between styles" with
    // no explanation has to guess whether it means missing data, a hedge, or a finding — it
    // is the third, and saying so is the whole point of this entry. It is also the panel's
    // most common non-answer: about a third of the players who qualify get it.
    !hasStyle ? "" : `<div><b>Style</b> groups players by twelve measured metrics of their
      charted play, each group named for its centre.
      ${/* The gate is not a detail. Style is a continuum: the clustering scores a silhouette
           near 0.12, and for about a third of players the nearest two groups fit equally well.
           Naming one of them is a coin toss reported as a finding, so the panel doesn't. */""}
      <b>"Between styles"</b> means the two nearest groups fit this player about equally well.</div>`,
    !has("won_rally_len") && !match ? "" : `<div><b>Average won point length</b> counts the serve
      and the shot that ends the point, over the points that player won.</div>`,
    !match ? "" : `<div>Every rate on this panel is <b>this match only</b> — the rings, the
      serve plot, the break points and the placement — except where a line says
      "career". Those carry no minimum-sample gate, because they are not estimates of how
      these players usually play: they are counts of what happened over the match's own
      points.</div>`,
    !hasOutright ? "" : `<div><b>Return winners</b> are clean winners on the return over every 
      point returned.</div>`,
    !hasMix ? "" : `<div><b>Slice share</b> and <b>net share</b> are out of every non-serve
      stroke that player hit, the return counted as one. A <b>net shot</b> is a volley,
      overhead, half-volley or swinging volley; its winner and error rates are out of those
      net shots, not out of every stroke.</div>`,
    !hasMix && !hasGround ? "" : `<div>Every <b>error rate</b> here counts <b>unforced</b>
      errors only.${match ? "" : ` A career rate needs 800 strokes of its kind, or 200 net shots
      for the three net figures — nobody has hit 800 volleys.`}</div>`,
    !has("bits") ? "" : `<div><b>Variety</b> is how far a player's shot choices stray from tour
      norms. A model built on the whole tour predicts each next shot from the two before it, and
      variety is how surprised that model is by this player, in bits: a shot it gave even odds
      scores 1 bit. It counts uncommon shot types and uncommon order alike, so slicers and
      serve-volleyers score high. A player needs 800 charted strokes to get one.${match ? ` It stays a career figure on a charted match: one match moves it by 0.18 bits
      against a tour whose middle half spans 0.26, mostly noise.` : ""}</div>`,
    // The strip closes the key rather than opening it: it names the two figures it is drawn
    // under, so it reads after their own entries rather than before them. The band numbers are
    // read off the build rather than written into the sentence — a hardcoded "2.9 to 3.2" is
    // right until the next rebuild and quietly wrong after it.
    !bands.length ? "" : `<div>The <b>strip</b> under a figure is where that player sits on the
      charted tour: the shaded part is the middle half of it, and the ends are the 5th and 95th
      percentiles. ${bands.join(" ")} A player past either end is drawn at it and marked.</div>`,
    !match ? "" : `<div><b>Win probability</b> starts from what the two players' charted
      records had done before this match — their serve and return rates, combined into a
      point-win probability for each — and propagates it up the scoring tree, point to game
      to set to match, after every point. It is not a live market price and knows nothing
      about the day: it is what the scoreline was worth against those two records.</div>`,
  ].filter(Boolean);
  if (!defs.length) return "";
  return `<details class="notekey figkey">
    <summary>How these figures are measured</summary>
    <div class="keytext">${defs.join("")}</div>
  </details>`;
}

function tape(da, db, spread, det) {
  // The ring takes only the sides that clear the coverage floor; the profile columns beside
  // it take the player whole, since every figure in them carries its own gate already. A side
  // held back leaves its half of the ring empty, which is the shape the drawing already has
  // for a player the rates simply do not exist for — and the note says which it is, so an
  // empty half is never left reading as "no charting" when it means "not enough of it".
  //
  // On a charted match the ring is filled from the match itself and the floor does not
  // apply — see matchSide(). A player with one charted match in their life still served a
  // measurable number of games in this one.
  const ma = matchSide(det, 0), mb = matchSide(det, 1);
  const sa = ma || (wellCharted(da) ? da.s : null);
  const sb = mb || (wellCharted(db) ? db.s : null);
  const cells = sa || sb ? tapeRows().map((r) => donut(r, sa, sb)).join("") : "";
  // Both columns' contents are extracted once and shared: the row plan is built from the two
  // together, and the phone comparison reads the same pair rather than re-deriving them.
  const pA = profileParts(da, ma, spread) || EMPTY_PARTS;
  const pB = profileParts(db, mb, spread) || EMPTY_PARTS;
  const plan = profilePlan(pA, pB);
  const sideA = profileSide(pA, pB, "a", plan), sideB = profileSide(pB, pA, "b", plan);
  if (!cells && !sideA && !sideB) return "";
  const rings = cells ? `<div class="dnstack">${cells}</div>` : "";
  // Named, not just omitted. A blank half beside a full one is the panel making a claim about
  // the thin player, and the claim it should make is about the charting rather than the
  // tennis.
  const thin = det ? [] : [[da, sa], [db, sb]]
    .filter(([d, s]) => d && !s).map(([d]) => last(d.s.player));
  const thinNote = thin.length
    ? `<p class="tapenote">Hold and break rates need ${RATE_MIN_PTS.toLocaleString()}
       charted points to print; ${esc(thin.join(" and "))}
       ${thin.length > 1 ? "are" : "is"} below that.</p>` : "";
  // No header and no section wrapper: it carries straight on from the charted-history coverage
  // above it, which every figure here is measured against, so a labelled gap between the two
  // would only push them apart. The bordered box is its own boundary.
  //
  // The serve plot and the groundstroke square both used to close this box. Each is a section
  // of its own now — where the delivery goes and what it does are one subject, and so are how
  // a player plays a wing and what it wins. The ring keeps the hold rate the serve plot is the
  // anatomy of; the style columns keep the shot mix the square's wings are read against; the
  // square keeps a key of its own, near the drawing rather than a screen up.
  return `<section class="tape">
    <div class="tapemain" style="--pbrows:${plan.length}">${sideA}${rings}${sideB}${profileCompare(pA, pB, plan)}</div>
    ${/* No key under the ring. Both marks on it carry their own figure against them, so a key
         would be naming things the drawing has already named — and naming them a screen away
         from where they are. */""}
    ${thinNote}
    ${/* Career fields under the match's own, so the key can see both. It defines what is on
         screen, and on a charted match the columns still print two career figures — the style
         label and variety — off rows the match side object does not carry. Handed only the
         match side, `hasStyle` and has("bits") both came out false and the panel showed
         "Between styles" and "3.1 bits" with nothing anywhere explaining either. */""}
    ${figureKey({ ...(da && da.s), ...sa }, { ...(db && db.s), ...sb }, spread, !!det)}
  </section>`;
}

// --- shared-header sections ---------------------------------------------------------
// One topic, one header, two columns. Giving each player their own full card lets the
// sections slide out of step the moment one player has more patterns than the other —
// and once they have, no two comparable numbers are ever on screen together.
//
// The topic sits on its own line and sticks to the top of the scroll while its cards are
// passing, because the panel is four or five screens tall: without it, a column of
// drawings halfway down says nothing about which question it answers. The note under it
// scrolls away, being the sort of thing you read once.
//
// `kind` is how the columns behave once they are phone-narrow: "cards" keeps them
// side by side (a court thumbnail survives a 160px column, and the comparison is the
// whole point of the section), "text" stacks them (a shot sequence does not).
// How many items a column is about to render, read off its own markup: every card in
// either family opens with a known class, and an empty column still costs one line.
const countCards = (html) =>
  Math.max(1, (String(html || "").match(/class="(?:pcard2|trig )/g) || []).length);

// `full` is a drawing that belongs to the section but not to either column: it is measured on
// a scale the two players share, and a scale cannot be shared across a gutter — two plots in
// two columns are two plots that cannot be laid against each other. It runs at the section's
// full width, under whatever columns the section also has (the serve and groundstroke plots
// each stand alone in their section, so in practice it is the only thing under the heading).
function section(title, note, a, b, aHtml, bHtml, kind = "cards", full = "") {
  if (!aHtml && !bHtml && !full) return "";
  const col = (html, side, tag) => `<div class="seccol" data-side="${tag}">
    <p class="colwho"><span class="tdot ${tag}"></span>${esc(last(side.name) || "TBD")}</p>
    ${html || `<p class="colnone">nothing at this player's coverage</p>`}</div>`;
  // How many rows the two columns share, so the CSS can run them on one set of tracks
  // and keep each player's first finding level with the other's. Without it the columns
  // are two independent stacks, and one extra line of wrap in a description slides
  // everything below it out of step with the thing it is supposed to be read against.
  const rows = 1 + Math.max(countCards(aHtml), countCards(bHtml));
  // Whose column is whose is said once per layout, and only where the layout stops saying it
  // by itself. Side by side — at any width — each column is capped by a rule in its player's
  // colour, in the same left-right order as the split under the scoreboard, which never
  // scrolls away — so repeating the names in the sticky bar would carry the same key twice
  // over columns that had not moved. Stacked, the position is genuinely gone, and each column
  // names its own player.
  // Both columns empty and only the full-width drawing to show: the columns are dropped
  // rather than printed as two "nothing at this player's coverage" placeholders over a
  // drawing that is not missing. Which happens for real — the placement strips are gated on
  // the experiment's reliability flag and the plot only wants 200 service points, so a pair
  // of thinly-charted players reaches this section with the plot and nothing above it.
  const cols = aHtml || bHtml
    ? `<div class="seccols" style="--rows:${rows}">${col(aHtml, a, "a")}${col(bHtml, b, "b")}</div>`
    : "";
  return `<section class="msec ${kind}">
    <h3 class="sechead">${title}</h3>
    ${note ? `<p class="secnote">${note}</p>` : ""}
    ${cols}${full}
  </section>`;
}

// Said once per section rather than on each of six cards. Both figures the cards carry are
// comparisons, and neither is self-describing: "n=277/970" needs to be read as a share, and
// the win rate is against the player's own rate on the same ball — which is the whole point
// of it, since measuring it against the tour's rate ranked players rather than choices.
const PAYOFF_LEGEND = `<span class="paykey">n is how often they play it, out of how often
  they face the ball; win rates are against their own rate answering that same ball</span>`;

// The court glyph explained where it is first used, rather than only inside the collapsed
// notation key — three cues is two more than a reader should have to go looking for.
// A span, not a paragraph: this rides inside the section's <h3>, where a block element
// would be invalid nesting.
const COURT_LEGEND = `<span class="courtkey">
  <span class="ck in">dashed</span> the ball they get ·
  <span class="ck out">solid</span> their answer ·
  <span class="ck half">tinted half</span> their side of the net</span>`;

// The key to the bar under each cue. Same marks the comparison strip's note uses, because
// it is the strip's bar: a reader who has scrolled past one already knows this one.
// `baseline` is what the tick stands for. It stays the caller's word rather than a
// constant in here: the strip and the cue column word the same tick differently, and a
// second cue section measured against something else has existed before and could again.
const meterLegend = (baseline) => `<span class="meterkey">
  <span class="segkey"></span> landed <span class="segkey miss"></span> missed, out of the
  balls the cue provokes · <span class="tickkey"></span> ${baseline}</span>`;

// Collapsed key for the shot notation: two mini courts (rally zones, serve
// targets) + a text legend. Tap/click to open — hover isn't a thing on phones.
function notationHelp() {
  const court = (inner) => `<svg viewBox="0 0 150 190" xmlns="http://www.w3.org/2000/svg">
    <rect x="20" y="10" width="110" height="170" class="ct-line" fill="none"/>
    <line x1="20" y1="95" x2="130" y2="95" class="ct-net"/>
    ${inner}</svg>`;
  const zones = court(`
    <line x1="56.7" y1="10" x2="56.7" y2="95" class="ct-dash"/>
    <line x1="93.3" y1="10" x2="93.3" y2="95" class="ct-dash"/>
    <text x="38" y="45" class="ct-big">1</text>
    <text x="75" y="45" class="ct-big">2</text>
    <text x="112" y="45" class="ct-big">3</text>
    <text x="38" y="60" class="ct-sub">FH side</text>
    <text x="75" y="60" class="ct-sub">middle</text>
    <text x="112" y="60" class="ct-sub">BH side</text>
    <circle cx="75" cy="172" r="4" class="ct-player"/>
    ${shotLine(75, 166, 40, 66)}
    ${shotLine(75, 166, 75, 66, { faint: true })}
    ${shotLine(75, 166, 110, 66, { faint: true })}
    <text x="75" y="189" class="ct-cap">rally direction →1 / →2 / →3</text>`);
  const serves = court(`
    <line x1="20" y1="52.5" x2="130" y2="52.5" class="ct-line-thin"/>
    <line x1="20" y1="137.5" x2="130" y2="137.5" class="ct-line-thin"/>
    <line x1="75" y1="52.5" x2="75" y2="137.5" class="ct-line-thin"/>
    <circle cx="27" cy="60" r="3.4" class="ct-target"/>
    <text x="36" y="64" class="ct-sub anchor-start">wide</text>
    <circle cx="48" cy="76" r="3.4" class="ct-target"/>
    <text x="57" y="80" class="ct-sub anchor-start">body</text>
    <circle cx="70" cy="60" r="3.4" class="ct-target"/>
    <text x="66" y="49" class="ct-sub">T</text>
    <circle cx="112" cy="172" r="4" class="ct-player"/>
    ${shotLine(108, 167, 30, 64, { faint: true })}
    <text x="75" y="189" class="ct-cap">serve wide / body / T</text>`);
  return `<details class="notekey">
    <summary>How to read the shot notation</summary>
    <div class="courts">${zones}${serves}</div>
    <div class="keytext">
      <div><code>FH</code>/<code>BH</code> forehand / backhand ·
        <code>drive</code> flat or topspin · <code>slice</code> slice or chip ·
        <code>net shot</code> volley, overhead, half-volley or swinging volley ·
        <code>drop shot</code> and <code>lob</code>, the shortest and deepest balls in
        tennis, each its own · <code>shot</code> stroke type not charted</div>
      <div><code>→1/2/3</code> where it was hit, seen from the hitter: zone 1 is a
        right-hander's forehand side, 3 their backhand side (<code>→·</code> =
        direction not charted).</div>
      <div>A response is named for the line it took — crosscourt, down the line,
        inside-out — except a net shot, which is named for where it went. Those words
        all describe where a player was standing, and a volley is cut off in the air
        wherever they could reach it, so the corner the ball was headed for is not one
        they ever stood in.</div>
      <div>Every court drawing reads the same way: the tinted half is the profiled
        player's side, a solid line in their colour is a ball they hit, and a dashed grey
        one is the opponent's. Lines run contact to contact, so every kink is a player
        meeting the ball, and the mark on the one the drawing turns on says what happened
        there: a hollow ring is a bounce, with the answer leaving from a step behind it,
        and a filled dot up near the net is a ball taken out of the air, no bounce under
        it at all. On a court pattern that is the ball they answered, and the arrow is the
        answer. On a trigger it is the ball they attacked — the shot they went for is what
        the numbers beside it measure, and it isn't drawn, because the notation never says
        where it went.</div>
      <div>Court patterns name zones by the player's own hands (a lefty's FH corner
        is a righty's BH corner), so "drive into the BH corner → crosscourt BH slice"
        at <b>1.6×</b> means they answer that ball with the crosscourt slice 1.6× as
        often as the tour does from the same spot. <b>wins 52% ▲6</b> is the payoff:
        how often the point ends up theirs after that response, vs the tour playing
        the same ball.</div>
      <div>Triggers group a player's point-ending shots as one decision: an
        <em>aggressive shot</em>, a stroke they went for the finish with. It counts
        three ways — a winner, their own unforced error, or a shot that forced the
        reply into an error. <code>A · B</code> is the cue: their shot A, then the
        opponent's reply B. "Aggressive" is the <em>aggressive shot frequency</em>
        that cue provokes — how often a stroke there is one — and "converts" is the
        share that paid, winners and forced errors together. A cue that raises the
        frequency but sinks conversion is a trap: they take the bait. The first bar
        in each column is the same pair of numbers over every rally stroke the player
        hits, with no cue at all: their baseline, and the tick every bar below it is
        measured against.</div>
      <div>A rally stroke there is anything from the third ball of the point on, so
        serves and returns aren't in the denominator. An error the player was forced
        into counts against whoever forced it, not against them.</div>
    </div>
  </details>`;
}

// Every decided pairing gets one of these: link straight to the chart if it exists, or
// invite the viewer to be the one who charts it — live, if the match hasn't been played
// yet, since that's exactly when Match Charting Project volunteers sign up to chart one.
// Only a slot still waiting on an opponent has nothing to invite: there's no pairing yet
// for anyone to sign up for.
//
// The mark on the end is drawn for the same reason the close button's is: this is a
// control, and the site's controls carry SVG glyphs, not characters. A font's → is also
// the wrong weight beside 700 uppercase at 9.5px — it is drawn for running text and comes
// out a hairline. fill: currentColor, so the state that colours the label colours it too.
// No ✓ leads the charted label: no other mark on the site is a checkmark, and the two states
// already read apart on their words and their colour.
const GO_ICON = `<svg class="gly" viewBox="0 0 11 8" width="11" height="8" aria-hidden="true">
  <rect x="0" y="2.9" width="7.4" height="2.2"/><path d="M6.4 0.4 11 4 6.4 7.6z"/></svg>`;

function chartButton(m) {
  if (m.a.name === "TBD" || m.b.name === "TBD") return "";
  if (m.chart_id) {
    const url = `https://www.tennisabstract.com/charting/${encodeURIComponent(m.chart_id)}.html`;
    return `<a class="mchartbtn charted" href="${url}" target="_blank" rel="noopener">
      View the chart${GO_ICON}</a>`;
  }
  return `<a class="mchartbtn uncharted" href="${CHART_GUIDE}" target="_blank" rel="noopener">
    Chart this match${GO_ICON}</a>`;
}

// The scoreline that sits between the two names, the higher of each set bolded — so the
// result reads as a run of bold on the winner's side.
//
// One flat list of cells, ordered A,B per set, laid out two ways by CSS alone: a wide
// header flows it down columns, giving each player a horizontal scoreline level with
// their own name, and a narrow one flows it across rows, giving one row per set stacked
// between the names. Either way a set is a pair and the pairs stay in order, so neither
// layout needs its own markup.
function scoreStack(a, b) {
  const n = Math.max((a.sets || []).length, (b.sets || []).length);
  if (!n) return `<div class="mscore none">vs</div>`;
  // The feed's per-set verdict (true won / false lost / null not decided). Where it's
  // there, an undecided set is never bold, so a suspended match's live set doesn't read
  // as won by whoever leads it; older archived draws have no list and are all finished,
  // so there the higher score stands.
  const winsA = Array.isArray(a.set_wins) && a.set_wins.length ? a.set_wins : null;
  const winsB = Array.isArray(b.set_wins) && b.set_wins.length ? b.set_wins : null;
  const cell = (v, o, wins, i) => {
    if (v == null) return `<span class="sg"></span>`;
    const won = wins ? wins[i] === true : o != null && Math.trunc(v) > Math.trunc(o);
    return `<span class="sg${won ? " won" : ""}">${Math.trunc(v)}</span>`;
  };
  let cells = "";
  for (let i = 0; i < n; i++) {
    const x = a.sets && a.sets[i], y = b.sets && b.sets[i];
    if (x == null && y == null) continue;    // drop the pair, never half of one
    cells += cell(x, y, winsA, i) + cell(y, x, winsB, i);
  }
  return `<div class="mscore">${cells}</div>`;
}

// A player's name in both renderings the header might need: the full name, and a
// first-initial form — a narrow three-column header runs out of room for "Stefanos
// Tsitsipas" long before it runs out of room for "S. Tsitsipas", and shortening the part
// that carries least beats wrapping or clipping the part that carries most.
//
// Both are always emitted and fitHeader() chooses, by measuring; CSS shows one and hides
// the other. A one-word name abbreviates to itself, so it simply costs that rung of the
// ladder nothing and the next one is tried.
function nameHtml(name) {
  const full = esc(name || "TBD");
  const parts = String(name || "").trim().split(/\s+/);
  const abbr = parts.length > 1
    ? esc(`${parts[0][0].toUpperCase()}. ${parts.slice(1).join(" ")}`) : full;
  return `<span class="mname"><span class="mfull">${full}</span>` +
    `<span class="mabbr">${abbr}</span></span>`;
}

// What to call the event here: the same call app.js makes for the page's own <h1> — the
// calendar's common name ("Canadian Open") over the feed's own name, which is the title
// sponsor's ("National Bank Open presented by Rogers") and not what anyone calls the thing.
// Unlike the page header, there is no line underneath for the sponsor's name to fall back
// to, so it is simply dropped here rather than restated in an eyebrow that is read once.
const ename = (t) => (t.event || {}).common_name || t.name;

// Where this match sits: event and round. It rides in the top corner beside the close
// button rather than over the names, because it is the context you read once on opening
// and then stop looking at, and the scoreboard is what the header is for. No draw here:
// the tabs behind the panel are already set to one, and a men's and a women's match never
// share a screen.
function eyebrow(t, round) {
  const event = t.completed ? `${t.season} ${ename(t)}` : ename(t);
  return [esc(event), round ? esc(round.label) : ""].filter(Boolean).join(" · ");
}

// When. A scheduled match carries its date and start time inside ESPN's detail string once
// it has a court and a session, so printing the long date beside that would just say the day
// twice. Before that the detail is the literal word "TBD", which is a non-empty string and
// would print itself over a date the feed already knows, so an unscheduled match falls back
// to its day. A finished one says only the day: the state it
// is in is already on the scoreboard, in the caret against the winner's name, and a word
// for it beside the date was the same fact a second time in weaker type. ESPN's detail
// here is only ever "Final" or "Retired", so nothing else is being dropped with it.
// The live dot is drawn in CSS now rather than typed as ●, and it is a square: nothing on
// this site is round. ESPN's own hyphen between the day and the time becomes the middot the
// rest of the page separates with, so the header's two chrome lines punctuate alike.
function whenLine(m) {
  if (m.state === "in") return `<span class="live">${esc(m.detail || "Live")}</span>`;
  if (m.state !== "post") {
    const d = m.detail && m.detail !== "TBD" ? m.detail.replace(/ - /g, " · ") : dayLong(m.date);
    return esc(d);
  }
  const day = matchDate(m.date);
  return day ? esc(day) : "";
}

// Scoreboard header, read top-down like a broadcast graphic: where we are, then the two
// players facing each other across their score, then when. Each player takes an end —
// flag, name, seed, and the colour dot that marks them as this side of everything below.
// Because it never scrolls away, it is also the header for the charted profile beneath
// it, which is why no name or flag is repeated down there.
function headHtml(m, t, round) {
  const decided = !!(m.a.winner || m.b.winner);
  const side = (s, tag) => {
    const emoji = flagEmoji(s.country);
    const flag = `<span class="mflag"${emoji ? ` title="${esc(s.country)}"` : ""}>${emoji}</span>`;
    const seed = s.seed ? `<span class="mseed">${esc(String(s.seed))}</span>` : "";
    const cls = "mp " + tag + (s.winner ? " win" : decided ? " lose" : "");
    // The winner's caret points into their name from the score side. The two names are
    // on one row now, so nothing has to line up underneath and the slot can simply be
    // absent on the other side.
    return `<div class="${cls}">${flag}${nameHtml(s.name)}${seed}
      ${s.winner ? `<span class="mwin"></span>` : ""}</div>`;
  };
  // Older archived draws carry no per-match date and nothing else to say, so the when
  // line drops out entirely rather than leaving an empty row under the names.
  const when = whenLine(m);
  // A hairline on the boundary between the two staggered rows, reaching name to name: the
  // one thing that says the run of games above it belongs to the player above it. Only
  // where there are two scorelines to divide — no scoreline, nothing to separate, and a
  // rule through a bare "vs" is just a rule.
  //
  // The stagger goes with it. It exists to tie each scoreline to the name it belongs to
  // across the gap between them; with no games to tie, it drops one name half a line below
  // the other for no reason a reader can recover, and two players about to play each other
  // should meet level. So an unplayed match says so in the markup and both names share a
  // row — see .mgrid.noscore.
  const played = (m.a.sets || []).length || (m.b.sets || []).length;
  const rule = played ? `<i class="mrule"></i>` : "";
  // Event/round belongs to the tournament, not to either player, so it sits in its own
  // corner rather than bracketing the scoreboard from an opposite end. A played or live
  // match's when joins it there, top left, since both are read before the score is. An
  // upcoming match's when is a countdown, not a record — it's still true at the moment
  // you'd act on it, which is down by the chart button, the one thing there is to *do*
  // about a match that hasn't been played yet.
  const upcoming = m.state === "pre";
  return `<div class="mcorner">
      <p class="mevent">${eyebrow(t, round)}</p>
      ${when && !upcoming ? `<p class="mstate">${when}</p>` : ""}
    </div>
    <div class="mgrid${played ? "" : " noscore"}">
      ${side(m.a, "a")}${scoreStack(m.a, m.b)}${side(m.b, "b")}${rule}</div>
    ${upcoming
      ? `<div class="mfoot">${when ? `<p class="mstate">${when}</p>` : ""}${chartButton(m)}</div>`
      : chartButton(m)}`;
}

// The body, under one title: who the two players are, then the headline ring, then the serve,
// then the pictures, then the sequences, then the small print. Every section shares one header
// across both columns, so the two players stay level however unevenly charted they are.
//
// The coverage band leads, under "Charted history", because the charted counts are the
// denominator of every number in the panel — everything under it is read through them.
//
// "Side by side" comes next, and opens with style, hand, and the per-player figures ahead of
// the ring: the handedness there is the key to reading the court drawings two sections down,
// so it has to arrive before them, and style is the first per-player comparison the body
// makes, which is what the section is for.
//
// "Serve outcome" is then the first single-player measurement. Every point starts with a
// serve, and it is the only thing here a viewer can expect to see happen in the match they
// just tapped. It is one plot, run full width because its two axes are a scale shared across
// both players: every service point sized by how often that delivery happens and what it won.
//
// "Serve direction" follows — the same subject one step earlier, where each first serve was
// aimed, as a strip per court side. Two windows meet across the pair, and each says which it
// is rather than leaving the reader to assume they match: direction is recency-weighted with a
// 10-match half-life, because the serve_tendencies experiment showed that predicts a player's
// next matches better than their career mix, and the outcome rates are the whole charted
// career, where they have always been measured. The second is not the first with a different
// denominator — it would take the same held-out check on rates that experiment never ran —
// so the plot keeps its span and prints it.
//
// From "serve direction" on, the sections run in the order a point does: where the serve goes,
// what the server does with the ball it comes back as ("off the return"), and only then the
// mid-rally exchange ("court patterns"). Off the return is built out of the service court and
// the serve's own direction, so it continues the section above it. Below court patterns it
// would put a mid-rally ball between the serve and the shot the serve sets up.
//
// The title is gated on there being a player under it. With neither side charted the body is
// the invitation to go and chart one, and "Charted history" over "Neither player has Match
// Charting history yet" heads a section with the word "history" twice and no history in it.
// The two conditions are exact opposites, so exactly one of them ever prints.
// The charted-match panel. Seven career sections become four about the match: how it swung,
// what each serve was worth, where the first one went, and the groundstroke exchange.
//
// Everything from "serve + 1" down is dropped rather than recomputed. Those sections are
// lifts against the tour of a player's era — a court pattern rests on a median 334
// observations of one incoming ball, a trigger on a rate over hundreds of rally strokes —
// and a match supplies a handful of each. Recomputed per match they would print a 2.4×
// lift off four balls; left career-wide under a match header they would read as findings
// about a match they were not measured on. Neither is worth the four screens, and the panel
// says what it can say about this match and stops.
// The charted match's first slot holds one of two full-width charts: this match's
// win-probability curve, or the two players' charted-history pyramid — the same one the
// career panel heads with. The curve is the default, being the thing a charted match has
// that an uncharted one does not; the pyramid is the other reading worth that width. The
// switch is a pair of wordless glyphs, and the choice carries across panel opens so a
// reader who wants coverage keeps getting it.
let lastMatchView = "wp";

// A curve and a centred tapering stack — the outline of each chart the glyph switches to,
// at the 14px the site's other view toggles use. Square ends, no rounded caps, the same
// as every other glyph here.
function matchViewIcon(view) {
  return view === "wp"
    ? `<svg viewBox="0 0 14 14" width="14" height="14" aria-hidden="true"><path
        d="M1 10 L4.5 4.5 L7 8 L10 3 L13 6.5" fill="none" stroke="currentColor"
        stroke-width="1.6" stroke-linejoin="round"/></svg>`
    : `<svg viewBox="0 0 14 14" width="14" height="14" aria-hidden="true"><rect x="3.5"
        y="1.4" width="7" height="2.6"/><rect x="1" y="5.7" width="12" height="2.6"/><rect
        x="4.5" y="10" width="5" height="2.6"/></svg>`;
}

function matchBodyHtml(m, pa, pb, spread, det) {
  const a = m.a, b = m.b;
  const ma = matchSide(det, 0), mb = matchSide(det, 1);
  const by = det.charted_by
    ? `<p class="covnote">Charted by ${esc(det.charted_by)} for the Match Charting Project.</p>` : "";
  const wp = wpChart(det, a, b);
  const cov = profileBand(pa, pb);
  let head;
  if (wp && cov) {
    // "cov" only when that is the remembered choice; a first open, or anything else,
    // lands on the curve. A match missing one of the two never reaches here.
    const v = lastMatchView === "cov" ? "cov" : "wp";
    // No visible caption on either pane: the active glyph and its tooltip name the view,
    // and both charts already carry their own labels — the curve its player names and
    // set rules, the pyramid its per-player totals line.
    const tab = (k, title, label) => `<button type="button" class="mcvtab${v === k ? " on" : ""}"
      data-view="${k}" role="tab" aria-selected="${v === k}" tabindex="${v === k ? 0 : -1}"
      title="${title}" aria-label="${label}">${matchViewIcon(k)}</button>`;
    const pane = (k, art) => `<div class="mcvpane" data-view="${k}"${v === k ? "" : " hidden"}>${art}</div>`;
    head = `<div class="mcv">
      <div class="mcvtabs" role="tablist" aria-label="Top chart">
        ${tab("wp", "This match", "This match — win probability by point")}
        ${tab("cov", "Charted history", "Charted history — charted points by season")}
      </div>
      ${pane("wp", wp)}
      ${pane("cov", cov)}
    </div>`;
  } else {
    // One chart and no switch — a degenerate curve, or a match with no player data on
    // either side. Whichever survived stands on its own labels.
    head = wp || cov;
  }
  return head +
    tape(pa, pb, spread, det) +
    section("serve outcome", `every service point on two axes — how often each delivery
      landed, and what it won`, a, b,
      "", "", "text", serveAnatomy(pa, pb, ma, mb)) +
    section("serve direction", `percent in and percent won by first and second serve`, a, b,
      serveMatchHtml(pa, ma), serveMatchHtml(pb, mb), "text") +
    section("the groundstrokes", `winners and unforced errors per wing, each sized by its
      share of that player's groundstrokes`, a, b,
      "", "", "text", groundAnatomy(pa, pb, ma, mb)) +
    by;
}

// The top-chart switch on a charted match: it flips which pane is shown and remembers the
// choice for the next open. The curve's own scrubber is wired once at render and keeps
// working when its pane returns — it only needs a laid-out box, which it has as soon as
// the pane is unhidden.
function wireMatchView(root) {
  const mcv = root.querySelector(".mcv");
  if (!mcv) return;
  const tabs = [...mcv.querySelectorAll(".mcvtab")];
  const panes = [...mcv.querySelectorAll(".mcvpane")];
  const show = (view) => {
    lastMatchView = view;
    for (const t of tabs) {
      const on = t.dataset.view === view;
      t.classList.toggle("on", on);
      t.setAttribute("aria-selected", String(on));
      t.tabIndex = on ? 0 : -1;
    }
    for (const p of panes) p.hidden = p.dataset.view !== view;
  };
  for (const t of tabs) t.addEventListener("click", () => show(t.dataset.view));
  // Left/right arrows walk the pair, the tablist convention — the focused tab is also the
  // shown one, so moving focus moves the view.
  mcv.querySelector(".mcvtabs").addEventListener("keydown", (e) => {
    if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
    e.preventDefault();
    const i = tabs.findIndex((t) => t.dataset.view === lastMatchView);
    const step = e.key === "ArrowRight" ? 1 : tabs.length - 1;
    const next = tabs[(Math.max(0, i) + step) % tabs.length];
    next.focus();
    show(next.dataset.view);
  });
}

function bodyHtml(m, pa, pb, spread, det) {
  const a = m.a, b = m.b;
  if (det) return matchBodyHtml(m, pa, pb, spread, det);
  const ta = trigSets(pa), tb = trigSets(pb);
  const none = !pa && !pb
    ? `<p class="nochart">Neither player has Match Charting history yet.
       <a href="${CHART_GUIDE}" target="_blank" rel="noopener">Chart a match →</a></p>` : "";
  return (pa || pb ? CHARTED_TITLE + profileBand(pa, pb) : "") +
    tape(pa, pb, spread) +
    section("serve outcome", `percent in and percent won by first and second serve`, a, b,
      "", "", "text", serveAnatomy(pa, pb)) +
    section("serve direction", `where the first serve goes`, a, b,
      serveHtml(pa), serveHtml(pb), "text") +
    none +
    section("serve + 1", `what they do with returns${PAYOFF_LEGEND}`, a, b,
      familyCards(pa, "ret", 2), familyCards(pb, "ret", 2), "cards") +
    section("the groundstrokes", `winners and unforced errors per wing, each sized by its
      share of that player's groundstrokes`, a, b,
      "", "", "text", groundAnatomy(pa, pb)) +
    section("court patterns", `what they do with an incoming ball, × how often the tour
      of their own era plays it from the same
      spot${COURT_LEGEND}${PAYOFF_LEGEND}`, a, b,
      familyCards(pa, "rally", 3), familyCards(pb, "rally", 3), "cards") +
    section("shot-making triggers", `a lead-up that shifts their aggressive shot
      frequency — the share of their rally strokes that count
      as a winner, their own unforced error, or a ball that forces the
      error${meterLegend("their rate with no cue")}`,
      a, b, ta, tb, "text") +
    section("opening cues by court", `the same question as above, asked separately of
      each service court — a wide serve opens opposite wings on the two sides, so a
      pooled cue averages two different serves${meterLegend("their norm for that shot and court")}`,
      a, b, openSets(pa), openSets(pb), "text") +
    (pa || pb ? COV_NOTE : "");
}

// --- the panel as a dialog ----------------------------------------------------------
// It claims aria-modal, so it has to behave like one: focus moves in, Tab stays in, the
// draw behind stops scrolling, and closing hands focus back to the match tile you opened
// from — otherwise a keyboard lands back at the top of the page each time.
const FOCUSABLE = "a[href], button:not([disabled]), summary, [tabindex]:not([tabindex='-1'])";
let opener = null;          // the element that opened the panel, to hand focus back to
// Which match that element was, so the hand-back survives the tile being replaced. The
// draw re-renders whole — on a resize, or when the round or slice under it changes — and
// the card that comes back is an equivalent one, not the node that was clicked. Holding
// only the node, a re-render between open and close dropped focus to <body>, which is the
// thing handing it back exists to prevent.
let openerId = null;
let wired = false;
// Each open takes a ticket. The queries below are async and the panel writes its results
// into slots looked up by id, so an open whose queries outlive it — close one match, open
// the next while the first is still in flight — would render its player under the other
// match's header. A superseded open drops its results instead of painting them.
let openSeq = 0;

// The insights DB is a separate fetch from the draw feed, and the site is deployed without
// it whenever the Release asset is missing (see .github/workflows/live.yml), so a failed
// load is a state the panel has to have words for rather than one it can sit in. It is not
// the "not charted yet" copy: that invites you to go and chart a match that may already be
// charted, which is a different thing to say and, here, a wrong one.
const DATA_DOWN = `<p class="nochart">Player charting data isn't loading right now — the
  draw and scores above are unaffected.</p>`;

function lockPage(on) {
  // <html> is the scroller here, so that is where the lock has to go; body alone does
  // nothing. Hiding the scrollbar widens the page, and the padding it leaves in its
  // place is what keeps the draw behind from jumping sideways as the panel opens.
  const gap = window.innerWidth - document.documentElement.clientWidth;
  document.documentElement.style.overflow = on ? "hidden" : "";
  document.body.style.paddingRight = on && gap ? `${gap}px` : "";
}

export function closeMatchup() {
  const panel = document.getElementById("matchup");
  if (panel.hidden) return;
  panel.hidden = true;
  document.getElementById("scrim").hidden = true;
  lockPage(false);
  // Scanned rather than selected: a match id comes from the feed, so it is not something
  // that can be dropped into a selector unescaped, and a draw is 127 cards at its largest.
  const back = opener && document.contains(opener)
    ? opener
    : openerId && [...document.querySelectorAll(".match[data-mid]")]
      .find((el) => el.dataset.mid === openerId);
  if (back) back.focus();
  opener = null;
  openerId = null;
}

function onPanelKey(e) {
  if (e.key !== "Tab") return;
  const panel = document.getElementById("matchup");
  const items = [...panel.querySelectorAll(FOCUSABLE)].filter((el) => el.offsetParent);
  if (!items.length) return e.preventDefault();
  const first = items[0], last_ = items[items.length - 1];
  // The panel itself holds focus on open, so a first Tab has to land somewhere sensible
  // whichever direction it goes.
  if (!panel.contains(document.activeElement) || document.activeElement === panel) {
    e.preventDefault();
    (e.shiftKey ? last_ : first).focus();
  } else if (e.shiftKey && document.activeElement === first) {
    e.preventDefault(); last_.focus();
  } else if (!e.shiftKey && document.activeElement === last_) {
    e.preventDefault(); first.focus();
  }
}

// The header is the panel's one fixed cost — four screens of profile scroll past it, and
// on a phone a five-set scoreline holds a quarter of the sheet to say what you tapped.
// So once the body starts moving it condenses to the names and the score, and comes back
// when you return to the top. The two thresholds are hysteresis: one value would flicker
// as the collapse itself changes what is under the fold.
// Condensing takes nothing away from the names: the close button leaves the panel at this
// size rather than reserving a lane across the right-hand one, and everything else it
// changes — the name size, the score size — only ever makes them smaller. So the fit
// reached at the top of the scroll still holds at the bottom, and the header settles on one
// layout per match per width instead of trading between two as you read.
function onBodyScroll() {
  const panel = document.getElementById("matchup");
  const t = document.getElementById("matchupBody").scrollTop;
  if (t > 24) panel.classList.add("cond");
  else if (t < 8) panel.classList.remove("cond");
}

// Has either name run past `lines` lines?
//
// The number is a parameter because the ladder below asks the question twice with two
// different answers in mind: one line is what the cheap rungs are trying to buy, and two is
// what the staggered layout can still carry before it is worth giving up.
//
// Line count, and not a width comparison, because there is no width here that answers the
// question. A name is a flex item with min-width:0, so it never gets wider than its track —
// it wraps instead — and .mname overflows visible, for which scrollWidth is just
// clientWidth again even with the text held on one line. The two numbers came back equal
// for a name plainly wrapped in two, so nothing was ever found to be short.
//
// clientHeight, not a rect: the panel opens under the `pop` animation, which scales it to
// .97, and a rect is the *visual* box. Height and line-height are both layout, so the
// animation cannot be seen from here — which matters, since this runs during it.
function namesOver(grid, lines) {
  for (const n of grid.querySelectorAll(".mname")) {
    const lh = parseFloat(getComputedStyle(n).lineHeight);
    if (lh > 0 && n.clientHeight > lh * (lines + 0.5)) return true;
  }
  return false;
}

// Fit the scoreboard to the match in front of it, measured rather than assumed, giving up
// the cheapest thing first.
//
// Four things to spend, in the order they are worth least.
//
// The gap either side of the score is the cheapest: it keeps the games off the end of a
// name, which is worth 40px when 40px is spare and worth nothing at all beside a name broken
// over two lines. So it goes first, and only down to the point where the names fit — no
// further, since it buys nothing past that.
//
// The first name is next: "Alexander Zverev" down to "A. Zverev" costs the part of the name
// carrying least, and a surname still says who this is. Cheaper than either a wrap or the
// layout, so it is spent before both — and only when the gap alone didn't get there, which
// is the part a media query could never do. The old rule abbreviated at 700px flat, so every
// phone got initials whether the full name would have fitted or not.
//
// A second line on a name comes next, and it is the last thing spent before the layout.
// The stagger carries a two-line name perfectly well — each scoreline is still out beside
// the name it belongs to — and it carries it in less height than the fallback needs: a
// five-set phone header measures 102px staggered over two lines against 113px stacked over
// one. A wrap looks like the failure and isn't; the fallback is the failure.
//
// The staggered layout is the dear one. It is what ties each scoreline to the name it
// belongs to, and its fallback — both names level, the games stacked between them — works
// at any width but says less: the games become two columns either side of a centre line
// with nothing but position to say whose are whose. So it is given up last, and only when a
// closed-up gap and an abbreviated name still leave a name needing a third line.
//
// The gap is re-spent after each of the other three, because every one of them changes what
// the names have to fit into and the cheapest thing is worth re-offering against the new
// question.
//
// When that happens depends on the match as much as on the window: five sets of games take
// twice the middle of the band that straight sets do, and "A. Zverev" is not the width of
// "Q. Halys". A breakpoint can see none of that: switching at 620px, wider than any phone in
// portrait, gives every phone a fallback none of them needs.
//
// Above 620px the stacked class is inert (see the stylesheet): there is room on a wide panel
// for a long name to take two lines, and the stagger is still the better header. Setting it
// there changes nothing, so the last gap pass simply re-reaches the same answer.
//
// Runs on open and on resize, and not on the body's scroll: each pass forces layout several
// times over, and condensing takes nothing off a name — see onBodyScroll.
// Set the widest gap in [min, max] that still holds every name inside `lines` lines, and say
// whether there was one. Left at the full gap when even min can't manage it, since a gap
// given up to a wrap that happened regardless is just a narrower gap.
//
// Searched rather than calculated: what a name needs is only knowable by laying it out, and
// the arithmetic — a gap surrendered returns twice itself to the two name tracks — quietly
// stops holding once both names are against the limit at the same time. Line count is
// monotonic in the gap, though; narrowing it can only ever give the names room. So the
// boundary can be bisected, with lo always fitting and hi never, in five or six passes.
function fitGap(grid, max, min, lines) {
  const setGap = (g) => grid.style.setProperty("--mgap", `${g}px`);
  const over = () => namesOver(grid, lines);
  if (!over()) return true;                            // fits at the full gap
  setGap(min);
  if (over()) { grid.style.removeProperty("--mgap"); return false; }
  let lo = min, hi = max;
  while (hi - lo > 1) {
    const mid = Math.floor((lo + hi) / 2);
    setGap(mid);
    if (over()) hi = mid; else lo = mid;
  }
  setGap(lo);
  return true;
}

// The gap between one set's games and the next, closed up before anything is taken off a
// name. A five-set line carries four of these across the middle of the band — ~44px at 11px
// apiece — so once the header is under any pressure at all they are the first width handed
// back. Unlike the name-side gap in fitGap, this one is kept narrow even when it does not
// close the fit on its own: the reader has said a tighter set line is fine here, and the
// abbreviation or wrap that follows does less damage with the score block already smaller.
const SGAP_MAX = 11, SGAP_MIN = 4;
function fitScoreGap(grid) {
  const score = grid.querySelector(".mscore");
  if (!score) return;
  const set = (g) => score.style.setProperty("--sgap", `${g}px`);
  const over = () => namesOver(grid, 1);
  // Only under pressure — measured on the full staggered layout the caller has just reset to.
  if (!over()) return;
  set(SGAP_MIN);
  if (over()) return;                                  // keep it at the minimum
  let lo = SGAP_MIN, hi = SGAP_MAX;                    // otherwise the widest that still fits
  while (hi - lo > 1) {
    const mid = Math.floor((lo + hi) / 2);
    set(mid);
    if (over()) hi = mid; else lo = mid;
  }
  set(lo);
}

function fitHeader() {
  const grid = document.querySelector("#matchupHead .mgrid");
  if (!grid) return;
  // Both off first: the question is what the *full* staggered layout does, so that has to
  // be the thing measured. Left set from a narrower window they would answer about
  // themselves and never come back off.
  grid.classList.remove("stacked", "abbr");
  grid.style.removeProperty("--mgap");
  const score = grid.querySelector(".mscore");
  if (score) score.style.removeProperty("--sgap");

  const cs = getComputedStyle(grid);
  const max = parseFloat(cs.getPropertyValue("--mgap-max")) || 0;
  const min = parseFloat(cs.getPropertyValue("--mgap-min")) || 0;

  // the inter-set gap first — the cheapest give, and it never touches a name
  fitScoreGap(grid);
  // full names, staggered — spend only the gap
  if (fitGap(grid, max, min, 1)) return;
  // first name to an initial, and the gap offered again against the shorter names
  grid.classList.add("abbr");
  if (fitGap(grid, max, min, 1)) return;
  // a second line, still staggered, and the gap spent again to hold the names to two
  if (fitGap(grid, max, min, 2)) return;
  // still not enough: give the stagger up too, and spend the gap into what replaced it
  grid.classList.add("stacked");
  fitGap(grid, max, min, 1);
}

let fitQueued = false;
function onResize() {
  if (fitQueued) return;
  fitQueued = true;
  requestAnimationFrame(() => { fitQueued = false; fitHeader(); });
}

// The charted-history readout opens on hover for a mouse. A coarse pointer has no hover — a
// tap is a click there and nothing else — so on those devices a tap on a season's half of the
// band pins its readout open, a tap on another season moves it, and a tap anywhere else in
// the panel lets it go. One at a time: the readout is a floating strip and two would overlap.
// Left to the mouse elsewhere, where :hover already does this and a pinned strip would just be
// in the way.
function onCovTap(e) {
  if (!matchMedia("(hover: none)").matches) return;
  const band = e.currentTarget;
  const open = band.querySelector(".covbar.on");
  const bar = e.target.closest(".covbar[data-lbl]");
  if (open && open !== bar) open.classList.remove("on");
  if (bar) bar.classList.toggle("on");
}

export async function openMatchup(m, t) {
  const mine = ++openSeq;
  const panel = document.getElementById("matchup");
  const body = document.getElementById("matchupBody");
  if (panel.hidden) { opener = document.activeElement; openerId = m.id; }
  panel.hidden = false;
  panel.setAttribute("aria-label", `${m.a.name || "TBD"} vs ${m.b.name || "TBD"}`);
  document.getElementById("scrim").hidden = false;
  lockPage(true);
  if (!wired) {
    panel.addEventListener("keydown", onPanelKey);
    body.addEventListener("scroll", onBodyScroll, { passive: true });
    body.addEventListener("click", onCovTap);
    window.addEventListener("resize", onResize, { passive: true });
    wired = true;
  }
  const round = t.rounds.find((r) => r.matches.some((x) => x.id === m.id));
  document.getElementById("matchupHead").innerHTML = headHtml(m, t, round);
  fitHeader();
  body.scrollTop = 0;
  panel.classList.remove("cond");
  panel.focus();
  // An unfilled match — a final whose two slots are both still TBD — has no body to write.
  // Everything below the scoreboard is keyed to a player: two charted histories, the
  // patterns each of them plays, a number for which of them wins. With neither side known
  // that came out as a run of empty sections, a win probability apologising for itself and
  // a notation key for drawings that weren't there, all of it under a header that had
  // already said "TBD vs TBD" — five screens restating one word. The header keeps saying
  // which round this is, and the panel stops there.
  if (!isEntrant(m.a) && !isEntrant(m.b)) {
    body.innerHTML = "";
    return;
  }
  body.innerHTML = `<div id="cardslot" class="loading">Loading…</div>
    ${notationHelp()}`;

  let pa, pb, spread, det;
  try {
    // The sidecar rides alongside the two player queries rather than after them: it is a
    // static file on the same origin and there is nothing in the panel that needs one
    // before the other.
    [pa, pb, det] = await Promise.all([
      playerData(m.a.matched, t.gender),
      playerData(m.b.matched, t.gender),
      matchDetail(m.chart_id),
    ]);
    // Oriented at use rather than in the cache: the sidecar is keyed by chart id and the
    // side order belongs to the draw slot that opened it.
    det = orientDetail(det, m.chart_flip);
    spread = (await tourSpread())[t.gender] || {};
  } catch (e) {
    console.warn("insights db unavailable:", e);
    if (mine !== openSeq) return;
    const down = document.getElementById("cardslot");
    down.classList.remove("loading");
    down.innerHTML = DATA_DOWN;
    return;
  }
  if (mine !== openSeq) return;

  const slot = document.getElementById("cardslot");
  slot.classList.remove("loading");
  slot.innerHTML = bodyHtml(m, pa, pb, spread, det);
  if (det) {
    // The shot-notation key is written before the data arrives, and it sits outside the slot
    // this line replaces. It explains court zones, rally patterns and the trigger framework —
    // a key to four sections a charted match doesn't render, under a panel whose own jargon
    // is explained by figureKey. It goes with them.
    const key = body.querySelector(".notekey:not(.figkey)");
    if (key) key.remove();
    if (slot.querySelector(".wp")) {
      slot._wp = det.wp;
      wireWpChart(slot);
    }
    wireMatchView(slot);
  }
}
