// The matchup drawer: experimental pre-match win probability + a card per player,
// all queried from insights.duckdb via DuckDB-WASM.
import { query, leagueMu, serveGates, tourSpread } from "./db.js";
import { preMatchWP } from "./winprob.js";
import { patternSvg, pairSvg, shotLine } from "./court.js";

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
      "SELECT tag, context, att_rate, att_lift, conversion, conv_delta, n, depth " +
      "FROM player_triggers WHERE player = ? AND gender = ?", [name, gender]);
  } catch (e) { /* stale insights db: show the card without tendencies */ }
  let patterns = [];
  try {
    patterns = await query(
      "SELECT family, state, response, state_depth, inc_code, resp_code, lift, count, n_state, " +
      "win_rate, tour_win_rate " +
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
  return { s: s[0], triggers, patterns, serve };
}

// Where a value stands in the tour's own sorted values: the share of charted players it is
// above, 0–1. Bisected rather than scanned — the arrays are a few hundred long and every
// panel asks this four or five times.
function pctile(sorted, v) {
  if (!sorted || !sorted.length || v == null) return null;
  let lo = 0, hi = sorted.length;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (sorted[mid] < v) lo = mid + 1; else hi = mid;
  }
  return lo / sorted.length;
}

// A percentile as a share, held off both ends: nobody is "ahead of 0%" or "ahead of 100%"
// of a group they are themselves in, and printing either invites the reader to check a
// claim the number was never making.
const pctileFmt = (p) => `${Math.min(99, Math.max(1, Math.round(p * 100)))}%`;

// The benchmark is no longer the mean of the archetype a player was sorted into — it is
// what their own style fingerprint predicts, fitted smoothly across the style space — so
// the wording names the style rather than the box. It also has to stay true for a player
// whose archetype is withheld: "below their archetype" reads oddly beside a card that
// declines to say which archetype that is, and this trio doesn't depend on one.
function ratingLabel(z) {
  if (z == null) return "";
  if (z <= -0.5) return "beats their style";
  if (z >= 0.5) return "below their style";
  return "typical for their style";
}

// A collapsed mini-court under a pattern: tap to see where the lead-up shots landed,
// drawn on the fly from the notation (client twin of viz.rally_svg). Empty when the
// pattern has no chartable direction, so there's nothing to draw.
function rallyDrawer(pattern) {
  const svg = patternSvg(pattern);
  return svg ? `<details class="rally"><summary>ball path</summary>
    <div class="court">${svg}</div></details>` : "";
}

// One decision, two outcomes: a green light converts, a trap is taken bait. The cue is
// the lead-up sequence; the two numbers are how often it provokes a go-for-it shot and
// how often that shot pays. Courts stay collapsed here — a trigger is a 2–4 stroke
// sequence, and a column of full sequence drawings would bury the court patterns above,
// which are what the panel leads with.
// The cue's two numbers, drawn as the one bar they are: its length is how often the cue
// makes them go for a finishing shot, where it changes colour is how much of that landed,
// and the tick is the rate the shot gets played at *without* the cue — so the lift the
// sentence states as "3.0× their norm" is also the gap between the tick and the bar's end.
//
// Deliberately the same construction as the comparison strip's winners-and-errors row,
// down to the drained second segment and the haloed reference tick, because it is the same
// measurement: the notation key already tells the reader these are "the same pair of
// numbers the strip up top splits into one bar, read per cue". They should look like it.
// The domain is 0–1 rather than the strip's 0.05–0.32, though: a cue that does anything at
// all pushes the attempt rate far past the range a player's rally balls average out to, and
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

function trigLine(t) {
  // Gold: a 3-4 shot sequence that beats its own shorter pattern and replicates across
  // halves of the player's data — only the hugely-charted earn these.
  const deep = Number(t.depth) > 2;
  const trap = t.tag === "trap";
  const cls = deep ? "gold" : trap ? "bait" : "green";
  const conv = Math.round(t.conversion * 100);
  // A deep pattern already claims the ⭐, so a deep *trap* would otherwise lose its
  // warning entirely — it keeps a ⚠ on the number that makes it one.
  const payoff = trap
    ? `converts only <b>${conv}%</b>${deep ? ' <span class="warnmark">⚠</span>' : ""}
       <span class="lift">${Math.round(t.conv_delta * 100)}pp vs their norm</span>`
    : `converts <b>${conv}%</b>`;
  const against = deep ? "the shorter pattern" : "their norm";
  return `<div class="trig ${cls}"${deep
    ? ` title="deep pattern: only visible with this player's huge charted history"` : ""}>
    <p class="tcue">after <code>${esc(t.context)}</code></p>
    <p class="tnum">goes for it <b>${Math.round(t.att_rate * 100)}%</b>
      <span class="lift">${Number(t.att_lift).toFixed(1)}× ${against}</span> ·
      ${payoff} <span class="lift">n=${Number(t.n)}</span></p>
    ${trigMeter(t)}
    ${rallyDrawer(t.context)}</div>`;
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
  // moves placement more than the score does. Starred like a deep pattern, and for the
  // same reason — most players show nothing here, because most players' break-point
  // placement is indistinguishable from their normal-point placement once the
  // multiplicity correction is applied.
  let bp = "";
  const delta = d.s && d.s.serve_bp_wide_delta;
  if (d.s && Number(d.s.serve_bp_sig) === 1 && delta != null) {
    const pts = Math.round(Math.abs(delta) * 100);
    bp = `<p class="srvbp" title="a shift this size clears the experiment's significance
      test; most players show nothing here">on break points, <b>${pts} points</b> ${delta > 0 ? "wider" : "less wide"} than their own norm</p>`;
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
  // Payoff: their point-win rate playing this response vs the tour's playing the same
  // response to the same ball — the choice is the lift, this is what it earns. Level
  // with the tour is stated rather than left blank, so a missing arrow always means
  // the comparison is genuinely unavailable and never that the gap rounded to zero.
  let payoff = "";
  if (p.win_rate != null) {
    const w = `wins <b>${Math.round(p.win_rate * 100)}%</b>`;
    if (p.tour_win_rate == null) {
      payoff = ` · ${w}`;
    } else {
      const d = Math.round((p.win_rate - p.tour_win_rate) * 100);
      payoff = ` · ${w} ` + (d === 0 ? `<span class="lvl">level with tour</span>`
        : `<span class="${d > 0 ? "up" : "down"}">${d > 0 ? "▲" : "▼"}${Math.abs(d)} vs tour</span>`);
    }
  }
  return `<div class="pcard2">
    <div class="pcourt">${pairSvg(p.inc_code, p.resp_code, p.state_depth)}</div>
    <div class="pmeta">
      <p class="plift">${Number(p.lift).toFixed(1)}×<span> the tour</span></p>
      <p class="pdesc">${esc(p.state)}<b>→ ${esc(p.response)}</b></p>
      <p class="pfoot">n=${Number(p.count).toLocaleString()}${payoff}</p>
    </div>
  </div>`;
}

const familyCards = (d, fam, n) => !d ? "" :
  d.patterns.filter((p) => p.family === fam).slice(0, n).map(patternCard).join("");

// The player's own rate, with no cue at all: how often a rally ball of theirs is an attempt
// at a finishing shot, and how much of that lands.
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
    <p class="tnum">goes for it <b>${(att * 100).toFixed(1)}%</b>${conv == null ? ""
      : ` · converts <b>${Math.round(conv * 100)}%</b>`}
      ${/* Not quite the same number as the ticks below, and said so: each cue's tick is the
           player's rate with that cue's own balls taken out, which moves it by a tenth of a
           point on a career of twenty thousand. Near enough to read off, not near enough to
           claim they are the same figure. */""}
      <span class="lift">each tick below is this, without that cue's own balls</span></p>
    <div class="tmeter"><i style="width:${(att * 100).toFixed(1)}%">${segs}</i></div>
  </div>`;
}

// A player's triggers, split the way the panel shows them: their own baseline rate, then the
// shallow green lights and traps, then the deep sequences, then the note that earns its place
// by absence.
//
// The baseline comes from player_summary rather than from the trigger table, so it prints for
// a player charted enough to have a rate but not enough for any cue to clear the significance
// test — which is most of the tour, and which used to leave their column saying only "nothing
// at this player's coverage".
function trigSets(d) {
  if (!d) return { main: "", gold: "" };
  const base = trigBase(d);
  if (!d.triggers.length) return { main: base, gold: "" };
  const shallow = d.triggers.filter((t) => !(Number(t.depth) > 2));
  const greens = shallow.filter((t) => t.tag === "green")
    .sort((a, b) => b.att_lift - a.att_lift).slice(0, 3);
  const traps = shallow.filter((t) => t.tag === "trap")
    .sort((a, b) => a.conv_delta - b.conv_delta).slice(0, 2);
  const gold = d.triggers.filter((t) => Number(t.depth) > 2)
    .sort((a, b) => b.att_lift - a.att_lift).slice(0, 3);
  const immune = d.s.n_traps != null && Number(d.s.n_traps) === 0
    ? `<div class="trig immune">no trap sequences — every lead-up that raises their
       aggression also meets their usual conversion</div>` : "";
  return {
    main: base + [...greens, ...traps].map(trigLine).join("") + immune,
    gold: gold.map(trigLine).join(""),
  };
}

// --- "side by side": one ring per metric ----------------------------------------------
// The axis the two players used to diverge along, bent into a circle. 12 o'clock is the
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
// This used to be a *zoomed* window per metric — 50–80% for serve points, 5–32% for winners
// and errors — picked so that two tour pros, whose numbers differ by a point or two, drew
// visibly different bars. On bars that was defensible; a track with no ends doesn't claim to
// be anything. On a ring it wasn't: a closed loop reads as a whole, so "how full" reads as a
// share of it, and identical circles side by side invite exactly the comparison the windows
// didn't support. It showed: 66.5% of serve points and 19.8% of rally strokes drew the same
// 99° arc, because each sat 55% of the way through its own window.
//
// The cost of zeroing them is real and is paid in resolution. 66.5% against 68.1% is under
// three degrees, which nobody can see. The figures either side of the ring carry that
// comparison now, the leader is the one set in ink, and the tour tick is where the picture
// still says something — it shows how narrow these gaps genuinely are.
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
// `avg` puts a tick on the ring at the tour reference where one exists. `better` says which
// direction wins.
const clamp01 = (x) => Math.max(0, Math.min(1, x));
const num = (v) => (v == null ? null : Number(v));

function tapeRows(mu) {
  return [
    // The sweep is how often they win a service point; where it changes colour is how much
    // of that they never had to play for. Aces are a subset of service points won, so the
    // split is aces over *points won* — the share of this sweep — while the number under the
    // total is the ace rate as it is normally quoted, over every service point they hit.
    // Two different denominators, which is why only one of them is printed: the ring carries
    // the other one as an angle, where it doesn't have to be read as a figure.
    // Absent for a thinly-charted player (the build floors it at ~2 matches of service
    // points), and the arc is then simply one colour.
    {
      k: "serve_rate", label: "serve points won", hi: 1, top: "100%", better: "hi",
      avg: mu, fmt: pct,
      sub: (s) => s.ace_rate == null ? "" : `${(Number(s.ace_rate) * 100).toFixed(1)}% aces`,
      parts: (s) => {
        if (s.ace_rate == null) return null;
        const f = clamp01(Number(s.ace_rate) / Number(s.serve_rate));
        return [{ f, cls: "deep" }, { f: 1 - f }];
      }
    },
    // Ceilinged at 0–67% rather than 0–100%. Returning is the half of tennis nobody wins
    // outright — the best charted return games on either tour reach 46% (men) and 52%
    // (women) — so against a full 100% this ring spent two thirds of its climb on ground no
    // player has ever stood on, and the whole metric sat in the first third of the arc.
    // The cost is that its arcs are no longer the same scale as the rings either side of it:
    // 41.1% here climbs about as far as 66.5% does on serve points. That is what the scale
    // under the name is for, and why the note below stops short of saying arcs compare
    // between rings.
    {
      k: "return_rate", label: "return points won", hi: 0.67, top: "67%", better: "hi",
      avg: 1 - mu, fmt: pct
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

// A spoke across the ring at `deg`, `out` units past its edges. Used twice: for the tour
// average, and for the origin seam at the foot.
function dnSpoke(deg, out, cls) {
  const [x1, y1] = dnPoint(deg, DN_R - DN_W / 2 - out);
  const [x2, y2] = dnPoint(deg, DN_R + DN_W / 2 + out);
  return `<line class="${cls}" x1="${x1.toFixed(2)}" y1="${y1.toFixed(2)}"` +
    ` x2="${x2.toFixed(2)}" y2="${y2.toFixed(2)}"/>`;
}

// The tour average. Two spokes on the same line, the wider dark one under the narrower light
// one, which is the strip's haloed tick drawn in SVG — it has to survive both the saturated
// arc and the empty track, and no one colour does.
const dnTick = (deg) => dnSpoke(deg, 1.6, "dtickhalo") + dnSpoke(deg, 1.6, "dtick");

// Zero, cut into the foot of the ring. The two sweeps leave in opposite directions from this
// point, so without it they abut and the ring reads as one continuous band that happens to
// change colour somewhere — with the origin, which is the thing both sweeps are measured
// from, left to be inferred from the colour change. It is the polar version of the hairline
// that stood between the two bars, and it is drawn in the card's own colour so it reads as a
// gap in the ring rather than as one more mark laid on top of it.
const dnOrigin = () => dnSpoke(180, 0.5, "dorigin");

// One player's number and its qualifier, on that player's side of the ring. No colour chip —
// position says whose it is, the way it did when these were bars.
const dnFlank = (it, tag) => `<div class="dside ${tag}">
  <div class="dpair">
    <span class="dv${it.lead ? " lead" : ""}">${it.v == null ? "—" : it.fmt(it.v)}</span>
    ${it.sub ? `<span class="ds">${esc(it.sub)}</span>` : ""}
  </div></div>`;

// A ring cell: the name, then a player, the ring, and the other player. The scale used to be a
// line of small print under the name; it is now written on the picture at the two ends it
// actually refers to, which is where a reader looks for it.
const dnCell = (label, a, art, b) => `<div class="dn">
  <p class="dnkey">${esc(label)}</p>
  <div class="dnrow">${a}${art}${b}</div>
</div>`;

function donut(r, sa, sb) {
  const va = sa ? num(sa[r.k]) : null;
  const vb = sb ? num(sb[r.k]) : null;
  if (va == null && vb == null) return "";
  const lead = r.better && va != null && vb != null && va !== vb
    ? ((va > vb) === (r.better === "hi") ? "a" : "b") : "";
  const at = (v) => clamp01(v / r.hi) * 180;
  // An arc is one colour unless the metric splits it: then the segments are shares of that
  // player's own sweep, laid out from the foot upward, so both players' first segments start
  // from the shared origin and stay directly comparable.
  const arc = (v, s, side) => v == null ? ""
    : dnArc(at(v), (r.parts && s ? r.parts(s) : null) || [{ f: 1 }], side);
  const item = (v, s, tag) => ({
    v, fmt: r.fmt, lead: lead === tag,
    sub: v == null || !r.sub ? "" : r.sub(s)
  });
  // "no data" only in the label a screen reader hears — set beside the picture it would be a
  // sentence where every other cell holds a figure, which is what the em dash is for.
  const say = (v) => (v == null ? "no data" : r.fmt(v));
  // The two ends of the scale, at the two ends of the ring. Both sweeps start at the foot and
  // finish at the top, so those are the only two places the numbers could go and mean
  // anything — and put there they are read off the picture rather than remembered from a
  // caption above it.
  return dnCell(r.label,
    dnFlank(item(va, sa, "a"), "a"),
    `<div class="dnring">
      <span class="dncap">${esc(r.top)}</span>
      <svg viewBox="0 0 100 100" xmlns="http://www.w3.org/2000/svg" role="img"
        aria-label="${esc(`${r.label} — ${say(va)} against ${say(vb)}`)}">
        <circle class="dtrack" cx="${DN_C}" cy="${DN_C}" r="${DN_R}"/>
        ${arc(va, sa, "a")}${arc(vb, sb, "b")}${dnOrigin()}
        ${/* one per side, and only where that side has a sweep to read it against — a lone
             tick on an empty half is a reference for a number that isn't there */""}
        ${r.avg == null || va == null ? "" : dnTick(dnAt(at(r.avg), "a"))}
        ${r.avg == null || vb == null ? "" : dnTick(dnAt(at(r.avg), "b"))}
      </svg>
      <span class="dncap">0</span>
    </div>`,
    dnFlank(item(vb, sb, "b"), "b"));
}

// --- variety and shot selection, against the tour they were measured on -----------------
// Two numbers a reader has no scale for. "3.2 bits" and "σ 5.5pp" are not quantities anyone
// arrives with an instinct about, and the pair of them used to be plotted on a field running
// from zero to a ceiling picked just past the tour's highest — which put every player in the
// world inside one small patch near the middle, two dots on top of each other, with the same
// three-word qualifier printed beside both of them.
//
// It was not the drawing's fault. The words underneath it were calibrated the same way: on the
// built table, the thresholds that separated "fairly patterned" from "average variety" from
// "unusually varied" sat at roughly the 27th and 93rd percentile of the charted men, so two
// players in three got the middle word whatever they actually did. A field divided into nine
// regions by those lines is nine regions one of which holds nearly everybody.
//
// So the scale is the tour itself. Each axis is a track running from the lowest charted player
// on that tour to the highest, with the distribution of all of them drawn behind it, and each
// player marked where they stand in it. The reading is a percentile, which is a sentence
// anyone can finish: more varied than 77% of the tour. The shape behind the marks is the other
// half of it — it shows that most of the tour is bunched and the top end is a long thin tail,
// which is why two players a fifth of a bit apart can be twenty-five percentiles apart.
//
// They stay together in one cell, and stacked rather than crossed. The scatter's argument for
// crossing them was that they are independent (they correlate +0.21 on the men's side and
// −0.16 on the women's, so the sign does not even survive the change of tour) and that the
// corner a player stands in is the finding. With two dots and no third player to compare
// against, the corner was never legible; two tracks say each half plainly and the reader can
// still hold them together, because they are six lines apart under one heading.
// `end` is how the two ends of the track are written, where that differs from how a player's
// own figure is: the ends are read as a range and want to be as short as a range is, and "σ"
// printed four times across one axis says nothing after the first. Left off where the two are
// the same thing.
const VARY = [
  { k: "bits", label: "variety", blurb: "how much their shot mix moves",
    fmt: (v) => `${v.toFixed(1)} bits`, more: "more varied than" },
  { k: "sigma", label: "shot selection", blurb: "how much the situation moves it",
    fmt: (v) => `σ ${(v * 100).toFixed(1)}pp`, end: (v) => `${(v * 100).toFixed(1)}pp`,
    more: "more cue-driven than" },
];

// How coarsely the tour's distribution is binned behind a track. 20 bins over the ~190 charted
// men who have a variety number is about ten to a bin at the mode and one or none out in the
// tail, which is the shape being drawn — finer and it comes apart into noise, coarser and the
// bunching that is the whole point of showing it flattens out.
const VBINS = 20;

// The tour's distribution as one filled area, in a 20-unit-tall box that is stretched to
// whatever width the track gets. preserveAspectRatio="none" and a fill with no stroke: a
// stroked outline would come out thick horizontally and hairline vertically under that
// stretch, where a filled shape is simply the shape.
function distArea(tour) {
  const lo = tour[0], hi = tour[tour.length - 1];
  if (!(hi > lo)) return "";
  const counts = new Array(VBINS).fill(0);
  for (const v of tour) {
    counts[Math.min(VBINS - 1, Math.floor((v - lo) / (hi - lo) * VBINS))]++;
  }
  const top = Math.max(...counts);
  const w = 100 / VBINS;
  let d = "M0,20";
  counts.forEach((c, i) => {
    const y = (20 - (c / top) * 20).toFixed(2);
    d += ` L${(i * w).toFixed(2)},${y} L${((i + 1) * w).toFixed(2)},${y}`;
  });
  return `<svg class="vdist" viewBox="0 0 100 20" preserveAspectRatio="none"
    xmlns="http://www.w3.org/2000/svg" aria-hidden="true"><path d="${d} L100,20 Z"/></svg>`;
}

// One axis: the name, the distribution with both players marked on it, its two ends, and a
// reading per player.
//
// The marks are HTML over the drawing rather than shapes inside it, for the same reason the
// scatter's axis labels were: anything inside a stretched viewBox is stretched with it. A mark
// out here is a 2px rule at a left offset, the same 2px at any panel width.
//
// The two readings sit under the track, A at the left end and B at the right, and each carries
// a colour chip — the one place in the panel where a chip earns itself. Everywhere else the
// two players hold their own halves of the layout and position is the key. Here they share one
// track, and a player can perfectly well be the left-hand reading with the right-hand mark.
function varyAxis(r, sa, sb, tour) {
  const lo = tour[0], hi = tour[tour.length - 1];
  const at = (v) => clamp01((v - lo) / (hi - lo)) * 100;
  const end = r.end || r.fmt;
  const val = (s) => (s ? num(s[r.k]) : null);
  const mark = (s, tag) => {
    const v = val(s);
    return v == null ? ""
      : `<i class="vmark ${tag}" style="left:${at(v).toFixed(1)}%"></i>`;
  };
  const read = (s, tag) => {
    const v = val(s), p = pctile(tour, v);
    return `<div class="vread ${tag}">
      <span class="vv"><span class="tdot ${tag}"></span>${v == null ? "—" : esc(r.fmt(v))}</span>
      ${p == null ? "" : `<span class="ds">${r.more} ${pctileFmt(p)}</span>`}</div>`;
  };
  const say = (s) => { const v = val(s); return v == null ? "no data" : r.fmt(v); };
  return `<div class="vax">
    <p class="vname">${esc(r.label)} <span>${esc(r.blurb)}</span></p>
    <div class="vplot" role="img" aria-label="${esc(`${r.label}, across ${tour.length}
      charted players from ${r.fmt(lo)} to ${r.fmt(hi)} — ${say(sa)} against ${say(sb)}`)}">
      ${distArea(tour)}${mark(sb, "b")}${mark(sa, "a")}
    </div>
    <div class="vends"><span>${esc(end(lo))}</span><span>${esc(end(hi))}</span></div>
    <div class="vreads">${read(sa, "a")}${read(sb, "b")}</div>
  </div>`;
}

// An axis appears only where there is a tour to stand it against and at least one of the two
// players is on it. The floor on the tour's size is not decoration: a percentile out of thirty
// players is a rank dressed up as a rate, and the distribution behind it would be drawing
// twenty bins out of thirty numbers.
function varyCell(sa, sb, spread) {
  const axes = VARY
    .map((r) => [r, spread[r.k] || []])
    .filter(([r, tour]) => tour.length >= 60 && (num(sa && sa[r.k]) != null || num(sb && sb[r.k]) != null));
  if (!axes.length) return "";
  return `<div class="dn wide">
    <p class="dnkey">how guessable they are</p>
    <p class="dnsub">each of them against every charted player on this tour — so the
      percentages below are shares of that tour, not of anything in this match</p>
    ${axes.map(([r, tour]) => varyAxis(r, sa, sb, tour)).join("")}
  </div>`;
}

// Who these two players are, over everything the body then measures. It carries the three
// facts every section below is read through — what kind of player this is, which hand they
// hold the racket in, and how much of them the charting actually has — plus the one score
// that belongs with them rather than in a comparison.
//
// It sits here, directly under the scoreboard and above the first section, because the
// charted counts are the denominator of every number in the panel and were previously three
// screens down inside the side-by-side strip, under the numbers they qualify. Style and
// handedness were down there with them, and the court patterns two sections further on name
// their zones by the player's own hand — "the BH corner" is a different corner for a lefty —
// so the key to reading those drawings was arriving after them.
//
// No name and no flag: the scroll-locked match header above carries those, and this side of
// the panel is the same player in the same position. The player colours (--a / --b) are
// declared by the split rule under that header, its left half player A and its right half
// player B; the rule across the top of each half here is the same colour, and it is the same
// mark that caps each column further down.
function profileSide(d, tag, spread) {
  // An uncharted player is the site's whole invitation, so the ask sits at the top of their
  // side rather than only in the empty columns below it.
  if (!d) {
    return `<div class="pbside ${tag}" data-side="${tag}">
      <p class="pbnone">not charted yet —
        <a href="${CHART_GUIDE}" target="_blank" rel="noopener">chart a match →</a></p></div>`;
  }
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
  // Shot quality, out of a hundred it never approaches. The charted tour runs from about 49
  // to 73, so 61/100 reads as a middling mark and is in fact within a point of the median —
  // which is why the percentile is printed under it and the ring it used to have is gone. A
  // ring drew that whole distribution inside a quarter turn.
  //
  // The two lines under the score are two different questions and both are worth asking: how
  // they rank against everyone, and how they rank against what their own style predicts. The
  // second is the class_relative_wpa experiment's finding and can disagree with the first —
  // a style whose players all execute well produces a good absolute score that is below par
  // for the style.
  const acc = num(s.accuracy);
  const p = pctile(spread.accuracy, acc);
  const notes = [p == null ? "" : `ahead of ${pctileFmt(p)} of the tour`,
    ratingLabel(s.class_rel_z)].filter(Boolean).join(" · ");
  // One decimal, though the score is a coarse thing. Rounded to a whole number the two
  // players print the same figure often — the charted tour spends most of its range in the
  // fifties and sixties — and then sit above two different percentiles, which reads as an
  // error in one line or the other rather than as two numbers at different resolutions.
  //
  // Neither figure is set as the leader, unlike the rings below. This is a per-player fact
  // sitting in a per-player band, and the gaps are of a size — 60.7 against 60.8 — where ink
  // saying "this one is ahead" is a claim about the third significant figure of a rating that
  // does not have three. The percentile under it already does the comparing, at the
  // resolution the comparison survives at: ahead of 25% of the tour against ahead of 28%.
  const quality = acc == null ? "" : `
    <p class="pbq"><b>${acc.toFixed(1)}</b><span>/100</span>
      <em>shot quality</em></p>
    ${notes ? `<p class="pbnote">${esc(notes)}</p>` : ""}`;
  // "charted:" is stated rather than implied: these counts are how much of the player exists
  // in the data, not how much tennis they have played.
  return `<div class="pbside ${tag}" data-side="${tag}">
    ${arch ? `<p class="pbstyle">${esc(arch)}</p>` : ""}
    ${hand ? `<p class="pbhand">${esc(hand)}</p>` : ""}
    ${quality}
    <p class="pbchart">charted: ${s.matches_charted} matches ·
      ${Number(s.points_charted).toLocaleString()} points</p>
  </div>`;
}

function profileBand(da, db, spread) {
  if (!da && !db) return "";
  return `<div class="pband">
    ${profileSide(da, "a", spread)}${profileSide(db, "b", spread)}</div>`;
}

// The one line over the whole body. The scoreboard above it never says "this match" — it
// can't, nothing under here is about this match — so the body has to say what it is itself,
// before any of its numbers do.
//
// It used to ride inside the strip and head only what followed the strip, which left serve
// direction above it uncovered once that section moved to the top. Everything in the body is
// the same thing: what the charting has of these two players. So the line heads all of it.
//
// "Their charted matches, not this one", and no longer "career totals": serve direction is a
// recent-form window rather than a career total, and a subtitle that covers the body has to
// be true of every section in it. The section says which window in its own caption.
//
// The asterisk is the other half of the same statement. "Charted history" invites the reader
// to treat these as the player's record, and they are a sample of it — one assembled by
// volunteers picking matches worth charting, which is not how a random sample is drawn. That
// belongs beside the title rather than in the notation key at the foot, because it changes
// how every number below should be read and most readers never open the key.
const CHARTED_TITLE = `<p class="tapetitle">Charted history
    <span>— their charted matches, not this one</span></p>
  <p class="covnote">* Charting is volunteer work, so these are the matches someone chose to
    chart. That weights the numbers toward big occasions rather than sampling a career
    evenly.</p>`;

// The strip's own heading. It had none while the title above sat inside it; with the title
// promoted to head the body, the one chart here without a name would have been this one.
// "Side by side" names the form rather than the contents, because the form is what tells it
// from its neighbours: every other section gives each player a column, and this is the one
// place the two are measured on a shared axis.
//
// Two rings and the pair of tour tracks, where there were six rings and a scatter. The four
// that left were not deleted — the two whose ranges no ring could show now read against the
// tour's own spread at the foot of this section, and winners-and-errors is the first bar in
// each player's column under shot-making triggers, which is where the numbers it should be
// held against already were.
function tape(da, db, mu, spread) {
  const sa = da && da.s, sb = db && db.s;
  if (!sa && !sb) return "";
  const cells = tapeRows(mu).map((r) => donut(r, sa, sb)).join("") +
    varyCell(sa, sb, spread);
  if (!cells) return "";
  return `<section class="msec">
    <h3 class="sechead">side by side</h3>
    <section class="tape">
    <div class="dnwrap">${cells}</div>
    <p class="tapenote">
      <span class="tickkey"></span> this draw's tour average ·
      <span class="segkey deep"></span> aces, within serve points won</p>
  </section></section>`;
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
  // scrolls away. A phone used to get a second pair of names in the sticky bar as well, so a
  // court-pattern section arrived carrying the same key twice over columns that had not moved.
  // Stacked, the position is genuinely gone, and each column names its own player.
  return `<section class="msec ${kind}">
    <h3 class="sechead">${title}</h3>
    ${note ? `<p class="secnote">${note}</p>` : ""}
    <div class="seccols" style="--rows:${rows}">${col(aHtml, a, "a")}${col(bHtml, b, "b")}</div>
  </section>`;
}

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
// `baseline` is what the tick stands for, and the two sections do not agree on it — a
// shallow cue is measured against the player's own norm, a deep one against the shorter
// pattern it is built out of — so it is the caller's word, not this string's.
const meterLegend = (baseline) => `<span class="meterkey">
  <span class="segkey"></span> landed <span class="segkey miss"></span> missed, out of the
  balls the cue provokes · <span class="tickkey"></span> ${baseline}</span>`;

function confidence(pa, pb) {
  const minPts = Math.min(Number(pa.s.points_charted) || 0, Number(pb.s.points_charted) || 0);
  if (minPts >= 10000) return "high";
  if (minPts >= 2000) return "moderate";
  return "low — one side is thinly charted";
}

// Deliberately small print: the shot-sequence tendencies above are this site's
// substance; the win probability is a rough, tested-and-humbled reference number.
function wpBar(a, b, wpA, conf) {
  const pa = Math.round(wpA * 100);
  return `<div class="wp wp-slim">
    <h3 class="sechead">rough pre-match number</h3>
    <div class="wp-line"><span>${esc(last(a))} ${pa}%</span>
      <div class="wp-bar"><div class="pa" style="width:${wpA * 100}%"></div></div>
      <span>${100 - pa}% ${esc(last(b))}</span></div>
    <div class="wp-note">Experimental, from charted serve and return rates only. Surface and
      recent-form adjustments were tested and don't improve it at this data resolution, so
      it stays deliberately simple. Charting confidence: ${conf}.</div>
  </div>`;
}

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
      <div>On a court-pattern drawing the tinted half is the profiled player's side.
        The dashed neutral line is the ball arriving at them, the ring is where it
        bounced, and the solid arrow in their colour is the answer they play.</div>
      <div>Court patterns name zones by the player's own hands (a lefty's FH corner
        is a righty's BH corner), so "drive into the BH corner → crosscourt BH slice"
        at <b>1.6×</b> means they answer that ball with the crosscourt slice 1.6× as
        often as the tour does from the same spot. <b>wins 52% ▲6</b> is the payoff:
        how often the point ends up theirs after that response, vs the tour playing
        the same ball.</div>
      <div>Triggers group a player's winners and unforced errors as one decision —
        an <em>attempt</em> at a finishing shot. <code>A · B</code> is the cue:
        their shot A, then the opponent's reply B. "Goes for it" is the attempt
        rate that cue provokes; "converts" is winners per attempt. A cue that
        raises attempts but sinks conversion is a trap — they take the bait.
        The first bar in each column is the same pair of numbers over every rally
        stroke the player hits, with no cue at all: their baseline, and the tick
        every bar below it is measured against.</div>
      <div>A rally stroke there is anything from the third ball of the point on, so
        serves and returns aren't in the winners + unforced errors denominator.
        Forced errors sit outside the split as well, because being beaten isn't a shot
        they chose.</div>
    </div>
  </details>`;
}

// Every decided pairing gets one of these: link straight to the chart if it exists, or
// invite the viewer to be the one who charts it — live, if the match hasn't been played
// yet, since that's exactly when Match Charting Project volunteers sign up to chart one.
// Only a slot still waiting on an opponent has nothing to invite: there's no pairing yet
// for anyone to sign up for.
function chartButton(m) {
  if (m.a.name === "TBD" || m.b.name === "TBD") return "";
  if (m.chart_id) {
    const url = `https://www.tennisabstract.com/charting/${encodeURIComponent(m.chart_id)}.html`;
    return `<a class="mchartbtn charted" href="${url}" target="_blank" rel="noopener">
      ✓ View the chart →</a>`;
  }
  return `<a class="mchartbtn uncharted" href="${CHART_GUIDE}" target="_blank" rel="noopener">
    Chart this match →</a>`;
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

// Where this match sits: event and round. It rides in the top corner beside the close
// button rather than over the names, because it is the context you read once on opening
// and then stop looking at, and the scoreboard is what the header is for. No draw here:
// the tabs behind the panel are already set to one, and a men's and a women's match never
// share a screen.
function eyebrow(t, round) {
  const event = t.completed ? `${t.name} ${t.season}` : t.name;
  return [esc(event), round ? esc(round.label) : ""].filter(Boolean).join(" · ");
}

// When. A match that hasn't been played carries its date and start time inside ESPN's
// detail string already, so printing the long date beside it just says the day twice —
// which is what the old single line did. A finished one says only the day: the state it
// is in is already on the scoreboard, in the caret against the winner's name, and a word
// for it beside the date was the same fact a second time in weaker type. ESPN's detail
// here is only ever "Final" or "Retired", so nothing else is being dropped with it.
function whenLine(m) {
  if (m.state === "in") return `<span class="live">● ${esc(m.detail || "Live")}</span>`;
  const day = matchDate(m.date);
  if (m.state !== "post") return esc(m.detail || day || "");
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
  // Event/round and when both belong to the tournament, not to either player, so they
  // share one corner instead of bracketing the scoreboard from opposite ends — freeing
  // the other corner for the one thing there is to *do* about this match: chart it, or
  // read the chart that's already there.
  return `<div class="mcorner">
      <p class="mevent">${eyebrow(t, round)}</p>
      ${when ? `<p class="mstate">${when}</p>` : ""}
    </div>
    <div class="mgrid${played ? "" : " noscore"}">
      ${side(m.a, "a")}${scoreStack(m.a, m.b)}${side(m.b, "b")}${rule}</div>
    ${chartButton(m)}`;
}

// The body, under one title: who the two players are, then where the serve goes, then the two
// of them side by side, then the pictures, then the sequences, then the small print. Every
// section shares one header across both columns, so the two players stay level however
// unevenly charted they are.
//
// The profile band leads, because everything under it is read through it: the charted counts
// are the denominator of every number in the panel, and the handedness is the key to reading
// the court drawings two sections down. It used to sit inside the side-by-side strip, which
// put all of that after the numbers it qualifies.
//
// Serve direction is then the first measurement. Every point starts with one, it is the only
// thing here a viewer can expect to see happen in the match they just tapped, and it is the
// shortest section in the panel — so it reads as an opening rather than as something to
// scroll past.
//
// The title is gated on there being a player under it. With neither side charted the body is
// the invitation to go and chart one, and "Charted history" over "Neither player has Match
// Charting history yet" heads a section with the word "history" twice and no history in it.
// The two conditions are exact opposites, so exactly one of them ever prints.
function bodyHtml(m, pa, pb, mu, gates, spread) {
  const a = m.a, b = m.b;
  const ta = trigSets(pa), tb = trigSets(pb);
  const none = !pa && !pb
    ? `<p class="nochart">Neither player has Match Charting history yet.
       <a href="${CHART_GUIDE}" target="_blank" rel="noopener">Chart a match →</a></p>` : "";
  return (pa || pb ? CHARTED_TITLE + profileBand(pa, pb, spread) : "") +
    section("serve direction", `where the first serve goes, by court side — recent
      matches counting most`, a, b,
      serveHtml(pa, gates), serveHtml(pb, gates), "text") +
    tape(pa, pb, mu, spread) + none +
    section("court patterns", `their answer to an incoming ball, × how often the tour
      plays it from the same spot${COURT_LEGEND}`, a, b,
      familyCards(pa, "rally", 3), familyCards(pb, "rally", 3), "cards") +
    section("off the return", `what they do with the returns they serve up, by return
      depth`, a, b, familyCards(pa, "ret", 2), familyCards(pb, "ret", 2), "cards") +
    section("shot-making triggers", `a lead-up that shifts how often they go for a
      finishing shot — and whether it pays${meterLegend("their rate without the cue")}`,
      a, b, ta.main, tb.main, "text") +
    section("deep patterns ⭐", `3–4 shot sequences only chartable at this player's
      coverage${meterLegend("the shorter pattern's rate")}`, a, b, ta.gold, tb.gold, "text");
}

// --- the panel as a dialog ----------------------------------------------------------
// It claims aria-modal, so it has to behave like one: focus moves in, Tab stays in, the
// draw behind stops scrolling, and closing hands focus back to the match tile you opened
// from — otherwise a keyboard lands back at the top of the page each time.
const FOCUSABLE = "a[href], button:not([disabled]), summary, [tabindex]:not([tabindex='-1'])";
let opener = null;          // the element that opened the panel, to hand focus back to
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
  if (opener && document.contains(opener)) opener.focus();
  opener = null;
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
// "Q. Halys". A breakpoint can see none of that — this used to switch at 620px, wider than
// any phone in portrait, so every phone got the fallback and none of them needed it.
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
  if (panel.hidden) opener = document.activeElement;
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
    <div id="wpslot"></div>${notationHelp()}`;

  let pa, pb, mu, gates, spread;
  try {
    [pa, pb] = await Promise.all([
      playerData(m.a.matched, t.gender),
      playerData(m.b.matched, t.gender),
    ]);
    mu = (await leagueMu())[t.gender];
    gates = (await serveGates())[t.gender] || {};
    spread = (await tourSpread())[t.gender] || {};
  } catch (e) {
    console.warn("insights db unavailable:", e);
    if (mine !== openSeq) return;
    document.getElementById("wpslot").innerHTML = "";
    const down = document.getElementById("cardslot");
    down.classList.remove("loading");
    down.innerHTML = DATA_DOWN;
    return;
  }
  if (mine !== openSeq) return;

  const wpslot = document.getElementById("wpslot");
  if (t.completed) {
    wpslot.innerHTML = "";              // result is in — no pre-match number to offer
  } else if (pa && pb) {
    const wpA = preMatchWP(
      { serve: pa.s.serve_rate, ret: pa.s.return_rate },
      { serve: pb.s.serve_rate, ret: pb.s.return_rate }, mu, t.best_of);
    wpslot.innerHTML = wpBar(m.a.name, m.b.name, wpA, confidence(pa, pb));
  } else {
    wpslot.innerHTML = `<p class="wp-note">A win probability needs charting history for both players.</p>`;
  }
  const slot = document.getElementById("cardslot");
  slot.classList.remove("loading");
  slot.innerHTML = bodyHtml(m, pa, pb, mu, gates, spread);
}
