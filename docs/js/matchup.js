// The matchup drawer: a card per player, and on a charted match the experimental win
// probability through it, all queried from insights.duckdb via DuckDB-WASM.
import { query, tourSpread } from "./db.js";
import { patternSvg, pairSvg, retSvg, shotLine } from "./court.js";
import { dayLong, localStart } from "./schedule.js";
import { flagEmoji } from "./flags.js";
import { ename, isEntrant } from "./feed.js";

const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const CHART_GUIDE =
  "https://www.tennisabstract.com/blog/2015/09/23/the-match-charting-project-quick-start-guide/";
const last = (name) => String(name || "").split(" ").slice(-1)[0];
// One decimal, except "100%" at the top and a bare "0" (no sign) at the bottom, judged after
// rounding.
const pct = (x) => {
  const v = Math.round(Number(x) * 1000) / 10;
  return v === 0 ? "0" : v === 100 ? "100%" : v.toFixed(1) + "%";
};

// A finished match's date, short ("Jul 13, 2026"), or "" when absent or unparseable. Read in
// UTC, so a US night session starting after ~20:00 ET shows a day late.
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
      "win_rate, tour_win_rate, state_win_rate, serve_side, serve_dir, " +
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
// The per-match sidecar (win-probability curve and box score) from `site build-match-details`,
// fetched only when a charted match is opened. A failed fetch caches as null and the panel
// falls back to the career sections.
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

// The sidecar is ordered from the chart's player1 and the draw by bracket slot, and they
// disagree about half the time. `chart_flip` (from build_brackets._chart_of) says when to
// mirror. Win probability flips to its complement; leverage belongs to the point and doesn't.
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

// This match's rates under the career field names, so donut() and profileParts() draw both.
// No coverage floor: a match rate is a count of what happened, not an estimate.
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
    // Second-serve points won is over every point that reached a second serve, double faults
    // included.
    first_won_pct: rate(s.first_won, s.first_in),
    second_won_pct: rate(s.second_won, s.second_pts),
    len_won: s.len_won == null ? null : Number(s.len_won),
    dirs: s.dirs, dirs2: s.dirs2,
    aces: s.aces, dfs: s.dfs, serve_pts: s.serve_pts,
    // Counts, not a save rate: the median player faces seven break points a match.
    bp_faced: s.bp_faced, bp_saved: s.bp_saved,
    // The raw serve tallies the anatomy bar splits — see serveSplit(). The two ace counts
    // ride with them because they are the cores drawn inside those same columns.
    first_in: s.first_in, first_won: s.first_won,
    second_pts: s.second_pts, second_won: s.second_won,
    aces_first: s.aces_first, aces_second: s.aces_second,
    ...shotMix(s),
  };
}

// Shot mix and per-wing outcomes from the sidecar's per-stroke tallies
// (build_match_details._fold_point). The mix is over every non-serve stroke; outcome rates are
// over that wing's groundstrokes. The denominators ride along because the figures print them.
// All null on a sidecar without these tallies, and the figure falls back to the career reading.
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

// No shot-quality verdict prints here: class_rel_z still ships but mostly measures rally
// length. See experiments/class_relative_wpa.

// A collapsed mini-court under a pattern: tap to see where the lead-up shots landed,
// drawn on the fly from the notation (client twin of viz.rally_svg). Empty when the
// pattern has no chartable direction, so there's nothing to draw.
function rallyDrawer(pattern, mirror = false, court = "deuce") {
  const svg = patternSvg(pattern, mirror, court);
  return svg ? `<details class="rally"><summary>ball path</summary>
    <div class="court">${svg}</div></details>` : "";
}

// A cue's two numbers as one bar: its length is the aggressive shot frequency the cue provokes,
// the colour change is how much of that landed, and the tick is the rate without the cue. Drawn
// like the comparison strip's winners-and-errors row, on a 0–1 domain.
//
// The tick is the player's pooled no-cue rate. A cue confirmed in only one held-out fold ships
// that fold's lift, so the printed multiple and the bar can disagree slightly. `base` is the
// tick; opening cues omit it and it is recovered as att_rate / att_lift.
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

// Cue contexts are stored in the player's own frame (mirrored for a left-hander), so the
// drawing mirrors back to the real court.
function trigLine(t, hand, base) {
  // Two-shot cues only; see experiments/rally_patterns for why no 3-4 shot tier ships.
  const trap = t.tag === "trap";
  const cls = trap ? "bait" : "green";
  const conv = Math.round(t.conversion * 100);
  // Conversion is compared with the player's other cues, not their all-strokes rate, which sits
  // well below any cue's.
  const payoff = trap
    ? `converts only <b>${conv}%</b>
       <span class="lift">${Math.round(t.conv_delta * 100)}pp vs their other cues</span>`
    : `converts <b>${conv}%</b>`;
  const against = "their norm";
  // Both denominators print: frequency is over n, conversion over attempts (about a third of n).
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

// First-serve placement. Only wide and T print, since charters disagree on body serves by
// ±4-6 points, so the two don't sum to 100. The query keeps only `reliable` sides.
function serveHtml(d) {
  const rows = (d && d.serve) || [];
  if (!rows.length) return "";
  // Whole percents, to match serveMatchHtml. Named apart from `pct` to avoid shadowing it.
  const wholePct = (v) => `${Math.round(Number(v) * 100)}%`;
  const order = { deuce: 0, ad: 1 };
  const sorted = [...rows].sort((a, b) => order[a.side] - order[b.side]);
  // Laid out as the server sees it: deuce box left, ad box right, zones in court order (the
  // same mapping court.js uses). --p drives the backfill behind each number.
  const zone = (label, v) =>
    `<span class="srvzone" style="--p:${(Number(v) * 100).toFixed(1)}%">
      <span class="zl">${label}</span><b>${wholePct(v)}</b></span>`;
  const box = (r) => {
    const zones = r.side === "ad"
      ? zone("T", r.t) + zone("wide", r.wide)
      : zone("wide", r.wide) + zone("T", r.t);
    return `<div class="srvbox">${zones}
      <span class="srvlabel">${r.side} · n≈${Number(r.n_eff).toLocaleString()}</span></div>`;
  };
  // The player's own recency window (matches still carrying a tenth of the newest's weight)
  // and its year span, since "recent" can reach back years for a thinly-charted player.
  const win = Number(sorted.find((r) => r.matches)?.matches) || null;
  const span = sorted.find((r) => r.years)?.years?.replace("-", "–");
  const caption = `<p class="srvwin">${win ? `last ${win} charted matches` : "recent matches"}${span ? ` (${span})` : ""}</p>`;

  // Say when the recent mix differs a lot from the career one.
  let moved = "";
  const big = sorted
    .filter((r) => Number(r.drift_ratio) >= 1.5 && Math.abs(r.t - r.career_t) >= 0.05)
    .sort((a, b) => Math.abs(b.t - b.career_t) - Math.abs(a.t - a.career_t))[0];
  if (big) {
    moved = `<p class="tnum">${big.side} court: T share ${big.t > big.career_t ? "up from" : "down from"} <b>${wholePct(big.career_t)}</b>
      across their whole career</p>`;
  }
  // Break points, side-adjusted since they skew to the ad court. Most players show nothing.
  let bp = "";
  const delta = d.s && d.s.serve_bp_wide_delta;
  // Significant and at least five points, since a large sample certifies tiny shifts.
  const BP_MIN = 0.05;
  if (d.s && Number(d.s.serve_bp_sig) === 1 && delta != null && Math.abs(delta) >= BP_MIN) {
    const pts = Math.round(Math.abs(delta) * 100);
    // Whole-career window, unlike the rest of this section, so the line says so.
    bp = `<p class="srvbp" title="a shift this size clears the experiment's significance
      test and is large enough to play against; most players show nothing here">on break
      points, <b>${pts} points</b> ${delta > 0 ? "wider" : "less wide"} than their own norm
      <span class="srvbpwin">across their whole charted career</span></p>`;
  }
  return `<div class="srv">
    <div class="srvcourt">${sorted.map(box).join("")}</div>
    ${caption}${moved}${bp}</div>`;
}

// The same strip for one match: wide, body and T as counts with shares, and each zone's career
// share underneath. First deliveries, landed or faulted, as in the career mix.
function serveMatchHtml(d, md) {
  if (!md || !md.dirs) return "";
  const career = new Map(((d && d.serve) || []).map((r) => [r.side, r]));
  const NAMES = ["wide", "body", "T"];
  const zone = (label, n, tot, ref) => {
    const f = tot ? n / tot : 0;
    // A zone with no serves prints no percentage but keeps its line, so rows stay level.
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
    // Same zone order as the career strip.
    const order = side === "ad" ? [2, 1, 0] : [0, 1, 2];
    // career_wide / career_t, not the recency-weighted wide / t, because the line says "career".
    const refOf = (i) => (!ref ? null : i === 0 ? ref.career_wide : i === 2 ? ref.career_t : null);
    return `<div class="srvbox">${order.map((i) => zone(NAMES[i], c[i], tot, refOf(i))).join("")}
      <span class="srvlabel">${side} · ${tot} ${serve} serves</span></div>`;
  };
  const boxes = ["deuce", "ad"].map((k) => box(md.dirs, k, "first", true)).join("");
  if (!boxes) return "";
  // Second serves split by court like the first, since the two courts open opposite wings.
  // No career anchor: the shipped placement mix is first serves only.
  const second = ["deuce", "ad"].map((k) => box(md.dirs2, k, "second", false)).join("");
  return `<div class="srv">
    <div class="srvcourt">${boxes}</div>
    ${second ? `<div class="srvcourt second">${second}</div>` : ""}
    <p class="srvwin">this match only</p></div>`;
}

// Court-state patterns (court_response experiment): how the player answers an incoming ball
// against the field's answers to the same ball. Zones are named by the player's own hands, and
// every pattern replicated in both halves of their charted matches.
function patternCard(p) {
  // Payoff: their win rate with this response against their own rate on the same ball however
  // else they answer it. A tour baseline would mostly rank players rather than choices. A tie
  // prints "=", so a missing arrow always means no comparison.
  let payoff = "";
  if (p.win_rate != null) {
    const w = `wins <b>${Math.round(p.win_rate * 100)}%</b>`;
    // Just the two numbers; the section note explains them.
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
  // The serve+1 family's drawing starts at the serve. Stroke kinds are passed so a volley isn't
  // drawn with a bounce under it.
  const court = p.family === "ret"
    ? retSvg(p.serve_side, p.serve_dir, p.inc_code, p.resp_code, p.state_depth,
      p.state_kind, p.resp_kind)
    : pairSvg(p.inc_code, p.resp_code, p.state_depth, p.state_kind, p.resp_kind);
  // Both denominators: n_state is how often they faced the ball.
  const of = num(p.n_state);
  const n = `n=${Number(p.count).toLocaleString()}${of
    ? `<span class="pof">/${of.toLocaleString()}</span>` : ""}`;
  // Count and payoff on separate lines, so drop the joining " · ".
  const win = payoff.replace(/^ · /, "");
  return `<div class="pcard2">
    <div class="pcourt">${court}</div>
    <div class="pmeta">
      <p class="plift">${Number(p.lift).toFixed(1)}×<span> the tour</span></p>
      <p class="pdesc">${esc(p.state)}<b>→ ${esc(p.response)}</b></p>
      <p class="pn">${n}</p>
      ${win ? `<p class="pfoot">${win}</p>` : ""}
    </div>
  </div>`;
}

const familyCards = (d, fam, n) => !d ? "" :
  d.patterns.filter((p) => p.family === fam).slice(0, n).map(patternCard).join("");

// The player's no-cue aggressive shot frequency and conversion: the first bar in the column, on
// the same scale as the cue bars, and the rate their ticks mark.
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
      </p>
    <div class="tmeter"><i style="width:${(att * 100).toFixed(1)}%">${segs}</i></div>
  </div>`;
}

// One opening cue: like a pooled trigger, but measured against the player's norm for that shot
// on that service court. The court is named in the row and passed to the drawing, since a wide
// serve is a different ball on each side.
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

// Baseline rate, then green lights, then traps. The baseline comes from player_summary, so it
// prints even when no cue clears the significance test.
function trigSets(d) {
  if (!d) return "";
  const base = trigBase(d);
  if (!d.triggers.length) return base;
  const greens = d.triggers.filter((t) => t.tag === "green")
    .sort((a, b) => b.att_lift - a.att_lift).slice(0, 3);
  const traps = d.triggers.filter((t) => t.tag === "trap")
    .sort((a, b) => a.conv_delta - b.conv_delta).slice(0, 2);
  // Check the rows too, so "no trap sequences" never prints above a trap.
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

// --- "basic stats": one ring ---------------------------------------------------------
// One shared axis bent into a circle: 6 o'clock is zero, A sweeps up the left and B up the
// right, and the top is 100%. The arc is service games held; the tick across the band is return
// games broken. Games rather than points, because point rates are too close together to see.
const clamp01 = (x) => Math.max(0, Math.min(1, x));
const num = (v) => (v == null ? null : Number(v));

// Career hold and break rates print only above 2,000 charted points (the same floor as the win
// probability's confidence bands). No shrinkage: the thin players it would help are excluded.
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

// Clock degrees for a sweep of `s`: both players leave 6 o'clock, A up the left, B up the right.
const dnAt = (s, side) => (side === "a" ? 180 + s : 180 - s);

// A sweep as a dash on a full circle, rotated to start at 6 o'clock (and mirrored for B), which
// avoids arc flags.
function dnArc(deg, side) {
  if (!(deg > 0)) return "";
  const spin = side === "b"
    ? `translate(${DN_C * 2},0) scale(-1,1) rotate(90 ${DN_C} ${DN_C})`
    : `rotate(90 ${DN_C} ${DN_C})`;
  const seg = DN_LEN * deg / 360;
  return `<g transform="${spin}"><circle class="dseg ${side}" cx="${DN_C}" cy="${DN_C}"
    r="${DN_R}" stroke-dasharray="${seg.toFixed(2)} ${DN_LEN.toFixed(2)}"/></g>`;
}

// A spoke across the ring at `deg`, `out` past the outer edge and `inn` past the inner.
function dnSpoke(deg, out, cls, inn = out) {
  const [x1, y1] = dnPoint(deg, DN_R - DN_W / 2 - inn);
  const [x2, y2] = dnPoint(deg, DN_R + DN_W / 2 + out);
  return `<line class="${cls}" x1="${x1.toFixed(2)}" y1="${y1.toFixed(2)}"` +
    ` x2="${x2.toFixed(2)}" y2="${y2.toFixed(2)}"/>`;
}

// The break-rate tick: a dark spoke under a light one, so it shows on both arc and track.
const dnTick = (deg) => dnSpoke(deg, 1.6, "dtickhalo") + dnSpoke(deg, 1.6, "dtick");

// Zero, cut into the foot of the ring in the card colour so the two sweeps don't merge.
const dnOrigin = () => dnSpoke(180, 0.5, "dorigin");

// Ink marks at 12 and 6 o'clock for the ends of the scale. `inn: 0` keeps them clear of the
// labels in the hole.
const DN_END_OUT = 1.2;
const dnEnds = () => dnSpoke(0, DN_END_OUT, "dend", 0) + dnSpoke(180, DN_END_OUT, "dend", 0);

// --- the floating labels -------------------------------------------------------------
// Each figure sits beside its mark: the hold figure at the arc's end, the break figure by the
// tick. Positions are percentages of a box the size of the drawing, on a circle just outside
// the band; A's labels reach left, B's right.
const DN_LR = 45;

function dnLabel(x, y, side, cls, html) {
  return `<span class="dlab ${side} ${cls}"
    style="left:${x.toFixed(2)}%;top:${y.toFixed(2)}%">${html}</span>`;
}

// Minimum vertical gap between the two figures, in viewBox units at the smallest ring. Only
// bites for players who break about as often as they hold (2 of 363); the pair then moves
// apart around its midpoint.
const DN_SEP = 10.5;

function dnSpread(a, b) {
  const d = b.y - a.y;
  if (Math.abs(d) >= DN_SEP) return [a, b];
  const push = (DN_SEP - Math.abs(d)) / 2 * (d < 0 ? -1 : 1);
  return [{ x: a.x, y: a.y - push }, { x: b.x, y: b.y + push }];
}

const dnCell = (art) => `<div class="dn">${art}</div>`;

function donut(r, sa, sb) {
  const va = sa ? num(sa[r.k]) : null;
  const vb = sb ? num(sb[r.k]) : null;
  if (va == null && vb == null) return "";
  // Which side has the better figure: "" when either is missing, they tie, or there's no
  // better end.
  const leadOf = (xa, xb) => r.better && xa != null && xb != null && xa !== xb
    ? ((xa > xb) === (r.better === "hi") ? "a" : "b") : "";
  const lead = leadOf(va, vb);
  const at = (v) => clamp01(v / r.hi) * 180;
  // The break rate, read once for both the tick and its label.
  const markOf = (s) => (!r.mark || !s ? null : num(s[r.mark.k]));
  const markLead = leadOf(markOf(sa), markOf(sb));
  const anchor = (deg, side) => {
    const [x, y] = dnPoint(dnAt(deg, side), DN_LR);
    return { x, y };
  };
  // A side with no rate shows an em dash at the foot of its empty half.
  const labels = (v, s, side) => {
    if (v == null) return `<span class="dlab ${side} dnone">—</span>`;
    const m = markOf(s);
    // Figure nearest the ring on both sides: word first on A, figure first on B.
    const flank = (word, fig) => esc(side === "a" ? `${word} ${fig}` : `${fig} ${word}`);
    // Placed as a pair; see dnSpread().
    let pa = anchor(at(v), side), ga = m == null ? null : anchor(at(m), side);
    if (ga) [pa, ga] = dnSpread(pa, ga);
    const unit = r.unit ? `<span class="dvu">${esc(r.unit)}</span>` : "";
    const held = side === "a" ? `${unit}${r.fmt(v)}` : `${r.fmt(v)}${unit}`;
    const out = [dnLabel(pa.x, pa.y, side, `darc${lead === side ? " lead" : ""}`, held)];
    if (ga) {
      // Bold on the side that breaks more.
      out.push(dnLabel(ga.x, ga.y, side, `dtck${markLead === side ? " lead" : ""}`,
        flank(r.mark.label, pct(m))));
    }
    return out.join("");
  };

  // Screen readers hear "no data"; the drawing shows an em dash.
  const say = (v) => (v == null ? "no data" : r.fmt(v));
  const aria = `${r.label} — ${say(va)} against ${say(vb)}`
    + (r.mark ? `; ${r.mark.label} ${say(markOf(sa))} against ${say(markOf(sb))}` : "");
  // The ring's short name, inside the hole.
  const title = r.short
    ? `<p class="dnttl">${r.short.map(esc).join("<br>")}</p>` : "";
  // The scale ends, inside the hole.
  return dnCell(`<div class="dnring">
      <svg viewBox="0 0 100 100" xmlns="http://www.w3.org/2000/svg" role="img"
        aria-label="${esc(aria)}">
        <circle class="dtrack" cx="${DN_C}" cy="${DN_C}" r="${DN_R}"/>
        ${va == null ? "" : dnArc(at(va), "a")}${vb == null ? "" : dnArc(at(vb), "b")}
        ${dnOrigin()}${dnEnds()}
        ${/* a tick only where that side has an arc */""}
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
// On a charted match this replaces the charted-history pyramid. It diverges about 50%, B's
// colour above the line and A's below, and opens at the pre-match estimate from the two
// players' charted records rather than at 50%. Strokes are non-scaling, so widths are CSS
// pixels at any panel width.
const WP_W = 720, WP_H = 168, WP_MID = WP_H / 2;

function wpPath(curve) {
  const n = curve.length;
  const x = (i) => (n < 2 ? 0 : (i / (n - 1)) * WP_W);
  // The curve is A's probability, but B's certainty is the top of the box, matching the
  // scoreboard, which stacks B's row over A's.
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
  // The winner comes from the draw, not the last charted point, so retirements come out right.
  const won = a.winner === true ? 1 : b.winner === true ? 2 : w.won;
  const { line, area, x, y } = wpPath(w.curve);
  const n = w.curve.length;
  // Set boundaries as vertical rules.
  const idxOf = (pt) => w.curve.findIndex((c) => c[0] >= pt);
  const bounds = (w.sets || []).map(idxOf).filter((i) => i > 0);
  const rules = bounds.map((i) => `<line class="wpset" x1="${x(i).toFixed(2)}" y1="0"
      x2="${x(i).toFixed(2)}" y2="${WP_H}" vector-effect="non-scaling-stroke"/>`).join("");
  // Set labels, each centred in its own span, in percent of the plot.
  const edges = [0, ...bounds, n - 1];
  const setLabels = edges.slice(0, -1).map((start, k) => {
    const mid = n < 2 ? 0 : ((start + edges[k + 1]) / 2) / (n - 1) * 100;
    return `<span class="wpsetn" style="left:${mid.toFixed(2)}%">set ${k + 1}</span>`;
  }).join("");
  // Each wp is the state before a point, so the tail is carried to 0 or 1 from `won`.
  const endY = won === 1 ? WP_H : 0;
  const endX = WP_W;
  const winner = won === 1 ? a : b;
  // Quoted for B, the player the chart climbs toward.
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
      ${/* An HTML marker placed in percent, since an SVG circle would stretch with the box. */""}
      <span class="wpdot"></span>
      <span class="wpcap top">${esc(shortName(b.name))}</span>
      <span class="wpcap bot">${esc(shortName(a.name))}</span>
    </div>
    <div class="wpaxis">${setLabels}</div>
    <p class="wpread"><span class="wprl">before a ball was struck</span>
      <b>${pre}%</b> <span class="wprn">${esc(shortName(b.name))}</span></p>
  </div>`;
}

// Surname only; the full names are in the header.
const shortName = (name) => last(name || "") || String(name || "");

// The crosshair and readout. Pointer events, so a touch drag scrubs the curve on a phone.
function wireWpChart(root) {
  const wrap = root.querySelector(".wp");
  if (!wrap) return;
  const plot = wrap.querySelector(".wpplot"), svg = wrap.querySelector("svg");
  const read = wrap.querySelector(".wpread");
  const cross = wrap.querySelector(".wpcross"), dot = wrap.querySelector(".wpdot");
  // The oriented copy from the caller; _details holds the raw one.
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
// Charted points per season, one row per year, A's bars running left of a shared centre axis
// and B's right, so one busy season reads differently from steady coverage. Both players share
// one scale, so a lightly-charted player never looks as well covered as a heavily-charted one.
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

// Rulers at a quarter, half and three-quarters of the busiest bar, labelled to two significant
// figures.
const rulersAt = (max) => (max > 0 ? [0.25, 0.5, 0.75].map((f) => max * f) : []);

// A ruler's figure: its value to two significant figures, then shortened — 2352 -> "2.4k",
// 446 -> "450". Not an exact count of anything; the readout carries those.
function kfmt(n) {
  const mag = Math.pow(10, Math.floor(Math.log10(n)) - 1);
  const r = Math.round(n / mag) * mag;
  return r >= 1000 ? `${r / 1000}k` : `${r}`;
}

// One season's bar for one player. An empty year still gets its row, so gaps show. The length
// floor is set in CSS (.covbar i) so a single match stays visible. With `segs`, a season is
// split into one block per match, oldest against the axis; below SEG_MIN_PCT of the peak it
// stays one block.
const SEG_MIN_PCT = 2;
function coverBar(r, sc, tag, segs) {
  if (!r) return `<span class="covbar ${tag}"></span>`;
  const pts = Number(r.points) || 0, mt = Number(r.matches) || 0;
  // `title` for the mouse; `data-lbl` for the readout that opens on hover or tap (onCovTap).
  // Bars stay out of the tab order. The readout leads with the year, since the axis only labels
  // the ends.
  const lbl = `${r.year} · ${mt} ${mt === 1 ? "match" : "matches"} · ${pts.toLocaleString()} points`;
  // Flex packs blocks against the axis, so A's list is reversed to keep the oldest match there.
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

// Each side's match and point totals. No date range: the axis already shows it.
function coverSum(d, tag) {
  if (!d) {
    return `<span class="covsum ${tag}">not charted yet —
      <a href="${CHART_GUIDE}" target="_blank" rel="noopener">chart a match →</a></span>`;
  }
  const mt = Number(d.s.matches_charted) || 0;
  return `<span class="covsum ${tag}">${mt} ${mt === 1 ? "match" : "matches"} ·
    ${Number(d.s.points_charted).toLocaleString()} points</span>`;
}

// Newest season at the top, so current form is the first row on a phone. Only the two end
// years are labelled; every year between still gets a row.
function coverPyramid(da, db, sc) {
  const by = (d) => new Map(((d && d.years) || []).map((r) => [Number(r.year), r]));
  // Each season's per-match point counts, in play order, for coverBar's blocks.
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
  // Three rulers per half, each line and its figure placed by the same offset.
  const ticks = rulersAt(sc.max);
  // No rulers over an empty half.
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
  // Ruler figures, without a unit.
  const foot = ruler
    ? `<p class="covfoot">${scale(da, "a", -1)}${scale(db, "b", 1)}</p>` : "";
  const say = [`charted points by season, ${sc.lo} to ${sc.hi}`]
    .concat([[da, "left"], [db, "right"]].map(([d, side]) => {
      const p = peakOf(d);
      return p ? `${last(d.s.player)}, ${side}: busiest ${p.y}, ${p.mt} ${p.mt === 1 ? "match" : "matches"}` : "";
    }).filter(Boolean)).join("; ");
  // Past 18 seasons the rows get shorter.
  const dense = sc.hi - sc.lo + 1 > 18 ? " dense" : "";
  return `<div class="cov${dense}">
    <b class="covend hi" aria-hidden="true">${sc.hi}</b>
    <div class="covgrid" role="img" aria-label="${esc(say)}">${ruler}${rows.join("")}</div>
    <b class="covend lo" aria-hidden="true">${sc.lo}</b>
    ${foot}</div>`;
}

// Fallback for a build with no player_years table: the summary line carries the year span.
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
  // One scale for both players.
  const sc = yearScale(da && da.years, db && db.years);
  const head = sc ? coverSum(da, "a") + coverSum(db, "b")
    : coverPlain(da, "a") + coverPlain(db, "b");
  return `<div class="pband">
    <p class="covtop">${head}</p>
    ${sc ? coverPyramid(da, db, sc) : ""}</div>`;
}

// A figure's value for one player.
const figOf = (f, s) => (!s ? null : num(s[f.k]));

// The per-player figures in the two style columns. `better` marks those with a winning end, so
// the winner can be set in ink; variety and rally length have none.
const FIGS = [
  {
    k: "bits", label: "variety", unit: "bits", band: "bits",
    fmt: (v) => v.toFixed(1),
  },
  // Shot mix. `den` names the count a match reading is divided by, printed under the figure.
  // The slice has a share but no outcome rates, which are too noisy to draw.
  {
    k: "slice_pct", label: "slice share", unit: "", band: "slice_pct",
    fmt: pct, den: "shots",
  },
  {
    k: "net_pct", label: "net share", unit: "", band: "net_pct",
    fmt: pct, den: "shots",
  },
  // Net winner and error rates are uncorrelated (r = -0.00), so both print.
  {
    k: "net_winner_pct", label: "net winner rate", unit: "", band: "net_winner_pct",
    fmt: pct, better: "hi", den: "net_shots",
  },
  {
    k: "net_err_pct", label: "net error rate", unit: "", band: "net_err_pct",
    fmt: pct, better: "lo", den: "net_shots",
  },
  // Return winners over points returned. The ace rate is on the serve plot.
  {
    k: "ret_winner_rate", label: "return winners", unit: "", band: "ret_winner_rate",
    fmt: pct, better: "hi",
  },
  // No "shot selection" (sigma) figure: it mostly tracks rally length and a serve-volley
  // artifact. The triggers section covers the same question.
];

// --- the serve, as a two-axis plot -------------------------------------------------------
// Every service point on two axes. Across: first serves in, second serves in, double faults,
// running out from the midline. Up: the share of that column's points won. The shaded area is
// then serve points won, and the ace cores inside it add up to the ace rate:
//
//   area = w1·h1 + w2·h2 = serve points won
//   deep = w1·a1 + w2·a2 = ace rate
//
// The second holds exactly on a match. On a career it is within a few hundredths of a point,
// since aces come from the stats and the split from parsed points (3% don't parse).
//
// The second-serve column is serves that landed, so its rate is over those; the rate over every
// second-serve point is printed separately. Ace cores are clamped to their fill.
function serveSplit(s) {
  if (!s) return null;
  const band = (h, r, a, hn, hd, rn, rd, an) => ({ h, r, a: Math.min(a || 0, r), hn, hd, rn, rd, an });
  const n = num(s.serve_pts);
  // A charted match: the tallies themselves, and the plot is a count of what happened.
  if (n && s.first_in != null && s.first_won != null && s.second_won != null) {
    const fi = Number(s.first_in), fw = Number(s.first_won);
    const df = Number(s.dfs), si = Number(s.second_pts) - df, sw = Number(s.second_won);
    // Older sidecars lack the ace split; the cores then go undrawn.
    const a1 = num(s.aces_first) || 0, a2 = num(s.aces_second) || 0;
    if (fi < 0 || si < 0 || fw > fi || sw > si) return null;
    return {
      n, counts: true,
      bands: [band(fi / n, fi ? fw / fi : 0, fi ? a1 / fi : 0, fi, n, fw, fi, a1),
      band(si / n, si ? sw / si : 0, si ? a2 / si : 0, si, n, sw, si, a2),
      band(df / n, 0, 0, df, n, 0, df, 0)],
      // The scoreboard's second-serve-in rate, printed beside the band.
      second_in: si + df ? si / (si + df) : null,
    };
  }
  // A career: the same three bands from the four shipped rates. The second band's win rate is
  // divided back out, since the shipped rate is over every point that reached a second serve.
  const fi = num(s.first_in_pct), fwp = num(s.first_won_pct);
  const si = num(s.second_in_pct), swp = num(s.second_won_pct);
  if ([fi, fwp, si, swp].some((x) => x == null)) return null;
  // Ace shares are divided back out the same way (build_insights._SERVE_ACE_SQL). Null on older
  // builds.
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

// Column order, out from the midline.
const SVBAND = ["first", "second", "df"];
// What each column is, for the tooltip that carries its counts.
const SVSAY = ["1st serves in", "2nd serves in", "double faults"];
// Width reserved for the gaps between all three columns, drawn or not, so both players share
// one scale.
const SV_GAPS = 4;
// The band height (as a share of the 112px plot) below which a figure moves above its band.
// Set slightly above the measured height so the swap happens early.
const SV_FIG_H = 24 / 112;
const SV_ACE_H = 21 / 112;

// One player's plot, mirrored about the midline (A left, B right) with columns in the same
// order. Distances are measured from the plot's outer edge. at() converts a share plus the gaps
// already passed into a CSS length; gp() counts the gaps outside a column, which depends on
// which columns are drawn.
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

// The pooled ace rate: the two cores added back together.
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
    // The win rate sits at the top of its fill, or above it when the fill is too short. When
    // the ace figure tucks in as a third line (see svAce), the stack always goes above.
    const ace = svAce(x, i, tag, cmp);
    const won = i < 2
      ? `<b class="svwin${x.r < SV_FIG_H || ace.tucked ? " over" : ""}${sup(cmp, `w${i}`, tag)}">${pct(x.r)}<em>won</em>${ace.tucked}</b>` : "";
    return `<span class="svseg ${SVBAND[i]}"
      style="--w:calc((100% - ${SV_GAPS}px) * ${x.h.toFixed(5)});--f:${(x.r * 100).toFixed(2)}%;--ace:${(x.a * 100).toFixed(2)}%"
      title="${esc(say)}"><i class="svfill"></i>${ace.core}${won}${ace.fig}</span>`;
  }).join("");
  // The double-fault figure runs along the outer column; --dfm is its midpoint.
  const df = sp.bands[2];
  const dfLab = `<b class="svdf${sup(cmp, "df", tag)}" style="--dfm:${at(df.h / 2, 0)}"
    >${pct(df.h)}<em>${DF_KEY}</em></b>`;
  // The pooled ace figure hangs below the plot at --acm, the midpoint of the two core centres,
  // with curved tines up to each core. --acsp and --acout set the tines so they clear the in-rate
  // labels. With no second-serve aces only the first tine is drawn.
  const c0 = at(sp.bands[1].h + sp.bands[2].h + sp.bands[0].h / 2, gp(0));
  const c1 = at(sp.bands[2].h + sp.bands[1].h / 2, gp(1));
  const acm = `calc((${c0} + ${c1}) / 2)`;
  const acsp = `calc((${c0} - (${c1})) / 2)`;
  // Just inside the second-serve band's inner edge.
  const acout = sp.bands[1].a
    ? `;--acout:${at(sp.bands[2].h + sp.bands[1].h * 0.95, gp(1))}` : "";
  // The tine curves swap with the side.
  const tine = (cls, d) =>
    `<svg class="svtn ${cls}" viewBox="0 0 12 12" preserveAspectRatio="none" aria-hidden="true"
      ><path d="${d}" vector-effect="non-scaling-stroke"/></svg>`;
  const path = tag === "a"
    ? { in: "M0 12C0 7 12 5 12 0", out: "M12 12C12 7 0 5 0 0" }
    : { in: "M12 12C12 7 0 5 0 0", out: "M0 12C0 7 12 5 12 0" };
  const tines = (sp.bands[0].a ? tine("in", path.in) : "")
    + (sp.bands[1].a ? tine("out", path.out) : "");
  const aceLab = (sp.bands[0].a || sp.bands[1].a)
    ? `<div class="svacetot${sup(cmp, "atot", tag)}" style="--acm:${acm};--acsp:${acsp}${acout}">
        ${tines}<b>${pct(acePooled(sp))}<em><span class="svlong">total </span>ace rate</em></b></div>`
    : "";
  return `<div class="svcol ${tag}">
    <div class="svplot">${cols}</div>
    ${dfLab}${aceLab}
  </div>`;
}

// The ace core inside a fill, and its figure. The figure goes inside the core if it fits, else
// just above it, else as a third line in the win figure (8 of 819 careers).
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

// The two in-rates, centred under their columns.
const SVDIM = [
  { key: '1st<span class="svlong"> serves</span> in', band: 0, dim: "h", cmp: "h0" },
  { key: '2nd<span class="svlong"> serves</span> in', band: 1, dim: "second_in", cmp: "h1" },
];

// --- which of the two is the better figure -------------------------------------------------
// The better of each pair of serve figures is set bold. Fewer is better for double faults. Ties
// and missing sides bold neither.
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
  // --c is the column's centre measured from the outer edge.
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

// The whole serve block. No names or legend: colour and side already say who is who.
function serveAnatomy(da, db, ma, mb) {
  const sa = serveSplit(ma || (da && da.s)), sb = serveSplit(mb || (db && db.s));
  if (!sa && !sb) return "";
  const cmp = serveCmp(sa, sb);
  // Room under the plots for the pooled-ace figure (.svpair.aces).
  const aces = [sa, sb].some((s) => s && (s.bands[0].a || s.bands[1].a)) ? " aces" : "";
  return `<div class="svblock">
    <div class="svpair${aces}">
      ${serveLabels(sa, "a", cmp)}${serveBar(sa, "a", cmp)}${serveBar(sb, "b", cmp)}${serveLabels(sb, "b", cmp)}
    </div>
  </div>`;
}

// Where a figure sits on its tour: p5 to p95 with the middle half shaded, both from the build.
// Players outside it are drawn at the end and marked. `fmt` formats the band ends like the
// figure.
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

// The column's contents as data, shared by the wide columns (profileSide) and the phone
// comparison (profileCompare).
function profileParts(d, md, spread) {
  if (!d && !md) return null;
  const s = (d && d.s) || {};
  const sp = spread || {};
  // Printed for right-handers too, so its absence never needs explaining.
  const hand = s.hand ? `${s.hand === "L" ? "left" : "right"}-handed` : "";
  // Only name the archetype when the clustering is confident. For about a third of players the
  // two nearest fit equally well, and those print "Between styles".
  const arch = s.archetype
    ? (Number(s.style_confident) === 0 ? "Between styles" : s.archetype) : "";
  // Average length of the points the player won, one decimal. On a match it carries the career
  // value as an anchor; the tour strip is career-only.
  const r = md ? md.len_won : num(s.won_rally_len);
  const career = num(s.won_rally_len);
  const rally = r == null ? null
    : {
      v: Number(r).toFixed(1), unit: "shots", raw: Number(r), fmt: (v) => v.toFixed(1),
      band: md ? null : sp.won_rally_len,
      anchor: md && career != null ? career.toFixed(1) : null,
      label: "avg winning rally"
    };
  // Each figure is gated on its own. In match mode a figure the match measures carries the
  // career value as an anchor, and one it can't keeps the career value and is marked.
  const figs = FIGS.map((f) => {
    const career = figOf(f, s);
    const mv = md ? figOf(f, md) : null;
    const v = mv != null ? mv : career;
    if (v == null) return null;
    // No tour band on a match reading; the career anchor gives the scale.
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

// Break points saved, as a count: a player faces about seven a match, so a rate would be noise.
// No `better`, since facing more is about who was under pressure.
function bpFig(md) {
  if (!md || md.bp_faced == null) return null;
  const faced = Number(md.bp_faced), saved = Number(md.bp_saved);
  return {
    v: faced ? `${saved} of ${faced}` : "none faced", raw: faced ? saved / faced : null,
    unit: "", label: "break points saved"
  };
}

// --- the groundstrokes, as a square --------------------------------------------------------
// Every groundstroke on two axes. Across: each wing's share. Up: winner rate; down: unforced
// error rate, each over that wing's strokes. The shaded area is the overall rate. Wings sit
// where the player's hands are (unknown draws as right-handed).
//
// Capped at 20%, a little past the tour's 95th percentile, so the bands are visible.
const GS_CAP = 0.2;
// Past this share of the half, the figure sits on the band instead of beyond it (the half is
// 75px and the figure needs about 16).
const GS_FIG_OVER = 0.78;

// One player's plot, from career rates or the match's own. Null without the two shares.
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

// Bold the better figure per wing: more winners, fewer errors. Shares have no better end.
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

// One wing: a column its share wide, with a solid winner band and a hatched error band.
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
    // On a match, the stroke count under each wing.
    x.n == null ? "" : `<i>${esc(`${x.n} shots`)}</i>`}</span>`).join("")}</p>
  </div>`;
}

// The groundstroke block, laid out like the serve block.
function groundAnatomy(da, db, ma, mb) {
  const ga = gsSplit(da && da.s, ma), gb = gsSplit(db && db.s, mb);
  if (!ga && !gb) return "";
  const cmp = gsCmp(ga, gb);
  // The halves are labelled along the midline.
  return `<div class="gsblock">
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

const EMPTY_PARTS = { arch: "", hand: "", rally: null, figs: [] };

// The rows both columns share, so each figure sits level with its pair and a missing one prints
// an em dash. Career figures come first (style, hand, and variety on a match), then the match's
// own.
function profilePlan(pa, pb) {
  const rows = [];
  const has = (p, l) => p.figs.some((x) => x.label === l);
  const isCareer = (l) => [pa, pb].some((p) => {
    const x = p.figs.find((y) => y.label === l);
    return x && x.careerOnly;
  });
  if (pa.arch || pb.arch) rows.push({ kind: "arch" });
  if (pa.hand || pb.hand) rows.push({ kind: "hand" });
  // FIGS order, then anything else either side has (the break-point count).
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

// One player's column. `o` is the opponent, for bolding the better figure.
function profileSide(p, o, tag, plan) {
  if (!plan.length) return "";
  const oppFigs = new Map(o.figs.map((x) => [x.label, x]));
  const fig = (x, cls) => {
    const trail = x.better && figWinner(x, oppFigs.get(x.label)) === "b" ? ' class="trail"' : "";
    // Anchor and note sit under the figure.
    const note = (x.note ? `<i class="pbanch">${esc(x.note)}</i>` : "")
      + (x.anchor ? `<i class="pbanch">career ${esc(x.anchor)}</i>`
        : x.careerOnly ? `<i class="pbanch">career figure</i>` : "");
    // The tour strip goes under the label.
    return `<p class="${cls}"><b${trail}>${x.v}</b>${x.unit ? `<span>${esc(x.unit)}</span>` : ""}<em>${esc(x.label)}</em>${figBand(x.raw, x.band, x.fmt)}${note}</p>`;
  };
  // A missing figure is a bare em dash; the label is in the other column on the same row.
  const none = (cls) => `<p class="${cls} pbnone"><b>—</b></p>`;
  const cell = (r) => {
    if (r.kind === "arch") return p.arch ? `<p class="pbstyle">${esc(p.arch)}</p>` : none("pbstyle");
    if (r.kind === "hand") return p.hand ? `<p class="pbhand">${esc(p.hand)}</p>` : none("pbhand");
    if (r.kind === "rally") return p.rally ? fig(p.rally, "pbq") : none("pbq");
    const x = p.figs.find((y) => y.label === r.label);
    return x ? fig(x, "pbfig") : none("pbfig");
  };
  return `<div class="pbside ${tag}" data-side="${tag}">${plan.map(cell).join("")}</div>`;
}

// The phone layout: one row per figure, A's value, the label, B's value.
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
  // Same plan as the wide columns, so both layouts list the same rows.
  const seq = plan.filter((r) => r.kind === "rally" || r.kind === "fig")
    .map((r) => (r.kind === "rally" ? (A.rally || B.rally).label : r.label));
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
  // Two siblings, so on a phone the style lines go above the ring and the figures below it.
  return (tops ? `<div class="pbtops">${tops}</div>` : "") +
    `<div class="pbcmp">${rows}</div>`;
}

// The title over the career body. The asterisk points to COV_NOTE at the foot.
const CHARTED_TITLE = `<p class="tapetitle">Charted history<span class="tapestar">*</span></p>`;

// The footnote: charted matches are chosen by volunteers, not sampled at random.
const COV_NOTE = `<p class="covnote">* Charting is volunteer work, so these are the matches
    someone chose to chart. That weights the numbers toward big occasions rather than
    sampling a career evenly.</p>`;

// The collapsed key, defining only the figures on screen. Tour bands are read off the build.
function figureKey(sa, sb, spread, match) {
  const has = (k) => {
    const f = FIGS.find((x) => x.k === k);
    return [sa, sb].some((s) => s && (f ? figOf(f, s) : num(s[k])) != null);
  };
  // The style line is a string, not a figure, so it needs its own test — num() on an
  // archetype name is NaN and `has` would drop the entry that most needs to exist.
  const hasStyle = [sa, sb].some((s) => s && s.archetype);
  // Break points are defined only when on screen.
  const hasBp = [sa, sb].some((s) => s && s.bp_faced != null);
  // Return winners, the one outright-win figure in the column.
  const hasOutright = has("ret_winner_rate");
  const sp = spread || {};
  // One entry covers all four shot-mix figures, shown if any of them is.
  const MIX_KEYS = ["slice_pct", "net_pct", "net_winner_pct", "net_err_pct"];
  const hasMix = MIX_KEYS.some(has);
  // The groundstroke square has no key; its shares gate the error-rate entry.
  const hasGround = [sa, sb].some((s) => s && num(s.fh_share) != null);
  // Tour bands for the figures shown with a strip (career readings only).
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
    // Style leads, and explains "Between styles", which about a third of players get.
    !hasStyle ? "" : `<div><b>Style</b> groups players by twelve measured metrics of their
      charted play, each group named for its centre.
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
    // The strip entry closes the key, after the figures it is drawn under.
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

// "Basic stats": the games-won ring between the two players' style columns (see .tapemain).
// No heading of its own; it follows on from the coverage band.
function tape(da, db, spread, det) {
  // The ring only takes sides above the coverage floor, unless the match itself fills it (see
  // matchSide). An empty half gets a note saying why.
  const ma = matchSide(det, 0), mb = matchSide(det, 1);
  const sa = ma || (wellCharted(da) ? da.s : null);
  const sb = mb || (wellCharted(db) ? db.s : null);
  const cells = sa || sb ? tapeRows().map((r) => donut(r, sa, sb)).join("") : "";
  // Extracted once and shared by both layouts.
  const pA = profileParts(da, ma, spread) || EMPTY_PARTS;
  const pB = profileParts(db, mb, spread) || EMPTY_PARTS;
  const plan = profilePlan(pA, pB);
  const sideA = profileSide(pA, pB, "a", plan), sideB = profileSide(pB, pA, "b", plan);
  if (!cells && !sideA && !sideB) return "";
  const rings = cells ? `<div class="dnstack">${cells}</div>` : "";
  // Name the thin player, so an empty half reads as "not enough charting".
  const thin = det ? [] : [[da, sa], [db, sb]]
    .filter(([d, s]) => d && !s).map(([d]) => last(d.s.player));
  const thinNote = thin.length
    ? `<p class="tapenote">Hold and break rates need ${RATE_MIN_PTS.toLocaleString()}
       charted points to print; ${esc(thin.join(" and "))}
       ${thin.length > 1 ? "are" : "is"} below that.</p>` : "";
  return `<section class="tape">
    <div class="tapemain" style="--pbrows:${plan.length}">${sideA}${rings}${sideB}${profileCompare(pA, pB, plan)}</div>
    ${thinNote}
    ${/* merged with the career rows so the key sees style and variety on a match */""}
    ${figureKey({ ...(da && da.s), ...sa }, { ...(db && db.s), ...sb }, spread, !!det)}
  </section>`;
}

// --- shared-header sections ---------------------------------------------------------
// How many items a column will render, read off its markup.
const countCards = (html) =>
  Math.max(1, (String(html || "").match(/class="(?:pcard2|trig )/g) || []).length);

// One topic, one header, two columns, so the two players stay level. `kind` sets phone-narrow
// behaviour: "cards" stay side by side, "text" stacks. `full` is a drawing on a scale both
// players share, run at full width.
function section(title, note, a, b, aHtml, bHtml, kind = "cards", full = "") {
  if (!aHtml && !bHtml && !full) return "";
  const col = (html, side, tag) => `<div class="seccol" data-side="${tag}">
    <p class="colwho"><span class="tdot ${tag}"></span>${esc(last(side.name) || "TBD")}</p>
    ${html || `<p class="colnone">nothing at this player's coverage</p>`}</div>`;
  // Row count, so the CSS can run both columns on one set of tracks.
  const rows = 1 + Math.max(countCards(aHtml), countCards(bHtml));
  // Only the full-width drawing and no columns: drop the placeholders.
  const cols = aHtml || bHtml
    ? `<div class="seccols" style="--rows:${rows}">${col(aHtml, a, "a")}${col(bHtml, b, "b")}</div>`
    : "";
  return `<section class="msec ${kind}">
    <h3 class="sechead">${title}</h3>
    ${note ? `<p class="secnote">${note}</p>` : ""}
    ${cols}${full}
  </section>`;
}

// Said once per section: how to read n and the win rate on the cards.
const PAYOFF_LEGEND = `<span class="paykey">n is how often they play it, out of how often
  they face the ball; win rates are against their own rate answering that same ball</span>`;

// The court drawing's key. A span, since it sits inside the section's <h3>.
const COURT_LEGEND = `<span class="courtkey">
  <span class="ck in">dashed</span> the ball they get ·
  <span class="ck out">solid</span> their answer ·
  <span class="ck half">tinted half</span> their side of the net</span>`;

// The key to the bar under each cue. `baseline` names the tick, which differs by section.
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

// Link to the chart if it exists, or invite the viewer to chart it. Nothing while a slot is
// still TBD. The arrow is an SVG, like the site's other controls.
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

// The scoreline between the two names, each set's higher score bold. One flat list of cells
// (A,B per set) that CSS lays out as columns on a wide header and rows on a narrow one.
function scoreStack(a, b) {
  const n = Math.max((a.sets || []).length, (b.sets || []).length);
  if (!n) return `<div class="mscore none">vs</div>`;
  // Use the feed's per-set verdict when present, so a live set isn't bolded for its leader.
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

// Full name and a first-initial form; fitHeader() measures and picks one.
function nameHtml(name) {
  const full = esc(name || "TBD");
  const parts = String(name || "").trim().split(/\s+/);
  const abbr = parts.length > 1
    ? esc(`${parts[0][0].toUpperCase()}. ${parts.slice(1).join(" ")}`) : full;
  return `<span class="mname"><span class="mfull">${full}</span>` +
    `<span class="mabbr">${abbr}</span></span>`;
}

// Event and round, in the top corner beside the close button.
function eyebrow(t, round) {
  const event = t.completed ? `${t.season} ${ename(t)}` : ename(t);
  return [esc(event), round ? esc(round.label) : ""].filter(Boolean).join(" · ");
}

// When: a scheduled match's local start time (localStart), the day for an unscheduled one
// (ESPN's detail is "TBD" then), a finished one's date, or the live marker.
function whenLine(m) {
  if (m.state === "in") return `<span class="live">${esc(m.detail || "Live")}</span>`;
  if (m.state !== "post") {
    const scheduled = m.detail && m.detail !== "TBD";
    const d = scheduled ? localStart(m.date, m.detail) : dayLong(m.date);
    return esc(d);
  }
  const day = matchDate(m.date);
  return day ? esc(day) : "";
}

// Scoreboard header: event, then the two players across their score, then when. It stays put,
// so nothing below repeats names or flags.
function headHtml(m, t, round) {
  const decided = !!(m.a.winner || m.b.winner);
  const side = (s, tag) => {
    const emoji = flagEmoji(s.country);
    const flag = `<span class="mflag"${emoji ? ` title="${esc(s.country)}"` : ""}>${emoji}</span>`;
    const seed = s.seed ? `<span class="mseed">${esc(String(s.seed))}</span>` : "";
    const cls = "mp " + tag + (s.winner ? " win" : decided ? " lose" : "");
    // The winner's caret points into their name from the score side.
    return `<div class="${cls}">${flag}${nameHtml(s.name)}${seed}
      ${s.winner ? `<span class="mwin"></span>` : ""}</div>`;
  };
  // Older archived draws carry no per-match date and nothing else to say, so the when
  // line drops out entirely rather than leaving an empty row under the names.
  const when = whenLine(m);
  // A hairline between the staggered rows ties each scoreline to its name. An unplayed match
  // has no scoreline, so both names share a row (.mgrid.noscore).
  const played = (m.a.sets || []).length || (m.b.sets || []).length;
  const rule = played ? `<i class="mrule"></i>` : "";
  // Event and round sit top left, with the when line for a played or live match. An upcoming
  // match's start time goes by the chart button instead.
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

// The charted match's top chart: the win-probability curve (default) or the charted-history
// pyramid, switched by two icons. The choice persists across opens.
let lastMatchView = "wp";

// Icons for the two charts: a curve and a tapering stack.
function matchViewIcon(view) {
  return view === "wp"
    ? `<svg viewBox="0 0 14 14" width="14" height="14" aria-hidden="true"><path
        d="M1 10 L4.5 4.5 L7 8 L10 3 L13 6.5" fill="none" stroke="currentColor"
        stroke-width="1.6" stroke-linejoin="round"/></svg>`
    : `<svg viewBox="0 0 14 14" width="14" height="14" aria-hidden="true"><rect x="3.5"
        y="1.4" width="7" height="2.6"/><rect x="1" y="5.7" width="12" height="2.6"/><rect
        x="4.5" y="10" width="5" height="2.6"/></svg>`;
}

// The charted-match body. Sections that are lifts against the tour (serve + 1, court patterns,
// triggers) are left out, since one match gives only a handful of observations.
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
    // No captions; the icon tooltips name the views.
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

// The top-chart switch: shows one pane and remembers the choice.
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

// The career body, in the order a point runs: coverage, basic stats, serve outcome, serve
// direction (recency-weighted, 10-match half-life), serve + 1, groundstrokes, court patterns,
// triggers, opening cues.
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
// The opener's match id, so focus can go back even after the draw re-renders.
let openerId = null;
let wired = false;
// Each open takes a ticket, so a superseded open drops its late results.
let openSeq = 0;

// Shown when the insights DB fails to load (it's deployed without it when the Release asset is
// missing). Not the "not charted yet" message, which would be wrong here.
const DATA_DOWN = `<p class="nochart">Player charting data isn't loading right now — the
  draw and scores above are unaffected.</p>`;

function lockPage(on) {
  // <html> is the scroller. Padding replaces the hidden scrollbar so the page doesn't shift.
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
  // Scanned, not selected, since match ids come from the feed.
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

// Condense the header to names and score once the body scrolls. Two thresholds, so it doesn't
// flicker.
function onBodyScroll() {
  const panel = document.getElementById("matchup");
  const t = document.getElementById("matchupBody").scrollTop;
  if (t > 24) panel.classList.add("cond");
  else if (t < 8) panel.classList.remove("cond");
}

// Has either name run past `lines` lines? Counted in lines, since a wrapping flex item never
// overflows its width. clientHeight rather than a rect, so the opening scale animation doesn't
// affect it.
function namesOver(grid, lines) {
  for (const n of grid.querySelectorAll(".mname")) {
    const lh = parseFloat(getComputedStyle(n).lineHeight);
    if (lh > 0 && n.clientHeight > lh * (lines + 0.5)) return true;
  }
  return false;
}

// Set the widest gap in [min, max] that keeps every name within `lines` lines, by bisection,
// and say whether one exists. If none does, the gap is reset.
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

// The gap between sets, narrowed first whenever the names don't fit, and kept narrow even if
// that alone doesn't fix it.
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

// Fit the scoreboard by giving things up in order of cost: the gaps between sets, the gap beside
// the score, the first name (to an initial), a second line per name, and last the staggered
// layout. Measured per match rather than set by breakpoint, since five sets and a long name need
// more room than straight sets and a short one. Runs on open and resize.
function fitHeader() {
  const grid = document.querySelector("#matchupHead .mgrid");
  if (!grid) return;
  // Reset first, so the full staggered layout is what gets measured.
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

// Skipped while the panel is closed, since hidden nodes measure as zero.
let fitQueued = false;
function onResize() {
  if (fitQueued || document.getElementById("matchup").hidden) return;
  fitQueued = true;
  requestAnimationFrame(() => { fitQueued = false; fitHeader(); });
}

// On touch devices (no hover), a tap pins a season's readout open; another tap moves or closes
// it.
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
  // Neither slot filled yet (e.g. a TBD final): header only.
  if (!isEntrant(m.a) && !isEntrant(m.b)) {
    body.innerHTML = "";
    return;
  }
  body.innerHTML = `<div id="cardslot" class="loading">Loading…</div>
    ${notationHelp()}`;

  let pa, pb, spread, det;
  try {
    // The sidecar loads alongside the two player queries.
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
    // A charted match doesn't show the sections the notation key explains, so remove it.
    const key = body.querySelector(".notekey:not(.figkey)");
    if (key) key.remove();
    if (slot.querySelector(".wp")) {
      slot._wp = det.wp;
      wireWpChart(slot);
    }
    wireMatchView(slot);
  }
}
