// The matchup drawer: experimental pre-match win probability + a card per player,
// all queried from insights.duckdb via DuckDB-WASM.
import { query, leagueMu } from "./db.js";
import { preMatchWP } from "./winprob.js";

const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const last = (name) => String(name || "").split(" ").slice(-1)[0];
const pct = (x) => (x * 100).toFixed(1) + "%";

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
  return { s: s[0], triggers };
}

function predictabilityLabel(bits) {
  if (bits == null) return "";
  if (bits >= 3.6) return "unusually varied";
  if (bits <= 2.9) return "fairly patterned";
  return "average variety";
}

function ratingLabel(z) {
  if (z == null) return "not enough charted shots";
  if (z <= -0.5) return `beats their archetype (z ${z.toFixed(1)})`;
  if (z >= 0.5) return `below their archetype (z +${z.toFixed(1)})`;
  return `typical for their style (z ${z.toFixed(1)})`;
}

// One decision, two outcomes: a green light converts, a trap is taken bait.
function trigLine(t) {
  const ctx = `after <code>${esc(t.context)}</code>`;
  const lift = `${Number(t.att_lift).toFixed(1)}×`;
  if (Number(t.depth) > 2) {
    // Gold: a 3-4 shot sequence that beats its own shorter pattern and replicates
    // across halves of the player's data — only the hugely-charted earn these.
    const kind = t.tag === "trap"
      ? `but converts only ${Math.round(t.conversion * 100)}% ⚠`
      : `and converts ${Math.round(t.conversion * 100)}%`;
    return `<div class="pat gold" title="deep pattern: only visible with this player's huge charted history">${ctx}
      — goes for it ${Math.round(t.att_rate * 100)}% (${lift} the shorter pattern) ${kind}
      <span class="lift">(n=${Number(t.n)})</span></div>`;
  }
  if (t.tag === "green") {
    return `<div class="pat green">${ctx} — goes for it ${Math.round(t.att_rate * 100)}% (${lift})
      and converts ${Math.round(t.conversion * 100)}% <span class="lift">(n=${Number(t.n)})</span></div>`;
  }
  return `<div class="pat bait">${ctx} — takes the bait (${lift} their attempts) but converts
    only ${Math.round(t.conversion * 100)}% <span class="lift">(${Math.round(t.conv_delta * 100)} vs their norm, n=${Number(t.n)})</span></div>`;
}

// How context-driven is the go-for-it decision (σ from the shot_triggers experiment)?
function selectionLabel(sigma) {
  if (sigma == null) return null;
  if (sigma >= 0.06) return `highly cue-driven (σ ${(sigma * 100).toFixed(1)}pp)`;
  if (sigma <= 0.025) return `pattern-immune (σ ${(sigma * 100).toFixed(1)}pp)`;
  return `selective (σ ${(sigma * 100).toFixed(1)}pp)`;
}

// serve/return rate with a ▲/▼ against the tour average (mu = mean serve-win rate).
function rateStat(label, rate, avg) {
  if (rate == null) return "";
  const d = rate - avg;
  const arrow = Math.abs(d) < 0.005 ? "" :
    `<span class="${d > 0 ? "up" : "down"}">${d > 0 ? "▲" : "▼"} ${(Math.abs(d) * 100).toFixed(1)}</span>`;
  return `<div class="stat"><span class="k">${label}:</span> ${pct(rate)} ${arrow}</div>`;
}

function signatures(s) {
  if (!s.signatures) return "";
  const sigs = String(s.signatures).split("; ").slice(0, 2)
    .map((x) => `<code>${esc(x)}</code>`).join(" ");
  return `<div class="phead">signature sequences</div><div class="sig">${sigs}</div>`;
}

function playerCard(side, d, mu, gender) {
  const flag = side.country ? `<span class="flag">${esc(side.country)}</span>` : "";
  if (!d) {
    return `<div class="pcard"><h4>${esc(side.name || "TBD")}</h4>${flag}
      <p class="uncharted">No Match Charting history yet.
      <a href="https://github.com/JeffSackmann/tennis_MatchChartingProject" target="_blank" rel="noopener">Chart a match →</a></p></div>`;
  }
  const s = d.s;
  let tendencies = "";
  if (d.triggers.length) {
    const shallow = d.triggers.filter((t) => !(Number(t.depth) > 2));
    const greens = shallow.filter((t) => t.tag === "green")
      .sort((a, b) => b.att_lift - a.att_lift).slice(0, 3);
    const traps = shallow.filter((t) => t.tag === "trap")
      .sort((a, b) => a.conv_delta - b.conv_delta).slice(0, 2);
    const gold = d.triggers.filter((t) => Number(t.depth) > 2)
      .sort((a, b) => b.att_lift - a.att_lift).slice(0, 3);
    const unbaitable = s.n_traps != null && Number(s.n_traps) === 0
      ? `<div class="pat immune">no trap sequences — every lead-up that raises their
         aggression also meets their usual conversion</div>` : "";
    tendencies = `<div class="phead">shot-making triggers</div>` +
      [...greens, ...traps].map(trigLine).join("") + unbaitable +
      (gold.length
        ? `<div class="phead">deep patterns ⭐ <span class="phead-note">3–4 shot
           sequences only chartable at this player's coverage</span></div>` +
          gold.map(trigLine).join("")
        : "");
  }
  const sel = selectionLabel(s.sigma);
  const trig = s.trig_att_rate != null
    ? `<div class="stat"><span class="k">goes for it:</span> ${pct(s.trig_att_rate)} of strokes · converts ${Math.round(s.trig_conversion * 100)}%</div>` : "";
  return `<div class="pcard">
    <h4>${esc(side.name)}</h4>${flag}
    ${s.archetype ? `<div class="arch">${esc(s.archetype)}</div>` : ""}
    ${signatures(s)}
    ${tendencies}
    <div class="phead">the numbers</div>
    ${rateStat("serve pts won", s.serve_rate, mu)}
    ${rateStat("return pts won", s.return_rate, 1 - mu)}
    ${trig}
    ${sel ? `<div class="stat"><span class="k">shot selection:</span> ${sel}</div>` : ""}
    <div class="stat"><span class="k">shot quality:</span> ${ratingLabel(s.class_rel_z)}${s.accuracy != null ? ` · ${Number(s.accuracy).toFixed(0)}/100` : ""}</div>
    <div class="stat"><span class="k">style:</span> ${s.bits != null ? predictabilityLabel(s.bits) + ` (${s.bits.toFixed(1)} bits)` : "—"}</div>
    <div class="stat"><span class="k">charted:</span> ${s.matches_charted} matches · ${Number(s.points_charted).toLocaleString()} points</div>
  </div>`;
}

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
    <div class="phead">rough pre-match number</div>
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
    <line x1="75" y1="166" x2="40" y2="66" class="ct-shot"/>
    <line x1="75" y1="166" x2="75" y2="66" class="ct-shot faint"/>
    <line x1="75" y1="166" x2="110" y2="66" class="ct-shot faint"/>
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
    <line x1="108" y1="167" x2="30" y2="64" class="ct-shot faint"/>
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
      <div><code>A→B (3.6×)</code> in signatures: the player follows shot A with
        shot B 3.6× as often as the tour; <code>A · B</code> in triggers: their
        shot A, then the opponent's reply B, then the stroke being measured.</div>
    </div>
  </details>`;
}

function scoreline(m) {
  const sets = (s) => (s.sets || []).map((x) => (x == null ? "" : Math.trunc(x))).join(" ");
  const a = sets(m.a), b = sets(m.b);
  return a || b ? `<span class="score">${esc(a)} — ${esc(b)}</span>` : "";
}

function stateLine(m, t, round) {
  const where = `${esc(t.name)} · ${t.gender === "M" ? "Men" : "Women"}${round ? " · " + esc(round.label) : ""}`;
  if (m.state === "in") return `${where} · <span class="live">● ${esc(m.detail || "Live")}</span>`;
  if (m.state === "post") return `${where} · ${esc(m.detail || "Final")}`;
  return m.detail ? `${where} · ${esc(m.detail)}` : where;
}

export async function openMatchup(m, t) {
  document.getElementById("matchup").hidden = false;
  document.getElementById("scrim").hidden = false;
  const body = document.getElementById("matchupBody");
  const round = t.rounds.find((r) => r.matches.some((x) => x.id === m.id));
  body.innerHTML = `<h2 class="mh">${esc(m.a.name)} <small>vs</small> ${esc(m.b.name)} ${scoreline(m)}</h2>
    <div class="mstate">${stateLine(m, t, round)}</div>
    <div class="cards" id="cardslot">Loading…</div>${notationHelp()}<div id="wpslot"></div>`;

  const [pa, pb] = await Promise.all([
    playerData(m.a.matched, t.gender),
    playerData(m.b.matched, t.gender),
  ]);

  const mu = (await leagueMu())[t.gender];
  const wpslot = document.getElementById("wpslot");
  if (pa && pb) {
    const wpA = preMatchWP(
      { serve: pa.s.serve_rate, ret: pa.s.return_rate },
      { serve: pb.s.serve_rate, ret: pb.s.return_rate }, mu, t.best_of);
    wpslot.innerHTML = wpBar(m.a.name, m.b.name, wpA, confidence(pa, pb));
  } else {
    wpslot.innerHTML = `<p class="wp-note">A win probability needs charting history for both players.</p>`;
  }
  document.getElementById("cardslot").innerHTML =
    playerCard(m.a, pa, mu, t.gender) + playerCard(m.b, pb, mu, t.gender);
}
