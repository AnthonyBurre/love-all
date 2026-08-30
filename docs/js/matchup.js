// The matchup drawer: experimental pre-match win probability + a card per player,
// all queried from insights.duckdb via DuckDB-WASM.
import { query, serveGates, tourSpread } from "./db.js";
import { patternSvg, pairSvg, retSvg, shotLine } from "./court.js";
import { dayLong } from "./schedule.js";

const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const CHART_GUIDE =
  "https://www.tennisabstract.com/blog/2015/09/23/the-match-charting-project-quick-start-guide/";
const last = (name) => String(name || "").split(" ").slice(-1)[0];
const pct = (x) => (x * 100).toFixed(1) + "%";
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
      "win_rate, tour_win_rate, field_share, state_win_rate, serve_side, serve_dir " +
      "FROM player_patterns WHERE player = ? AND gender = ? ORDER BY evidence DESC",
      [name, gender]);
  } catch (e) { /* stale insights db: show the card without patterns */ }
  let serve = [];
  try {
    serve = await query(
      "SELECT side, wide, t, n_eff, years, career_wide, career_t, reliable, drift_ratio " +
      "FROM player_serve WHERE player = ? AND gender = ? AND reliable = 1",
      [name, gender]);
  } catch (e) { /* stale insights db: show the card without serve direction */ }
  let years = [];
  try {
    years = await query(
      "SELECT year, matches, points FROM player_years WHERE player = ? AND gender = ? " +
      "ORDER BY year", [name, gender]);
  } catch (e) { /* stale insights db: the coverage band prints its counts without the chart */ }
  return { s: s[0], triggers, openings, patterns, serve, years };
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
// sentence states as "3.0× their norm" is also the gap between the tick and the bar's end.
//
// Deliberately the same construction as the comparison strip's winners-and-errors row,
// down to the drained second segment and the haloed reference tick, because it is the same
// measurement: the notation key already tells the reader these are "the same pair of
// numbers the strip up top splits into one bar, read per cue". They should look like it.
// The domain is 0–1 rather than the strip's 0.05–0.32, though: a cue that does anything at
// all pushes the frequency far past the range a player's rally balls average out to, and
// on the strip's scale every one of these would sit clamped at the end of the bar.
function trigMeter(t) {
  const att = Number(t.att_rate);
  if (!isFinite(att)) return "";
  const conv = t.conversion == null ? null : Number(t.conversion);
  const lift = Number(t.att_lift);
  const norm = isFinite(lift) && lift > 0 ? att / lift : null;
  const segs = conv == null ? `<span style="flex:1"></span>`
    : `<span style="flex:${conv}"></span><span class="miss" style="flex:${1 - conv}"></span>`;
  const tick = norm == null ? "" : `<u style="left:${(norm * 100).toFixed(1)}%"></u>`;
  return `<div class="tmeter"><i style="width:${(att * 100).toFixed(1)}%">${segs}</i>${tick}</div>`;
}

// `hand` is the player's, and every row here needs it: both trigger families store their
// contexts in the player's own frame, mirrored for a left-hander so that one cue string
// means one piece of tennis whoever plays it. The drawing is the one place that wants the
// real court back, so it mirrors again on the way out.
function trigLine(t, hand) {
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
    ${trigMeter(t)}
    ${rallyDrawer(t.context, hand === "L")}</div>`;
}

// Where they aim the first serve. Only wide and T are printed: the body share is
// partly a charter's opinion (charters disagree about it by ±4-6 points on the same
// players), so the two shown do not add to 100 and the remainder is deliberately
// unnamed. Rows appear per court side only where the player has enough charted serves
// for the share to be mostly signal — the `reliable` flag the experiment ships, which
// is already applied in the query, so a thinly-charted player shows nothing here
// rather than a number that is really sampling noise.
function serveHtml(d, gates) {
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
  const win = gates.recent_matches ? Math.round(gates.recent_matches) : null;
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
  const court = p.family === "ret"
    ? retSvg(p.serve_side, p.serve_dir, p.inc_code, p.resp_code, p.state_depth)
    : pairSvg(p.inc_code, p.resp_code, p.state_depth);
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
      ${/* This *is* the tick below, exactly: trigMeter draws it at att_rate / att_lift, and
           att_lift is the cue's rate over this same pooled figure, so the division returns
           it unchanged. */""}
      <span class="lift">the tick on each cue below marks this rate</span></p>
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
  return base + [...greens, ...traps].map((t) => trigLine(t, hand)).join("") + immune;
}

// --- "side by side": one ring per metric ----------------------------------------------
// One shared axis, bent into a circle. 12 o'clock is the
// bottom of the drawing domain for both of them, A sweeps counter-clockwise and B clockwise,
// and a half-turn each is the top of it. So they still grow from a shared origin and the
// comparison is still "whose reaches further" — read as a sweep rather than as a length, and
// with the unreached range left as open track at the foot of the ring.
//
// Two rings, not two concentric ones. On a stack of concentric rings the same value
// draws a longer arc on an outer ring than on an inner one, because arc length is radius ×
// angle — so the outermost metric always looks like the biggest number, whatever it says.
// Same radius every time, and the reader is comparing the one thing that is being encoded.
//
// The numbers still carry the exact values, in the hole. That matters more here than it did
// on the bars: a sweep is read less precisely than a length, so the picture is for the
// comparison and the digits are for the value, and neither is asked to do the other's job.
//
// Every ring runs from zero. `hi` is the far end of the half-turn and `scale` is that end
// written out under the metric's name, so the sweep is proportional to the figure beside it:
// twice the arc is twice the number, and a fifth of the ring is a fifth of the ceiling.
//
// Not a zoomed window per metric. A closed loop reads as a whole, so "how full" reads as a
// share of it, and identical circles side by side invite exactly the comparison a zoomed
// window cannot support: on a 50–80% window for serve points and 5–32% for rally strokes,
// 66.5% and 19.8% draw the same 99° arc.
//
// Zeroing them costs resolution, and that is paid for elsewhere. 66.5% against 68.1% is under
// three degrees, which nobody can see, so the figures either side of the ring carry that
// comparison and the leader is the one set in ink.
//
// Which is also why only two metrics are left on rings. A ring that runs from a real zero to
// a ceiling anyone could reach says something about both players at a glance; one where every
// player on tour lands inside a narrow band near the foot, or near the middle, spends a whole
// circle to draw two arcs of the same length. Winners-and-errors was the first kind of
// failure — a fifth of a ring, for everyone — and it has gone down to the shot-making
// triggers, where the same number is the reference every cue is measured against. Shot
// quality was the second (the charted tour runs 49 to 73 out of 100), and variety and shot
// selection the third, and all three now read against the tour's own spread instead.
//
// The zero is real in both that are left: no aces, and no return point ever won. The ceiling
// is not always the metric's own full — return points won has a full nobody comes within
// half of — so `hi` is per ring and `top` prints it over the arc.
//
// `mark` puts a second figure of the player's own on the ring, as a tick across the band at
// the point on the same scale it reaches. It is the game-level reading of the arc: how often
// the serve ring's points-won actually became a hold, how often the return ring's became a
// break. Same axis, different denominator, which is exactly the thing worth showing — the
// arcs sit in a narrow band because points are close, and the ticks do not, because games
// are not. A serve advantage of three points in a hundred is twenty games in a hundred.
//
// It reads in both directions from the same mechanism, which is why one mark does for both
// rings. Above half in points lands further above in games, so the serve ring's tick sits
// out past the end of its arc, in open track; below half lands further below, so the return
// ring's sits back inside its arc. The gap between arc and tick is the conversion either way.
//
// Not the charted tour average, which is the one shared spoke this replaces. That answers a
// question the two figures either side of the ring already answer between them — these players
// are close, and here is the tour they are close around — and it answers it in the one place
// on the drawing that could carry a number about the players instead.
//
// The mark is per player and per ring, so it is a function of that player's row rather than
// a scalar on the row spec. `better` says which direction wins.
const clamp01 = (x) => Math.max(0, Math.min(1, x));
const num = (v) => (v == null ? null : Number(v));

// The coverage floor the serve and return rates have to clear before this panel will print
// them, in charted points — the same 2,000 the win probability's confidence bands already
// used as their lower edge, now enforced rather than described.
//
// It was the one number here with no gate at all, which had it backwards: variety is withheld
// below 800 charted strokes, the serve mix below ~862 effective serves, ace rate below 200
// service points, and the two figures a reader looks at first were printed off a single match.
// A one-match entrant was reading 70.9% of serve points won — near the best server in the
// table — from 173 points, and the rings say nothing about how many points are behind them.
//
// 2,000 points is roughly a dozen charted matches. It is a floor on obvious nonsense rather
// than a claim that everything above it is precise: these rates are career-long and never
// adjusted for the opponents a volunteer chose to chart, so the number above the floor is
// still a charted rate and not a true one.
//
// The floor is also what makes shrinkage unnecessary. Pulling the rates toward the tour mean
// would bias a displayed measurement toward a prior the reader cannot see, and the thin
// players it would protect are already excluded, so the rings show each player's own charted
// rate.
const RATE_MIN_PTS = 2000;
const wellCharted = (d) => !!d && (Number(d.s.points_charted) || 0) >= RATE_MIN_PTS;

// The two free points, printed as a pair under the total. An ace is a service point won
// without playing it and a double fault is one given away the same way, they are measured
// over the same denominator — every service point the player served — and they are the two
// ends of the same decision about how hard to hit a serve. Read together they say what a
// player's serve costs as well as what it earns: 14.6% aces against 2.3% double faults is a
// different serve from 10.6% against 5.0%, and the ring alone cannot tell those apart.
//
// Double faults are text and not an angle, where aces get both. On the ring's half-turn a
// double-fault rate is 3.6° at the tour's 5th percentile and 10.1° at its 95th, and the
// whole middle half of the men's tour fits inside 2.9° — under the three degrees this
// panel already treats as invisible. Drawn as a wedge down from the 100% mark it would
// have been a 6px nick in a 17px band, in grey, on the grey of the unreached track. The
// figure is the part of it that carries information, so the figure is the part that ships.
// Returned as the two figures rather than as one string. Each gets its own line in the flank,
// which is what keeps a figure with its own unit: run together on one line and left to wrap,
// they broke wherever the gutter ran out — "9.6% aces · 1.9%" on one line and "double faults"
// on the next, and differently on the two sides of the ring, since the wider player's figures
// ran out sooner. Two lines is what the pair costs at this track width anyway.
// The part of a sweep the player never had to play out, as the arc's own deepened core:
// aces inside serve points won, return winners inside return points won. Both are subsets of
// the arc they sit in, so the split is over *points won* — the share of this sweep — while the
// figure in the flank is over every point of that kind, which is how each is normally quoted.
// Two different denominators, which is why only one of them is printed: the ring carries the
// other as an angle, where it does not have to be read as a figure.
//
// The return core is small and often smaller than the eye resolves — the modern men's game
// puts it near three degrees, against fourteen for a typical ace wedge — and it is drawn
// anyway. It is a true share of a true arc at whatever size it comes to, the women's tour
// spends up to fifteen degrees of ring on it, and a mark that appears only for the players it
// is large for is still telling the truth about the ones it is small for.
//
// Null where the rate is (a thinly-charted server, a returner under the build's return-point
// floor), and the arc is then simply one colour.
const outright = (part, whole) => (s) => {
  if (s[part] == null) return null;
  const f = clamp01(Number(s[part]) / Number(s[whole]));
  return [{ f, cls: "deep" }, { f: 1 - f }];
};

function tapeRows() {
  return [
    // The sweep is how often they win a service point; where it changes colour is how much of
    // that they never had to play for — see outright() above.
    {
      k: "serve_rate", label: "serve points won", short: ["serves", "won"],
      hi: 1, top: "100", better: "hi", fmt: pct, unit: "points",
      mark: { k: "hold_rate", label: "games" },
      wedge: { k: "ace_rate", label: "aces" }
    },
    // Ceilinged at 0–67% rather than 0–100%. Returning is the half of tennis nobody wins
    // outright — the best charted return games on either tour reach 46% (men) and 52%
    // (women) — so a full 100% would spend two thirds of the climb on ground no player has
    // ever stood on. The cost is that these arcs are not the same scale as the rings either
    // side: 41.1% here climbs about as far as 66.5% does on serve points. That is what the
    // scale under the name is for, and why the note below stops short of saying arcs compare
    // between rings.
    {
      k: "return_rate", label: "return points won", short: ["returns", "won"],
      hi: 0.67, top: "67", better: "hi", fmt: pct, unit: "points",
      mark: { k: "break_rate", label: "games" },
      wedge: { k: "ret_winner_rate", label: "return winners" }
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

// One player's sweep, as dashes on a full circle rather than as arc paths. A circle's own
// path starts at 3 o'clock and runs clockwise, so one group transform — a quarter turn to
// bring that start down to 6 o'clock, plus a mirror for the player climbing the other side —
// points it the right way. Every segment after that is an offset and a length along that
// path, which means no arc flags and no large-arc special case at exactly half a turn.
function dnArc(deg, segs, side) {
  if (!(deg > 0)) return "";
  const spin = side === "b"
    ? `translate(${DN_C * 2},0) scale(-1,1) rotate(90 ${DN_C} ${DN_C})`
    : `rotate(90 ${DN_C} ${DN_C})`;
  let at = 0;
  const parts = segs.map((g) => {
    const seg = DN_LEN * (deg * g.f) / 360, off = DN_LEN * at / 360;
    at += deg * g.f;
    return `<circle class="dseg ${side} ${g.cls || ""}" cx="${DN_C}" cy="${DN_C}" r="${DN_R}"
      stroke-dasharray="${seg.toFixed(2)} ${DN_LEN.toFixed(2)}"
      stroke-dashoffset="${(-off).toFixed(2)}"/>`;
  }).join("");
  return `<g transform="${spin}">${parts}</g>`;
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

// The player's own games figure, laid across the band where it falls on the ring's scale —
// see the `mark` note above. Two spokes on the same line, the wider dark one under the
// narrower light one, which is the strip's haloed tick drawn in SVG. It stands on both of the
// ring's grounds — inside the arc on the return ring, out on open track past the arc's end on
// the serve ring — and it is the halo that carries it across them: on a violet or red arc the
// white core does the work, and on the pale track the ink halo does.
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
// Every figure is set beside the mark it is read off. The points total sits where its arc
// stops, the games figure beside the tick, and the outright-win figure at the foot beside
// its wedge — so the number and the thing it measures are one object, and no part of the
// drawing has to be matched back to a column of small print by colour or by side.
//
// The three could not go in one column and stay tied to the ring: they are three different
// places on it, and a stacked list puts them in reading order rather than in the order the
// ring makes. Around the ring they land in the order they happen — outright wins at the foot,
// then points, then games above them — which is also the order they nest in.
//
// `left`/`top` are percentages of a box that is exactly the drawing's size, so they resolve
// against the same square the viewBox does and hold at every ring size. Anchored on a circle
// just outside the band, then pushed clear of it by the transform: side A's labels end at
// their anchor and reach left, side B's start at theirs and reach right, which is the half of
// the ring each player's arc climbs. That is also what keeps the two players' labels apart at
// the foot, where their anchors are closest.
const DN_LR = 45;

// The outright-win figures are the exception to the anchoring above: they sit in a row of
// their own directly under the ring, split either side of its centre line, rather than on
// the circle with the other two.
//
// Anchored on the circle at the middle of their own wedge, they collided — with each other
// whenever both wedges were small, which on the modern men's return ring is every time, and
// then with the games figure once they were pushed far enough round to clear that. Checked
// across all 363 players the rings print for, the second collision hits 120 of them: a break
// rate lands the games figure low on the ring, which is exactly where a wedge label pushed
// off the foot has to go.
//
// A row under the ring is the placement with no data in it, so nothing can drive it into
// anything else. It still points at the wedges — they are at the foot, and this is directly
// below the foot — and it still says which player's it is, by which side of the centre line
// it falls on, the same rule the other four follow.
// The leader joining an outright-win figure to the wedge it counts. The figures sit in a row
// under the ring, where nothing in the data can push them into anything else; the leader is
// what buys that placement back — without it the row is two numbers parked below a drawing,
// and the wedge they belong to is a colour change a reader has to find.
//
// Three runs, two kinks. A short radial stub straight out of the band at the middle of the
// wedge, then a diagonal outward and down to the row the figures sit on, then a flat run along
// that row into the figure. The stub leaves the band the way a spoke would, so the leader
// reads as attached to the wedge rather than dropped past it; the diagonal is the reach, and
// the flat run is what hands the line off to the text horizontally.
//
// Every run travels outward, away from the ring's centre line. That is a property of the data
// rather than a case handled: the widest wedge on either ring is a 22% ace rate, whose middle
// sits near x=35, and the row's inner end is at 32 — so every leader leaves the band inside
// its own figure and reaches out to it. The flat run is trimmed toward zero where a wide wedge
// starts the leader that close to the figure's edge, which keeps the diagonal from doubling
// back.
const DN_LEAD_R = 43;      // where a leader leaves the band, just clear of its outer edge at 41
const DN_LEAD_STUB = 2.5;  // how far the radial stub reaches before the leader turns outward
const DN_LEAD_Y = 104;     // the row the leaders flatten onto — and the row the figures sit on
const DN_LEAD_FLAT = 4;    // the flat run into the figure, after the diagonal
const DN_LEAD_X = 32;      // where that run ends, before the figure's own edge at 30

function dnLead(deg, side) {
  const a = dnAt(deg, side);
  const [x0, y0] = dnPoint(a, DN_LEAD_R);
  const [x1, y1] = dnPoint(a, DN_LEAD_R + DN_LEAD_STUB);
  const end = side === "a" ? DN_LEAD_X : 100 - DN_LEAD_X;
  const flat = Math.max(0, Math.min(DN_LEAD_FLAT,
    side === "a" ? x1 - end - 0.5 : end - x1 - 0.5));
  const knee = side === "a" ? end + flat : end - flat;
  return `<path class="dlead" d="M${x0.toFixed(2)},${y0.toFixed(2)}` +
    ` L${x1.toFixed(2)},${y1.toFixed(2)} L${knee.toFixed(2)},${DN_LEAD_Y}` +
    ` L${end},${DN_LEAD_Y}"/>`;
}

function dnLabel(x, y, side, cls, html) {
  return `<span class="dlab ${side} ${cls}"
    style="left:${x.toFixed(2)}%;top:${y.toFixed(2)}%">${html}</span>`;
}

// The clear space the points and games figures need between them, in viewBox units, when the
// two values they sit at are close enough on the ring to put them on the same line of type.
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
// It bites for 27 of the 363 players the rings print for — all on the serve ring, all of them
// players whose hold rate is barely above their serve-points rate, which is a real thing about
// how they serve and not a fault in the drawing. Where it applies the two labels move apart
// around their own midpoint, so neither ends up further than half the shortfall from its own
// mark: at most 5 units, under a tenth of the ring's width, with the tick glyph and the arc's
// own end still directly beside them.
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
  // metric has no better end. Used for the points total and, the same way, for the games
  // figure across the band: winning more games is better whichever the sweep direction, so
  // the mark rides `r.better` too.
  const leadOf = (xa, xb) => r.better && xa != null && xb != null && xa !== xb
    ? ((xa > xb) === (r.better === "hi") ? "a" : "b") : "";
  const lead = leadOf(va, vb);
  const at = (v) => clamp01(v / r.hi) * 180;
  // The three figures, read out of the player's row once each and used by both the drawing
  // and the label beside it — the tick and its number, the wedge and its number, are the same
  // value twice and come from the same lookup.
  const markOf = (s) => (!r.mark || !s ? null : num(s[r.mark.k]));
  const wedgeOf = (s) => (!r.wedge || !s ? null : num(s[r.wedge.k]));
  const markLead = leadOf(markOf(sa), markOf(sb));
  // An arc is one colour unless the player has an outright-win rate to split it with; then
  // the segments are shares of that player's own sweep, laid from the foot up, so both
  // players' cores start at the shared origin and stay directly comparable.
  const arc = (v, s, side) => v == null ? ""
    : dnArc(at(v), (r.wedge && s ? outright(r.wedge.k, r.k)(s) : null) || [{ f: 1 }], side);

  // One player's labels. A side with no rate gets a single em dash where its arc would have
  // left the foot: the half is empty on purpose, and an empty half beside a full one should
  // say so on the drawing rather than only in the note under it.
  // The middle of a player's wedge, in degrees of sweep from the foot — where its leader
  // leaves the band. Null where there is no wedge to point at.
  const wedgeMid = (v, s) => {
    const w = wedgeOf(s);
    return v == null || w == null ? null : at(v) * clamp01(w / v) / 2;
  };
  const anchor = (deg, side) => {
    const [x, y] = dnPoint(dnAt(deg, side), DN_LR);
    return { x, y };
  };
  const labels = (v, s, side) => {
    if (v == null) return `<span class="dlab ${side} dwdg dnone">—</span>`;
    const m = markOf(s), w = wedgeOf(s);
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
    const pts = side === "a" ? `${unit}${r.fmt(v)}` : `${r.fmt(v)}${unit}`;
    const out = [dnLabel(pa.x, pa.y, side, `dpts${lead === side ? " lead" : ""}`, pts)];
    if (ga) {
      // No key glyph. The figure is set against the tick it names, close enough that a
      // second copy of the mark beside the number was labelling the label. Bolded on the side
      // that holds or breaks more, the same lead mark the points total carries.
      out.push(dnLabel(ga.x, ga.y, side, `dgms${markLead === side ? " lead" : ""}`,
        flank(r.mark.label, pct(m))));
    }
    // Placed by the stylesheet rather than by angle, and joined to its wedge by a leader
    // drawn on the ring — see dnLead().
    if (w != null) {
      out.push(`<span class="dlab ${side} dwdg">${flank(r.wedge.label, pct(w))}</span>`);
    }
    return out.join("");
  };

  // "no data" only in the label a screen reader hears — set on the drawing it would be a
  // sentence where every other mark is a figure, which is what the em dash is for.
  const say = (v) => (v == null ? "no data" : r.fmt(v));
  // The ring's name, shrunk and shortened to sit in its own hole rather than over the row —
  // the one place beside the arc itself a reader is already looking.
  const title = r.short
    ? `<p class="dnttl">${r.short.map(esc).join("<br>")}</p>` : "";
  // The two ends of the scale, at the two ends of the ring, inside the hole. Every other
  // figure now sits outside the band against its own mark, so the hole holds only the two
  // that belong to the ring rather than to either player.
  return dnCell(`<div class="dnring">
      <svg viewBox="0 0 100 100" xmlns="http://www.w3.org/2000/svg" role="img"
        aria-label="${esc(`${r.label} — ${say(va)} against ${say(vb)}`)}">
        <circle class="dtrack" cx="${DN_C}" cy="${DN_C}" r="${DN_R}"/>
        ${arc(va, sa, "a")}${arc(vb, sb, "b")}${dnOrigin()}${dnEnds()}
        ${/* one per side, and only where that side has a sweep to read it against — a lone
             tick on an empty half marks a conversion of nothing */""}
        ${va == null || markOf(sa) == null ? "" : dnTick(dnAt(at(markOf(sa)), "a"))}
        ${vb == null || markOf(sb) == null ? "" : dnTick(dnAt(at(markOf(sb)), "b"))}
        ${wedgeMid(va, sa) == null ? "" : dnLead(wedgeMid(va, sa), "a")}
        ${wedgeMid(vb, sb) == null ? "" : dnLead(wedgeMid(vb, sb), "b")}
      </svg>
      <span class="dncap top">${esc(r.top)}</span>
      ${title}
      <span class="dncap zero">0</span>
      ${labels(va, sa, "a")}${labels(vb, sb, "b")}
    </div>`);
}

// How much of each player the charting actually has, under the title that names what these
// counts are — matches, points, and the span of years they were charted across. An uncharted
// player is the site's whole invitation, so the ask sits here too rather than only in the
// empty columns below it.
//
// No name and no flag: the scroll-locked match header above carries those, and this side of
// the panel is the same player in the same position. The player colours (--a / --b) are
// declared by the split rule under that header, its left half player A and its right half
// player B; the rule across the top of each half here is the same colour, and it is the same
// mark that caps each column further down.
// --- the charted-history chart -------------------------------------------------------------
// "2015–2024: 61 matches" is a span and a total, and a span and a total cannot tell those two
// apart: sixty matches in one breakout season, or six a year for ten. They read the same on the
// line and they are not the same denominator — the first is a snapshot of one year's form
// wearing a decade's date range, and every pattern, trigger and rate in the panel below is
// drawn from it. So the counts get a shape as well as a sum: one bar per season, its height the
// points charted in it.
//
// Points rather than matches, because points are what the rest of the panel is actually built
// out of — a trigger needs strokes, not fixtures — and a three-setter and a five-setter are one
// match each. The match count is the number people say out loud, so it rides in each bar's
// tooltip rather than being lost.
//
// Both players are drawn on one domain and one height scale, set across the pair. Two charts
// each fitted to their own data would put a lightly-charted player's best season at the same
// height as a heavily-charted one's, in a band whose whole subject is that the two are not
// equally known — and the bars sit at equal x positions in two equal-width columns, so a season
// lines up with the same season across the gap.
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

// One player's bars across the shared domain. A season with no charted match is an empty slot
// rather than a missing one: the columns only line up if every year holds a place, and the gap
// itself is the finding on a player the charting picked up late or dropped.
//
// Height is a percentage of the row, floored in CSS rather than here (see .cy) so the floor is
// a pixel count and not a share of whatever height the row happens to be. Without it a season
// of one charted match against a peak of nine thousand points draws two thirds of a pixel, and
// "barely charted" and "not charted at all" become the same mark — which is the one distinction
// this chart exists to make.
function coverageChart(rows, sc) {
  if (!sc || !rows || !rows.length) return "";
  const by = new Map(rows.map((r) => [Number(r.year), r]));
  const bars = [];
  let peak = null;
  for (let y = sc.lo; y <= sc.hi; y++) {
    const r = by.get(y);
    if (!r) { bars.push(`<i class="cy none"></i>`); continue; }
    const pts = Number(r.points) || 0, mt = Number(r.matches) || 0;
    if (!peak || pts > peak.pts) peak = { y, pts, mt };
    const label = `${y} — ${mt} ${mt === 1 ? "match" : "matches"} · ${pts.toLocaleString()} points`;
    // `title` is a mouse affordance and this layout is read on a phone, where hover does not
    // exist and the season labels were simply unreachable. `data-lbl` carries the same string
    // to a CSS readout that opens on press as well as on hover (see .cy[data-lbl]), so a
    // thumb can get at it. The bars stay out of the tab order deliberately — a thirty-season
    // career would otherwise put thirty stops inside a modal, twice over.
    bars.push(`<i class="cy" style="height:${(pts / sc.max * 100).toFixed(1)}%"
      title="${esc(label)}" data-lbl="${esc(label)}"></i>`);
  }
  // One label per end of the axis, and only those two. A tick per season is unreadable at this
  // size, and the years in between are recoverable by counting along from either end — which is
  // what the per-bar tooltip is for when a reader wants an exact one.
  const say = `charted points by season, ${sc.lo} to ${sc.hi}` +
    (peak ? `; busiest ${peak.y}, ${peak.mt} ${peak.mt === 1 ? "match" : "matches"}` : "");
  return `<div class="cchart">
    <div class="cbars" role="img" aria-label="${esc(say)}">${bars.join("")}</div>
    <p class="cyears"><span>${sc.lo}</span><span>${sc.hi}</span></p>
  </div>`;
}

function coverageSide(d, tag, sc) {
  if (!d) {
    return `<div class="pbside ${tag}" data-side="${tag}">
      <p class="pbnone">not charted yet —
        <a href="${CHART_GUIDE}" target="_blank" rel="noopener">chart a match →</a></p></div>`;
  }
  const s = d.s;
  const chart = coverageChart(d.years, sc);
  // The span goes wherever it is actually being carried, and never in both places at once.
  // With the chart drawn, the years belong to it — it has an axis, and the axis is labelled at
  // both ends. Printed here as well, they were a second date range forty pixels above a
  // different one (the axis spans *both* players, so a player charted from 2014 sits under a
  // "2013"), and two ranges that near each other read as a contradiction rather than as two
  // facts. Without a chart — a stale database with no player_years table — this line is the
  // only thing that can say when, so it says it.
  const span = s.year_min == null || chart ? "" : (s.year_min === s.year_max
    ? `${s.year_min}: ` : `${s.year_min}–${s.year_max}: `);
  // These counts are how much of the player exists in the data, not how much tennis they have
  // played — which is what the title above them and the note at the foot of the panel are for.
  //
  // Singular where it is one. This line is at its most conspicuous on exactly the players it
  // reads worst for: a qualifier with a single charted match got "1 matches" at the top of a
  // panel whose entire subject is how little is known about them.
  const mt = Number(s.matches_charted) || 0;
  return `<div class="pbside ${tag}" data-side="${tag}">
    <p class="pbchart">${span}${mt} ${mt === 1 ? "match" : "matches"} ·
      ${Number(s.points_charted).toLocaleString()} points</p>
    ${chart}</div>`;
}

function profileBand(da, db) {
  if (!da && !db) return "";
  // The scale is computed once, over both players, and handed down — so neither column can
  // quietly draw itself against a different axis than its neighbour.
  const sc = yearScale(da && da.years, db && db.years);
  return `<div class="pband">
    ${coverageSide(da, "a", sc)}${coverageSide(db, "b", sc)}</div>`;
}

// Variety, as the figure it is. It had a section and a scatter of its own; it now prints here,
// under shot quality, because that is what it is — a per-player fact belonging with the player,
// in the band that already holds the other one.
//
// Bits are not a scale a reader arrives knowing. What the scatter did about that was draw the
// rest of the tour behind the figure; what takes its place is the band the middle half of the
// tour occupies, quoted once in the definitions the section can open (see figureKey) rather
// than restated beside the figure.
//
// Kept as a list because everything downstream wants the same things — the key, how to print
// it, what to call it — and a second copy of "times 100, one decimal" in the definitions is
// the copy that drifts.
// How the serve behaves before anyone plays a point off it, and the reason this list is not
// only "figures with an exotic unit". None of the three is a share of any arc the rings draw —
// they draw points won, and these are about where the ball landed — so on a ring each could
// only ever be a figure parked beside a drawing it was not part of. Here they are what they
// actually are: facts about how this player serves, beside how long their points run and how
// far their shot choices stray.
//
// The three are one measurement told in full. A serve either goes in or it doesn't; the first
// rate is how often the first one lands, the second is how often the one after a miss lands,
// and a double fault is the case where neither did. Which is why the third is derived rather
// than read: it is exactly (1 - second in) x (1 - first in), so a shipped copy of it would be
// the same fact twice, free to disagree with the pair it came from. It is still printed —
// nobody should have to multiply two percentages to find out how often a player serves the
// point away — but there is one number behind it, not two.
//
// A figure's value for one player. Most are a column on the row; one is computed from two of
// them, and every reader of FIGS goes through here so the derived one is never the case that
// got missed.
const figOf = (f, s) => (!s ? null : (f.get ? f.get(s) : num(s[f.k])));

const dfOf = (s) => {
  const f = num(s.first_in_pct), sec = num(s.second_in_pct);
  return f == null || sec == null ? null : (1 - sec) * (1 - f);
};

// `better` marks the figures with a right side — a serve that lands is better than one that
// doesn't, a double fault is worse — so the phone comparison can set the winner in ink and let
// the other go quiet. Variety and rally length have no better end and stay level.
const FIGS = [
  {
    k: "bits", label: "variety", unit: "bits",
    fmt: (v) => v.toFixed(1), say: (v) => `${v.toFixed(1)} bits`,
  },
  {
    k: "first_in_pct", label: "1st serves in", unit: "", better: "hi",
    fmt: (v) => pct(v), say: (v) => pct(v),
  },
  {
    k: "second_in_pct", label: "2nd serves in", unit: "", better: "hi",
    fmt: (v) => pct(v), say: (v) => pct(v),
  },
  {
    k: "df_rate", label: "double faults", unit: "", get: dfOf, better: "lo",
    fmt: (v) => pct(v), say: (v) => pct(v),
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
function profileParts(d) {
  if (!d) return null;
  const s = d.s;
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
  // Strokes in the whole point, both players and the serve, averaged over the points this
  // player appeared in — so it is as much a fact about who they play as about them, which is
  // what the key says. One decimal: the tour's middle half spans about 0.8 of a stroke, and
  // whole numbers would collapse most of the field onto "5".
  //
  // Labelled "avg point length" rather than "avg rally": the figure counts the serve and the
  // return like every other stroke, and "rally" invites the reader to assume those are left
  // out. The unit says "shots", so the label only has to say what is averaged.
  const r = num(s.avg_rally_len);
  const rally = r == null ? null
    : { v: r.toFixed(1), unit: "shots", label: "avg point length" };
  // Independently gated. The figures come from different experiments with different
  // qualification thresholds, so a player can easily have one and not the other; a figure
  // held back because its neighbour is missing is a fact withheld for no reason.
  const figs = FIGS.map((f) => {
    const v = figOf(f, s);
    return v == null ? null
      : { v: f.fmt(v), raw: v, unit: f.unit, label: f.label, better: f.better };
  }).filter(Boolean);
  return { arch, hand, rally, figs };
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
function profileSide(d, opp, tag) {
  const p = profileParts(d);
  if (!p || (!p.arch && !p.hand && !p.rally && !p.figs.length)) return "";
  const oppFigs = new Map(((profileParts(opp) || { figs: [] }).figs).map((x) => [x.label, x]));
  const fig = (x, cls) => {
    const trail = x.better && figWinner(x, oppFigs.get(x.label)) === "b" ? ' class="trail"' : "";
    return `<p class="${cls}"><b${trail}>${x.v}</b>${x.unit ? `<span>${esc(x.unit)}</span>` : ""}<em>${esc(x.label)}</em></p>`;
  };
  return `<div class="pbside ${tag}" data-side="${tag}">
    ${p.arch ? `<p class="pbstyle">${esc(p.arch)}</p>` : ""}
    ${p.hand ? `<p class="pbhand">${esc(p.hand)}</p>` : ""}
    ${p.rally ? fig(p.rally, "pbq") : ""}${p.figs.map((x) => fig(x, "pbfig")).join("")}
  </div>`;
}

// The same figures for a phone, where the two flanking columns are a ~150px pair and every
// label prints twice. One grid row per figure — A's value, the label once, B's value — so the
// two numbers sit across a centre line and read against each other directly. Renders whenever
// either side has anything, filling the other side with an em dash; the flanking columns take
// the wide layout, where the rings run between them and each figure sits by its own mark.
function profileCompare(da, db) {
  const raw = (d) => profileParts(d) || { arch: "", hand: "", rally: null, figs: [] };
  const A = raw(da), B = raw(db);
  const any = (p) => p.arch || p.hand || p.rally || p.figs.length;
  if (!any(A) && !any(B)) return "";
  const map = (p) => {
    const m = new Map();
    if (p.rally) m.set(p.rally.label, p.rally);
    for (const x of p.figs) m.set(x.label, x);
    return m;
  };
  const ma = map(A), mb = map(B);
  const seq = [];
  if (A.rally || B.rally) seq.push((A.rally || B.rally).label);
  for (const f of FIGS) if (ma.has(f.label) || mb.has(f.label)) seq.push(f.label);
  const val = (x) => x == null ? "—"
    : `${x.v}${x.unit ? ` <span class="pbcu">${esc(x.unit)}</span>` : ""}`;
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
  return `<div class="pbcmp">${head(A.arch, B.arch, "arch")}` +
    `${head(A.hand, B.hand, "hand")}${rows}</div>`;
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
// Two rings, where there were six. Of the four that left, variety is a figure in the two style
// columns here and winners-and-errors is the first bar in each player's column under
// shot-making triggers, which is where the numbers it should be held against already were;
// shot selection and shot quality have since been cut outright rather than moved.
//
// The rings stack rather than sit side by side, and the two style columns flank the stack
// instead of sitting in a row above it, wide enough allowing: three tracks (style, rings,
// style) instead of the two rows a narrower panel needs. Centred on that row, the stack lands
// in the gap a style column already has between its own archetype line and its shot-quality
// figure — so on a wide panel the rings read as filling that gap rather than as a block
// dropped in below it. See .tapemain in the stylesheet for the two grid-template-areas this
// switches between.
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
function figureKey(sa, sb, spread) {
  const has = (k) => {
    const f = FIGS.find((x) => x.k === k);
    return [sa, sb].some((s) => s && (f ? figOf(f, s) : num(s[k])) != null);
  };
  // The style line is a string, not a figure, so it needs its own test — num() on an
  // archetype name is NaN and `has` would drop the entry that most needs to exist.
  const hasStyle = [sa, sb].some((s) => s && s.archetype);

  const defs = [
    // The style line leads the key because it leads the column, and because it is the one
    // item here that sometimes declines to answer. A reader who meets "Between styles" with
    // no explanation has to guess whether it means missing data, a hedge, or a finding — it
    // is the third, and saying so is the whole point of this entry. It is also the panel's
    // most common non-answer: about a third of the players who qualify get it.
    !hasStyle ? "" : `<div><b>Style</b> is based on a clustering exercise using twelve measured 
      tennis metrics. Players with similar charted fingerprints are grouped, and each group is 
      named for what its center looks like.
      ${/* The gate is not a detail. Style is a continuum: the clustering scores a silhouette
           near 0.12, and for about a third of players the nearest two groups fit equally
           well. Those are exactly the players whose label flipped wholesale when a fifth of a
           percent of the charting corpus was removed and their own fingerprint had not moved
           at all. Naming one of them is a coin toss reported as a finding, so the panel
           doesn't. */""}
      <b>"Between styles"</b> means the two nearest groups fit this player about equally well.</div>`,
    // The key follows the column, so it opens on the figure the column leads with. Kept to one
    // line: the concept is plain, and the only thing a reader needs told is what gets counted.
    !has("avg_rally_len") ? "" : `<div><b>Average point length</b> counts the serve that starts it and the
      shot that ends it.</div>`,
    !has("bits") ? "" : `<div><b>Variety</b> is how far a player's shot choices stray from
      tour norms. A model built on the whole tour predicts each next shot from the two before
      it, and variety is how surprised that model is by this player, averaged over their shots
      and measured in bits: a shot the model gave even odds scores 1 bit, and every bit past
      that is a shot half as likely again. It rewards uncommon shot types about as much as
      uncommon order, so slicers and serve-volleyers score high. A player needs 800 charted
      strokes to get one.</div>`,
  ].filter(Boolean);
  if (!defs.length) return "";
  return `<details class="notekey figkey">
    <summary>How these figures are measured</summary>
    <div class="keytext">${defs.join("")}</div>
  </details>`;
}

function tape(da, db, spread) {
  // The rings take only the sides that clear the coverage floor; the profile columns beside
  // them take the player whole, since every figure in them carries its own gate already. A
  // side held back leaves its half of the ring empty, which is the shape the drawing already
  // has for a player the rates simply do not exist for — and the note says which it is, so an
  // empty half is never left reading as "no charting" when it means "not enough of it".
  const sa = wellCharted(da) ? da.s : null, sb = wellCharted(db) ? db.s : null;
  const cells = sa || sb ? tapeRows().map((r) => donut(r, sa, sb)).join("") : "";
  const sideA = profileSide(da, db, "a"), sideB = profileSide(db, da, "b");
  if (!cells && !sideA && !sideB) return "";
  const rings = cells ? `<div class="dnstack">${cells}</div>` : "";
  // Named, not just omitted. A blank half beside a full one is the panel making a claim about
  // the thin player, and the claim it should make is about the charting rather than the
  // tennis.
  const thin = [[da, sa], [db, sb]]
    .filter(([d, s]) => d && !s).map(([d]) => last(d.s.player));
  const thinNote = thin.length
    ? `<p class="tapenote">Serve and return rates need ${RATE_MIN_PTS.toLocaleString()}
       charted points to print; ${esc(thin.join(" and "))}
       ${thin.length > 1 ? "are" : "is"} below that.</p>` : "";
  // No header and no section wrapper: it carries straight on from the charted-history coverage
  // above it, which every figure here is measured against, so a labelled gap between the two
  // would only push them apart. The bordered box is its own boundary.
  return `<section class="tape">
    <div class="tapemain">${sideA}${rings}${sideB}${profileCompare(da, db)}</div>
    ${/* No key under the rings. Every mark on them now carries its own figure against it,
         wearing the mark as a glyph, so a key would be naming things the drawing has already
         named — and naming them a screen away from where they are. */""}
    ${thinNote}
    ${figureKey(sa || (da && da.s), sb || (db && db.s), spread)}
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

function section(title, note, a, b, aHtml, bHtml, kind = "cards") {
  if (!aHtml && !bHtml) return "";
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
  return `<section class="msec ${kind}">
    <h3 class="sechead">${title}</h3>
    ${note ? `<p class="secnote">${note}</p>` : ""}
    <div class="seccols" style="--rows:${rows}">${col(aHtml, a, "a")}${col(bHtml, b, "b")}</div>
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
        <code>net</code> volley, overhead, or other net shot ·
        <code>shot</code> stroke type not charted</div>
      <div><code>→1/2/3</code> where it was hit, seen from the hitter: zone 1 is a
        right-hander's forehand side, 3 their backhand side (<code>→·</code> =
        direction not charted).</div>
      <div>Every court drawing reads the same way: the tinted half is the profiled
        player's side, a solid line in their colour is a ball they hit, a dashed grey one
        is the opponent's, and the ring is the bounce the drawing turns on. On a court
        pattern that ring is the ball they answered, and the arrow is the answer. On a
        trigger it is the ball they attacked — the shot they went for is what the numbers
        beside it measure, and it isn't drawn, because the notation never says where it
        went.</div>
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
  const cell = (v, o) => {
    if (v == null) return `<span class="sg"></span>`;
    const won = o != null && Math.trunc(v) > Math.trunc(o);
    return `<span class="sg${won ? " won" : ""}">${Math.trunc(v)}</span>`;
  };
  let cells = "";
  for (let i = 0; i < n; i++) {
    const x = a.sets && a.sets[i], y = b.sets && b.sets[i];
    if (x == null && y == null) continue;    // drop the pair, never half of one
    cells += cell(x, y) + cell(y, x);
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
  const event = t.completed ? `${ename(t)} ${t.season}` : ename(t);
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

// The body, under one title: who the two players are, then the two headline rings, then where
// the serve goes, then the pictures, then the sequences, then the small print. Every section
// shares one header across both columns, so the two players stay level however unevenly
// charted they are.
//
// The coverage band leads, under "Charted history", because the charted counts are the
// denominator of every number in the panel — everything under it is read through them.
//
// "Side by side" comes next, and now opens with style, hand, and the per-player figures ahead
// of the two rings: the handedness there is the key to reading the court drawings two sections
// down, so it has to arrive before them, and style and shot quality are the first per-player
// comparison the body makes, which is what the section is for.
//
// Serve direction is then the first single-player measurement. Every point starts with one, it
// is the only thing here a viewer can expect to see happen in the match they just tapped, and
// it is the shortest section in the panel — so it reads as an opening rather than as something
// to scroll past.
//
// The three pattern sections then run in the order a point does: where the serve goes, what the
// server does with the ball it comes back as ("off the return"), and only then the mid-rally
// exchange ("court patterns"). Off the return is built out of the service court and the serve's
// own direction, so it continues the section above it. Below court patterns it would put a
// mid-rally ball between the serve and the shot the serve sets up.
//
// The title is gated on there being a player under it. With neither side charted the body is
// the invitation to go and chart one, and "Charted history" over "Neither player has Match
// Charting history yet" heads a section with the word "history" twice and no history in it.
// The two conditions are exact opposites, so exactly one of them ever prints.
function bodyHtml(m, pa, pb, gates, spread) {
  const a = m.a, b = m.b;
  const ta = trigSets(pa), tb = trigSets(pb);
  const none = !pa && !pb
    ? `<p class="nochart">Neither player has Match Charting history yet.
       <a href="${CHART_GUIDE}" target="_blank" rel="noopener">Chart a match →</a></p>` : "";
  return (pa || pb ? CHARTED_TITLE + profileBand(pa, pb) : "") +
    tape(pa, pb, spread) +
    section("serve direction", `recency weighted measures of first serve direction by court side`, a, b,
      serveHtml(pa, gates), serveHtml(pb, gates), "text") +
    none +
    section("serve + 1", `what they do with returns${PAYOFF_LEGEND}`, a, b,
      familyCards(pa, "ret", 2), familyCards(pb, "ret", 2), "cards") +
    section("court patterns", `what they do with an incoming ball, × how often the tour
      of their own era plays it from the same
      spot${COURT_LEGEND}${PAYOFF_LEGEND}`, a, b,
      familyCards(pa, "rally", 3), familyCards(pb, "rally", 3), "cards") +
    section("shot-making triggers", `a lead-up that shifts their aggressive shot
      frequency — and whether it converts as well as their other cues
      do${meterLegend("their rate with no cue")}`,
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
let condFit = 0;
function onBodyScroll() {
  const panel = document.getElementById("matchup");
  const t = document.getElementById("matchupBody").scrollTop;
  const was = panel.classList.contains("cond");
  if (t > 24) panel.classList.add("cond");
  else if (t < 8) panel.classList.remove("cond");
  if (panel.classList.contains("cond") === was) return;
  // Condensing is not only a shrink. It also moves the right-hand name into the close
  // button's lane (see --close-lane), and that is width taken off a name fitHeader() sized
  // without it — so "S. Tsitsipas", fitted at the top of the scroll, came back one line
  // down and then, once overflow-wrap ran out of patience, broken across the middle of a
  // word. So the fit is re-asked on the transition, which happens twice a scroll at most;
  // on every scroll event it would force layout several times a frame to answer a question
  // that hasn't changed.
  // After the band's size transition, not during it: .mp animates its font-size, and a
  // name measured mid-transition is measured at a size it is on its way out of — which
  // resolves, every time, toward abbreviating a name that would have fitted.
  clearTimeout(condFit);
  condFit = setTimeout(fitHeader, 200);
}

// Has either name been broken over more than one line?
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
function namesWrap(grid) {
  for (const n of grid.querySelectorAll(".mname")) {
    const lh = parseFloat(getComputedStyle(n).lineHeight);
    if (lh > 0 && n.clientHeight > lh * 1.5) return true;
  }
  return false;
}

// Fit the scoreboard to the match in front of it, measured rather than assumed, giving up
// the cheapest thing first.
//
// Three things to spend, in the order they are worth least.
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
// The staggered layout is the dear one. It is what ties each scoreline to the name it
// belongs to, and its fallback — both names level, the games stacked between them — works
// at any width but says less. So it is given up last, and only when a closed-up gap and an
// abbreviated name together still leave something wrapping.
//
// The gap is re-spent after each of the other two, because every one of them changes what
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
// there changes nothing, so the second gap pass simply re-reaches the same answer.
//
// Runs on open and on resize, and deliberately not on the body's scroll: each pass forces
// layout several times over, and condensing only ever makes the names smaller, so it cannot
// introduce a wrap that wasn't already there.
// Set the widest gap in [min, max] that still holds every name on one line, and say whether
// there was one. Left at the full gap when even min can't manage it, since a gap given up to
// a wrap that happened regardless is just a narrower gap.
//
// Searched rather than calculated: what a name needs is only knowable by laying it out, and
// the arithmetic — a gap surrendered returns twice itself to the two name tracks — quietly
// stops holding once both names are against the limit at the same time. Wrapping is
// monotonic in the gap, though; narrowing it can only ever give the names room. So the
// boundary can be bisected, with lo always fitting and hi never, in five or six passes.
function fitGap(grid, max, min) {
  const setGap = (g) => grid.style.setProperty("--mgap", `${g}px`);
  if (!namesWrap(grid)) return true;                   // fits at the full gap
  setGap(min);
  if (namesWrap(grid)) { grid.style.removeProperty("--mgap"); return false; }
  let lo = min, hi = max;
  while (hi - lo > 1) {
    const mid = Math.floor((lo + hi) / 2);
    setGap(mid);
    if (namesWrap(grid)) hi = mid; else lo = mid;
  }
  setGap(lo);
  return true;
}

function fitHeader() {
  const grid = document.querySelector("#matchupHead .mgrid");
  if (!grid) return;
  // Both off first: the question is what the *full* staggered layout does, so that has to
  // be the thing measured. Left set from a narrower window they would answer about
  // themselves and never come back off.
  grid.classList.remove("stacked", "abbr");
  grid.style.removeProperty("--mgap");

  const cs = getComputedStyle(grid);
  const max = parseFloat(cs.getPropertyValue("--mgap-max")) || 0;
  const min = parseFloat(cs.getPropertyValue("--mgap-min")) || 0;

  // full names, staggered — spend only the gap
  if (fitGap(grid, max, min)) return;
  // first name to an initial, and the gap offered again against the shorter names
  grid.classList.add("abbr");
  if (fitGap(grid, max, min)) return;
  // still not enough: give the stagger up too, and spend the gap into what replaced it
  grid.classList.add("stacked");
  fitGap(grid, max, min);
}

let fitQueued = false;
function onResize() {
  if (fitQueued) return;
  fitQueued = true;
  requestAnimationFrame(() => { fitQueued = false; fitHeader(); });
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

  let pa, pb, gates, spread;
  try {
    [pa, pb] = await Promise.all([
      playerData(m.a.matched, t.gender),
      playerData(m.b.matched, t.gender),
    ]);
    gates = (await serveGates())[t.gender] || {};
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
  slot.innerHTML = bodyHtml(m, pa, pb, gates, spread);
}
