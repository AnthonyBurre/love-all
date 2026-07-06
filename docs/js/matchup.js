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
  const p = await query(
    "SELECT kind, context, rate, lift FROM player_patterns WHERE player = ? AND gender = ? ORDER BY rate DESC",
    [name, gender]);
  let triggers = [];
  try {
    triggers = await query(
      "SELECT tag, context, att_rate, att_lift, conversion, conv_delta, n " +
      "FROM player_triggers WHERE player = ? AND gender = ?", [name, gender]);
  } catch (e) { /* insights db predates player_triggers — patterns fallback below */ }
  return { s: s[0], patterns: p, triggers };
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

function patLine(p) {
  const cls = p.kind === "green" ? "green" : "trouble";
  const what = p.kind === "green" ? "goes for a winner" : "tends to err";
  return `<div class="pat ${cls}">after <code>${esc(p.context)}</code> — ${what} ${Math.round(p.rate * 100)}% <span class="lift">(${Number(p.lift).toFixed(1)}× their norm)</span></div>`;
}

// One decision, two outcomes: a green light converts, a trap is taken bait.
function trigLine(t) {
  const ctx = `after <code>${esc(t.context)}</code>`;
  const lift = `${Number(t.att_lift).toFixed(1)}×`;
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
  // Shot-making triggers (one decision + conversion) when the insights db has
  // them; the older two-book winner/error patterns otherwise.
  let tendencies = "";
  if (d.triggers.length) {
    const greens = d.triggers.filter((t) => t.tag === "green")
      .sort((a, b) => b.att_lift - a.att_lift).slice(0, 3);
    const traps = d.triggers.filter((t) => t.tag === "trap")
      .sort((a, b) => a.conv_delta - b.conv_delta).slice(0, 2);
    const unbaitable = s.n_traps != null && Number(s.n_traps) === 0
      ? `<div class="pat immune">no trap sequences — every lead-up that raises their
         aggression also meets their usual conversion</div>` : "";
    tendencies = `<div class="phead">shot-making triggers</div>` +
      [...greens, ...traps].map(trigLine).join("") + unbaitable;
  } else {
    const pats = [...d.patterns.filter((p) => p.kind === "green").slice(0, 3),
                  ...d.patterns.filter((p) => p.kind === "trouble").slice(0, 3)];
    tendencies = pats.length
      ? `<div class="phead">finishing / breakdown</div>` + pats.map(patLine).join("") : "";
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
    <div class="cards" id="cardslot">Loading…</div><div id="wpslot"></div>`;

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
