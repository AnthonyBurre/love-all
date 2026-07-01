// The matchup drawer: experimental pre-match win probability + a card per player,
// all queried from insights.duckdb via DuckDB-WASM.
import { query, leagueMu } from "./db.js";
import { preMatchWP } from "./winprob.js";

const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const last = (name) => String(name || "").split(" ").slice(-1)[0];

async function playerData(name, gender) {
  if (!name) return null;
  const s = await query("SELECT * FROM player_summary WHERE player = ? AND gender = ?", [name, gender]);
  if (!s.length) return null;
  const p = await query(
    "SELECT kind, context, rate, lift FROM player_patterns WHERE player = ? AND gender = ? ORDER BY rate DESC",
    [name, gender]);
  return { s: s[0], patterns: p };
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
  return `<div class="pat ${cls}">after <code>${esc(p.context)}</code> — ${what} ${Math.round(p.rate * 100)}%</div>`;
}

function playerCard(side, d) {
  const flag = side.country ? `<span class="flag">${esc(side.country)}</span>` : "";
  if (!d) {
    return `<div class="pcard"><h4>${esc(side.name || "TBD")}</h4>${flag}
      <p class="uncharted">No Match Charting history yet.
      <a href="https://github.com/JeffSackmann/tennis_MatchChartingProject" target="_blank" rel="noopener">Chart a match →</a></p></div>`;
  }
  const s = d.s;
  const green = d.patterns.find((p) => p.kind === "green");
  const trouble = d.patterns.find((p) => p.kind === "trouble");
  return `<div class="pcard">
    <h4>${esc(side.name)}</h4>${flag}
    ${s.archetype ? `<div class="arch">${esc(s.archetype)}</div>` : ""}
    <div class="stat"><span class="k">shot quality:</span> ${ratingLabel(s.class_rel_z)}</div>
    <div class="stat"><span class="k">style:</span> ${s.bits != null ? predictabilityLabel(s.bits) + ` (${s.bits.toFixed(1)} bits)` : "—"}</div>
    <div class="stat"><span class="k">charted:</span> ${s.matches_charted} matches</div>
    ${green ? patLine(green) : ""}
    ${trouble ? patLine(trouble) : ""}
  </div>`;
}

function wpBar(a, b, wpA) {
  const pa = Math.round(wpA * 100);
  return `<div class="wp">
    <div class="wp-bar">
      <div class="pa" style="width:${wpA * 100}%">${esc(last(a))} ${pa}%</div>
      <div class="pb" style="width:${(1 - wpA) * 100}%">${100 - pa}% ${esc(last(b))}</div>
    </div>
    <div class="wp-note"><b>Experimental</b> pre-match model from charted serve+return only —
      no surface, form, or injuries. Confidence tracks how much both players are charted.</div>
  </div>`;
}

export async function openMatchup(m, t) {
  document.getElementById("matchup").hidden = false;
  document.getElementById("scrim").hidden = false;
  const body = document.getElementById("matchupBody");
  const round = t.rounds.find((r) => r.matches.some((x) => x.id === m.id));
  body.innerHTML = `<h2 class="mh">${esc(m.a.name)} <small>vs</small> ${esc(m.b.name)}</h2>
    <div class="stat">${esc(t.name)} · ${t.gender === "M" ? "Men" : "Women"}${round ? " · " + esc(round.label) : ""}</div>
    <div id="wpslot"></div><div class="cards" id="cardslot">Loading…</div>`;

  const [pa, pb] = await Promise.all([
    playerData(m.a.matched, t.gender),
    playerData(m.b.matched, t.gender),
  ]);

  const wpslot = document.getElementById("wpslot");
  if (pa && pb) {
    const mu = (await leagueMu())[t.gender];
    const wpA = preMatchWP(
      { serve: pa.s.serve_rate, ret: pa.s.return_rate },
      { serve: pb.s.serve_rate, ret: pb.s.return_rate }, mu, t.best_of);
    wpslot.innerHTML = wpBar(m.a.name, m.b.name, wpA);
  } else {
    wpslot.innerHTML = `<p class="wp-note">A win probability needs charting history for both players.</p>`;
  }
  document.getElementById("cardslot").innerHTML = playerCard(m.a, pa) + playerCard(m.b, pb);
}
