// The matchup drawer: experimental pre-match win probability + a card per player,
// all queried from insights.duckdb via DuckDB-WASM.
import { query, leagueMu, serveGates } from "./db.js";
import { preMatchWP } from "./winprob.js";
import { patternSvg, pairSvg, shotLine } from "./court.js";

const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const CHART_GUIDE =
  "https://www.tennisabstract.com/blog/2015/09/23/the-match-charting-project-quick-start-guide/";
const last = (name) => String(name || "").split(" ").slice(-1)[0];
const pct = (x) => (x * 100).toFixed(1) + "%";

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
  } catch (e) { /* stale insights db: show the card without serve decisions */ }
  return { s: s[0], triggers, patterns, serve };
}

// The qualitative reading of a number the comparison strip already prints, so each of
// these is the word only — the strip supplies the digits next to it.
function predictabilityLabel(bits) {
  if (bits == null) return "";
  if (bits >= 3.6) return "unusually varied";
  if (bits <= 2.9) return "fairly patterned";
  return "average variety";
}

function ratingLabel(z) {
  if (z == null) return "";
  if (z <= -0.5) return "beats their archetype";
  if (z >= 0.5) return "below their archetype";
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
  const caption = `<p class="srvwin">${win ? `last ${win} charted matches` : "recent matches"}${
    span ? ` (${span})` : ""}</p>`;

  // A career average would be a different number for the players who moved, so say so
  // rather than quietly showing only the recent one.
  let moved = "";
  const big = sorted
    .filter((r) => Number(r.drift_ratio) >= 1.5 && Math.abs(r.t - r.career_t) >= 0.05)
    .sort((a, b) => Math.abs(b.t - b.career_t) - Math.abs(a.t - a.career_t))[0];
  if (big) {
    moved = `<p class="tnum">${big.side} court: T share ${
      big.t > big.career_t ? "up from" : "down from"} <b>${pct(big.career_t)}</b>
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
      test; most players show nothing here">on break points, <b>${pts} points</b> ${
      delta > 0 ? "wider" : "less wide"} than their own norm</p>`;
  }
  return `<div class="srv">
    <div class="srvcourt">${sorted.map(box).join("")}</div>
    ${caption}${moved}${bp}</div>`;
}

// How context-driven is the go-for-it decision (σ from the shot_triggers experiment)?
function selectionLabel(sigma) {
  if (sigma == null) return "";
  if (sigma >= 0.06) return "highly cue-driven";
  if (sigma <= 0.025) return "pattern-immune";
  return "selective";
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

// A player's triggers, split the way the panel shows them: the shallow green lights and
// traps together, then the deep sequences, then the note that earns its place by absence.
function trigSets(d) {
  if (!d || !d.triggers.length) return { main: "", gold: "" };
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
    main: [...greens, ...traps].map(trigLine).join("") + immune,
    gold: gold.map(trigLine).join(""),
  };
}

// --- the comparison strip -----------------------------------------------------------
// Both players' headline numbers on one shared axis, bars growing outward from a centre
// line, so a difference reads as a shape instead of as arithmetic between two columns
// that have drifted a screen apart.
//
// `lo`/`hi` is a *drawing* domain — a scale picked to spread tour-realistic values across
// the bar, not a claim that the metric is bounded there; anything outside is clamped.
// `avg` puts a tick on the bar at the tour reference where one exists. `better` says which
// direction wins, and is deliberately absent where neither does: variety and
// cue-sensitivity are styles, not scores, so neither player "leads" them.
const clamp01 = (x) => Math.max(0, Math.min(1, x));
const num = (v) => (v == null ? null : Number(v));

function tapeRows(mu) {
  return [
    { k: "serve_rate", label: "serve points won", lo: 0.50, hi: 0.80, better: "hi",
      avg: mu, fmt: pct },
    { k: "return_rate", label: "return points won", lo: 0.18, hi: 0.48, better: "hi",
      avg: 1 - mu, fmt: pct },
    // The two halves of one decision, drawn as one bar: its length is how often they
    // finish a rally ball themselves, and where it changes colour is how that turned
    // out. "Goes for it" is the right phrase next to a cue that provokes it, but as a
    // bare statistic it names the framing rather than the measurement, so up here the
    // row says what it counts.
    // The denominator rides in the shared key rather than in both subs: it is the same
    // sentence for each player, and repeated per side it wraps a phone column to four
    // lines and buries the one number that actually differs.
    { k: "trig_att_rate", label: "winners + unforced errors, per rally stroke",
      lo: 0.05, hi: 0.32, better: null, fmt: pct,
      sub: (s) => s.trig_conversion == null ? ""
        : `${Math.round(s.trig_conversion * 100)}% winners`,
      parts: (s) => s.trig_conversion == null ? null
        : [{ f: s.trig_conversion }, { f: 1 - s.trig_conversion, cls: "miss" }] },
    { k: "accuracy", label: "shot quality", lo: 30, hi: 90, better: "hi",
      fmt: (v) => `${v.toFixed(0)}/100`, sub: (s) => ratingLabel(s.class_rel_z) },
    { k: "sigma", label: "shot selection", lo: 0, hi: 0.09, better: null,
      fmt: (v) => `σ ${(v * 100).toFixed(1)}pp`, sub: (s) => selectionLabel(s.sigma) },
    { k: "bits", label: "variety", lo: 2.2, hi: 4.4, better: null,
      fmt: (v) => `${v.toFixed(1)} bits`, sub: (s) => predictabilityLabel(s.bits) },
  ];
}

function tapeRow(r, sa, sb) {
  const va = sa ? num(sa[r.k]) : null;
  const vb = sb ? num(sb[r.k]) : null;
  if (va == null && vb == null) return "";
  const lead = r.better && va != null && vb != null && va !== vb
    ? ((va > vb) === (r.better === "hi") ? "a" : "b") : "";
  const at = (v) => (clamp01((v - r.lo) / (r.hi - r.lo)) * 100).toFixed(1) + "%";
  // A bar is one block unless the metric splits it: then the segments are shares of the
  // bar's own length, ordered outward from the centre line so both players' first
  // segments meet in the middle and stay directly comparable.
  const bar = (v, s, side) => {
    if (v == null) return `<div class="tbar ${side}"></div>`;
    const tick = r.avg == null ? "" :
      `<u style="${side === "a" ? "right" : "left"}:${at(r.avg)}" title="tour average"></u>`;
    const segs = (r.parts && s ? r.parts(s) : null) || [{ f: 1 }];
    const fill = segs.map((g) =>
      `<span class="${g.cls || ""}" style="flex:${g.f}"></span>`).join("");
    return `<div class="tbar ${side}"><i style="width:${at(v)}">${fill}</i>${tick}</div>`;
  };
  const val = (v, s, side) => {
    if (v == null) return `<div class="tval ${side}">—</div>`;
    const sub = r.sub ? r.sub(s) : "";
    return `<div class="tval ${side}${lead === side ? " lead" : ""}">${r.fmt(v)}` +
      (sub ? `<span class="tsub">${esc(sub)}</span>` : "") + `</div>`;
  };
  return `<div class="taperow"><p class="tkey">${esc(r.label)}</p>
    <div class="tbars">${val(va, sa, "a")}${bar(va, sa, "a")}${bar(vb, sb, "b")}${val(vb, sb, "b")}</div>
  </div>`;
}

// What the charted numbers below rest on: the player's style label and how much of them
// exists in the data. No name and no flag — the scroll-locked match header above carries
// those, and this side of the panel is the same player in the same position. The two
// player colours (--a / --b) are theme-independent and are declared once, by the split
// rule under that header: its left half is player A, its right half player B, and those
// colours then run through the strip's bars, the column rules and the ball paths.
function tapeWho(d, tag) {
  // "charted:" is stated rather than implied: these counts are how much of the player
  // exists in the data, not how much tennis they have played, and every number in the
  // strip below rests on them.
  // An uncharted player is the site's whole invitation, so the ask sits at the top of
  // their side rather than only in the empty column below it.
  const meta = d
    ? (d.s.archetype ? `<span class="tarch">${esc(d.s.archetype)}</span>` : "") +
      `<span class="tcharted">charted: ${d.s.matches_charted} matches ·
       ${Number(d.s.points_charted).toLocaleString()} points</span>`
    : `<span class="tcharted">not charted yet —
       <a href="${CHART_GUIDE}" target="_blank" rel="noopener">chart a match →</a></span>`;
  return `<div class="twho ${tag}"><p class="tmeta">${meta}</p></div>`;
}

function tape(da, db, mu) {
  const sa = da && da.s, sb = db && db.s;
  if (!sa && !sb) return "";
  // The header above never says "this match" — it can't, everything below it is
  // career-wide — so the body has to say what it is itself, first thing, before any of
  // its numbers do.
  //
  // The title sits outside the strip, not in it. Inside, a bordered box drew a line
  // around what it covered, and the caveat looked like it stopped at the strip's own
  // numbers — while the court patterns and the triggers under it, which are career
  // totals in exactly the same way, read as being about the match just named overhead.
  // Out here it heads the whole body, which is the scope it actually has.
  return `<p class="tapetitle">Charted history <span>— career totals, not this match</span></p>
    <section class="tape">
    <div class="tapehead">${tapeWho(da, "a")}${tapeWho(db, "b")}</div>
    ${tapeRows(mu).map((r) => tapeRow(r, sa, sb)).join("")}
    <p class="tapenote"><span class="tickkey"></span> this draw's tour average ·
      <span class="segkey"></span> landed <span class="segkey miss"></span> missed, on the
      winners + errors bar</p>
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
  // Two ways to say whose column is whose, one per layout. Side by side, the names ride
  // in the sticky bar over the columns they head, because a line inside the columns
  // scrolls under that bar and is gone by the second card. Stacked, they can't — one bar
  // can't head two columns that aren't there — so each column carries its own.
  const who = (side, tag) =>
    `<span class="sw ${tag}"><span class="tdot ${tag}"></span>${esc(last(side.name) || "TBD")}</span>`;
  return `<section class="msec ${kind}">
    <h3 class="sechead">${title}
      <span class="secwho">${who(a, "a")}${who(b, "b")}</span></h3>
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
        It's the same pair of numbers the strip up top splits into one bar, read
        per cue instead of over all their rally balls.</div>
      <div>On that strip, a rally stroke is anything from the third ball of the point
        on, so serves and returns aren't in the winners + unforced errors denominator.
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

// The body, in reading order: the headline numbers side by side, then the pictures, then
// the sequences, then the small print. Every section below the strip shares one header
// across both columns, so the two players stay level however unevenly charted they are.
function bodyHtml(m, pa, pb, mu, gates) {
  const a = m.a, b = m.b;
  const ta = trigSets(pa), tb = trigSets(pb);
  const none = !pa && !pb
    ? `<p class="nochart">Neither player has Match Charting history yet.
       <a href="${CHART_GUIDE}" target="_blank" rel="noopener">Chart a match →</a></p>` : "";
  return tape(pa, pb, mu) + none +
    section("serve decisions", `where the first serve goes, by court side — recent
      matches counting most`, a, b,
      serveHtml(pa, gates), serveHtml(pb, gates), "text") +
    section("court patterns", `their answer to an incoming ball, × how often the tour
      plays it from the same spot${COURT_LEGEND}`, a, b,
      familyCards(pa, "rally", 3), familyCards(pb, "rally", 3), "cards") +
    section("off the return", `what they do with the returns they serve up, by return
      depth`, a, b, familyCards(pa, "ret", 2), familyCards(pb, "ret", 2), "cards") +
    section("shot-making triggers", `a lead-up that shifts how often they go for a
      finishing shot — and whether it pays`, a, b, ta.main, tb.main, "text") +
    section("deep patterns ⭐", `3–4 shot sequences only chartable at this player's
      coverage`, a, b, ta.gold, tb.gold, "text");
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
function onBodyScroll() {
  const panel = document.getElementById("matchup");
  const t = document.getElementById("matchupBody").scrollTop;
  if (t > 24) panel.classList.add("cond");
  else if (t < 8) panel.classList.remove("cond");
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
  body.innerHTML = `<div id="cardslot" class="loading">Loading…</div>
    <div id="wpslot"></div>${notationHelp()}`;

  let pa, pb, mu, gates;
  try {
    [pa, pb] = await Promise.all([
      playerData(m.a.matched, t.gender),
      playerData(m.b.matched, t.gender),
    ]);
    mu = (await leagueMu())[t.gender];
    gates = (await serveGates())[t.gender] || {};
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
  slot.innerHTML = bodyHtml(m, pa, pb, mu, gates);
}
