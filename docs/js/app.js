// Orchestration: load the brackets feed, build tabs, theme the page to the
// selected tournament, render the bracket into #bracket (quarter view by default,
// full draw on demand, round list on phones), and wire the matchup drawer.
import { renderTree, renderQuarters, renderRoundList, currentRound } from "./bracket.js";
import { openMatchup, closeMatchup } from "./matchup.js";
import { query } from "./db.js";

let data = null;
// "G|player" -> charted match count, or null while that is genuinely unknown — which is every
// load until the insights database answers, and the whole of one where it never does. An empty
// object would have been a table saying every player is uncharted; see matchTier in bracket.js.
let cov = null;
let covState = "loading";       // "loading" | "ready" | "down"
// view: null = auto — full draw early in an event, by-quarter from the round of 16 on.
// section: which slice of the draw is unfolded below the quarter view's chip row. How many
// there are depends on the draw — eight sixteenths on a slam, four quarters on a 32 — so it
// resets when you change event or tour rather than carrying an out-of-range index across.
const sel = { key: null, gender: null, view: null, section: 0, round: null };

const $ = (id) => document.getElementById(id);

// A tournament group spans its two draws (men/women). Completed events are keyed and
// labelled by year, so Wimbledon 2025 and a live Wimbledon never collide in the dropdown.
const SEP = "␟";
const gkey = (t) => (t.completed ? `${t.name}${SEP}${t.season}` : t.name);
// What to call an event on screen. The feed's own name is the title sponsor's — "National
// Bank Open presented by Rogers" — which is not what anyone calls the thing, so lead with
// the name the calendar says people use and leave the sponsor's to the line under the
// title. Keyed identity stays on the feed name: it's the stable one, it's what pairs the
// two draws of an event, and a calendar that can't place an event doesn't change it.
const ename = (t) => (t.event || {}).common_name || t.name;
const glabel = (t) => (t.completed ? `${ename(t)} ${t.season}` : ename(t));

// Season/tournament theme: slams get their own palette, everything below them follows its
// surface. Keyed off the venue city, since the feed's event name is a sponsor's ("HSBC
// Championships" is Queen's, on grass) and often has no city in it at all. Slams are
// matched on name first — their city is the one that would mislead ("London", "Paris").
const CLAY = ["madrid", "rome", "monte", "hamburg", "charleston", "barcelona", "munich",
  "rio de janeiro", "stuttgart", "strasbourg"];
const GRASS = ["london", "halle", "eastbourne", "bad homburg", "berlin",
  "'s-hertogenbosch"];
const AUS = ["melbourne", "brisbane", "adelaide"];
function themeFor(t) {
  const name = (t.name || "").toLowerCase();
  if (name.includes("wimbledon")) return "";       // grass = the default palette
  if (name.includes("australian open")) return "aus-hard";
  if (name.includes("roland garros") || name.includes("french open")) return "clay";
  const c = (t.city || t.name || "").toLowerCase();
  if (CLAY.some((x) => c.includes(x))) return "clay";
  if (GRASS.some((x) => c.includes(x))) return "";
  if (AUS.some((x) => c.includes(x))) return "aus-hard";
  return "us-hard";                                // everything else is a hard court
}

async function main() {
  try {
    data = await (await fetch("./data/brackets.json")).json();
  } catch (e) {
    $("status").textContent = "Could not load the current draws.";
    return;
  }
  $("updated").textContent =
    "Updated " + new Date(data.updated).toLocaleString([], { dateStyle: "medium", timeStyle: "short" });
  if (!data.tournaments.length) {
    $("status").textContent = "No Grand Slam, 1000 or 500 draws are live right now. Check back during an event.";
    return;
  }
  const first = groups()[0];
  sel.key = first.key;
  sel.gender = gendersFor(first.key)[0];
  $("controls").hidden = false;
  buildTabs();
  render();
  loadCoverage();               // shades the match tiers when the WASM db is ready
  wireDrawer();
  let raf = null;               // connectors are position-dependent: relayout on resize
  window.addEventListener("resize", () => {
    cancelAnimationFrame(raf);
    raf = requestAnimationFrame(render);
  });
}

// Distinct tournament groups: live events first, then completed ones most-recent-first.
function groups() {
  const seen = new Map();
  for (const t of data.tournaments) {
    const k = gkey(t);
    if (!seen.has(k)) {
      seen.set(k, { key: k, label: glabel(t), completed: !!t.completed, season: t.season || 9999 });
    }
  }
  return [...seen.values()].sort(
    (a, b) => (a.completed - b.completed) || (b.season - a.season) || a.label.localeCompare(b.label));
}

function gendersFor(key) {
  return data.tournaments.filter((t) => gkey(t) === key).map((t) => t.gender);
}

function pick() {
  return (
    data.tournaments.find((t) => gkey(t) === sel.key && t.gender === sel.gender) ||
    data.tournaments.find((t) => gkey(t) === sel.key) ||
    data.tournaments[0]
  );
}

// A draw can be sliced this way only when its bracket ordering is trustworthy — a live
// fixture-backed draw or a finished one (both fully linked) — and its shape is a clean
// power of two (each round half the size of the one before, down to a 1-match final,
// so the round of 16 is truly 8 matches). Draws with byes — most 1000s, and the 500s whose
// women's field is 28 or 30 — aren't that shape, and fall back to the full draw.
function quarterable(t) {
  if (!(t.slotted || t.completed)) return false;
  const r = t.rounds;
  if (r.length < 4 || r[r.length - 1].matches.length !== 1) return false;
  return r.every((rd, i) => i === 0 || r[i - 1].matches.length === rd.matches.length * 2);
}

function seg(container, items, active, onPick) {
  container.innerHTML = "";
  for (const [val, label, title] of items) {
    const b = document.createElement("button");
    if (typeof label === "string") b.textContent = label;
    else b.append(label);
    if (title) { b.title = title; b.setAttribute("aria-label", title); }
    if (val === active) b.className = "on";
    b.onclick = () => onPick(val);
    container.appendChild(b);
  }
}

// Wordless view-toggle glyphs: stacked horizontal bars for the top-down quarter
// view, vertical bars for the full draw's side-by-side round columns.
// Square ends, no rx — a rounded cap is the one thing the rest of the page no
// longer has, and at 14px it is most of what the glyph is.
function barsIcon(vertical) {
  const s = document.createElement("span");
  s.className = "ico";
  s.innerHTML = vertical
    ? `<svg viewBox="0 0 14 14" width="14" height="14" aria-hidden="true"><rect x="1.2" y="1" width="2.8" height="12"/><rect x="5.6" y="1" width="2.8" height="12"/><rect x="10" y="1" width="2.8" height="12"/></svg>`
    : `<svg viewBox="0 0 14 14" width="14" height="14" aria-hidden="true"><rect x="1" y="1.2" width="12" height="2.8"/><rect x="1" y="5.6" width="12" height="2.8"/><rect x="1" y="10" width="12" height="2.8"/></svg>`;
  return s;
}

// Which view to show: an explicit toggle click wins; otherwise the full draw while
// an event is in its early rounds (the quarter view is mostly undecided ghosts
// then), switching to by-quarter once the round of 16 is the current round — which
// also covers finished draws.
function viewFor(t) {
  if (sel.view) return sel.view;
  return currentRound(t.rounds) >= t.rounds.length - 4 ? "quarters" : "full";
}

function buildTabs() {
  // Tournament picker is a dropdown: the current/upcoming event sits on top (its released
  // draw is what you land on), with finished events following underneath to look back on.
  const selEl = $("tourSelect");
  selEl.innerHTML = "";
  const gs = groups();
  const option = (grp) => {
    const o = document.createElement("option");
    o.value = grp.key;
    o.textContent = grp.label;
    if (grp.key === sel.key) o.selected = true;
    return o;
  };
  for (const grp of gs.filter((g) => !g.completed)) selEl.appendChild(option(grp));
  const past = gs.filter((g) => g.completed);
  if (past.length) {
    const og = document.createElement("optgroup");
    og.label = "Past events";
    for (const grp of past) og.appendChild(option(grp));
    selEl.appendChild(og);
  }
  selEl.value = sel.key;
  selEl.onchange = () => {
    sel.key = selEl.value;
    if (!gendersFor(sel.key).includes(sel.gender)) sel.gender = gendersFor(sel.key)[0];
    sel.round = null;
    sel.section = 0;
    sel.view = null;            // back to the per-event default
    buildTabs();
    render();
  };

  const g = gendersFor(sel.key);
  seg($("genderTabs"), g.map((x) => [x, x === "M" ? "Men" : "Women"]), sel.gender, (x) => {
    sel.gender = x;
    sel.round = null;
    sel.section = 0;            // the two draws can differ in size, so in section count
    buildTabs();
    render();
  });
  $("genderTabs").style.display = g.length > 1 ? "" : "none";

  // Quarter view needs trustworthy slot ordering (fixture-backed or finished draws).
  // Whether the toggle is *shown* is render()'s call rather than this one's: visibility also
  // depends on the viewport (phones have no quarter view), and every path through here ends
  // in a render(), so setting it here too only made two places to keep in agreement.
  const t = pick();
  const q = quarterable(t);
  seg($("viewTabs"), [
    ["quarters", barsIcon(false), "Slices"],
    ["full", barsIcon(true), "Full draw"],
  ], q ? viewFor(t) : "full", (v) => {
    sel.view = v;
    sel.round = null;
    buildTabs();
    render();
  });
}

// The size of the field, counted off the draw itself rather than read from the calendar —
// the calendar's figure is a hand-typed one that has been wrong (it claimed 48 for a
// Washington draw that was 32). A round-1 slot is two players unless it is a bye, so a 96
// is 64 slots with 32 of them byes. Unknown for a draw with no slot scaffold, where round
// one is only the matches the feed happens to have named.
function drawSize(t) {
  if (!t.slotted && !t.completed) return null;
  const r1 = (t.rounds[0] || {}).matches || [];
  return r1.length ? r1.length * 2 - r1.filter((m) => m.bye).length : null;
}

// The lines under the <h1>: what this draw is, in the order you'd ask. First the
// sponsor's name for the event, which the <h1> does not carry but the tour publishes and a
// search turns up, then the level, the surface and the size of the field together, then
// the host city on its own — three different questions ("what's it called", "what kind of
// event", "where") rather than one run-on line. Every part is optional — an event the
// calendar can't place keeps its name alone rather than showing a line of gaps.
function billing(t) {
  const e = t.event || {};
  const name = t.name !== ename(t) ? t.name : null;
  const kind = [e.level || t.tier];
  if (e.surface) kind.push(e.indoor ? `${e.surface} (indoor)` : e.surface);
  const size = drawSize(t);
  if (size) kind.push(`${size}-player draw`);
  const where = e.venue || t.city;
  return [name, kind.filter(Boolean).join(" · "), where].filter(Boolean);
}

// A finished draw with charting reads as a plain charted / not-charted split; everything
// else keeps the four-step coverage scale.
//
// Read left to right the chips climb: uncharted, thin, decent, deep. A key is a scale, and a
// scale that starts at its top end asks the reader to run it backwards against every other
// left-to-right ramp on the page — the tier colours themselves, the slices view's notch count,
// and the ordering the CSS ramp is written in.
function updateLegend(t) {
  // Per-match charting rides in the draw feed, so this pair is known as soon as the page has
  // a draw to show — it never waits on the database and never has to say it is missing.
  const perMatch = t.rounds.some((r) => r.matches.some((m) => m.charted != null));
  if (perMatch) {
    $("legend").innerHTML = `<span class="chip t-none">not charted yet</span>
       <span class="chip t-rich">charted</span>`;
    return;
  }
  // The four-step scale is read out of the insights database, which lands after the first
  // paint and sometimes not at all. Until it does, no card is wearing a tier, and four chips
  // over an unshaded draw are a key to a scale nothing on screen is using.
  if (!cov) {
    $("legend").innerHTML = `<span class="legendwait">${covState === "down"
      ? "charting depth unavailable" : "charting depth loading…"}</span>`;
    return;
  }
  $("legend").innerHTML = `<span class="chip t-none">uncharted</span>
     <span class="chip t-thin">thin</span>
     <span class="chip t-some">decent</span>
     <span class="chip t-rich">deep</span>`;
}

function render() {
  $("status").hidden = true;
  const t = pick();
  document.body.dataset.theme = themeFor(t);
  // The tab keeps the site's name and only that. Leading with the selected event would rename
  // the tab on every dropdown change, so a tab parked reading "Wimbledon" could not be found
  // by its title. The event is the <h1> on the page, where it doesn't have to compete for
  // ~15 characters.
  $("pageTitle").textContent = glabel(t);
  const lines = billing(t);
  const bEl = $("billing");
  bEl.innerHTML = "";
  for (const line of lines) {
    const span = document.createElement("span");
    span.className = "billing-line";
    span.textContent = line;
    bEl.append(span);
  }
  bEl.hidden = !lines.length;
  updateLegend(t);

  // Phones skip the quarter view entirely: the whole draw, one round at a time,
  // opened on the current round. Wide screens keep the quarter view (one top-down
  // grid, see renderQuarters) or the full tree.
  const mobile = window.matchMedia("(max-width: 700px)").matches;
  const quarters = !mobile && quarterable(t) && viewFor(t) === "quarters";
  $("viewTabs").style.display = !mobile && quarterable(t) ? "" : "none";
  // The legend sits outside the draw it explains, so it has to be told which one is under
  // it: only the slices view spells charting depth as a count of corner notches, and a key
  // demonstrating four notches above a draw that draws one wedge is a key for the wrong
  // picture. The two views' cards still share the colour ramp, which is what the chips say
  // in either case — this only decides whether they also carry the count.
  document.body.dataset.view = quarters ? "quarters" : "draw";

  if (mobile) {
    if (sel.round == null || sel.round >= t.rounds.length) sel.round = currentRound(t.rounds);
    renderRoundList(t.rounds, $("bracket"), t, cov, openMatchup, {
      selected: sel.round, paired: t.slotted,
      onPick: (i) => { sel.round = i; render(); },
    });
  } else if (quarters) {
    renderQuarters(t, $("bracket"), cov, openMatchup,
      { selected: sel.section, onPick: (s) => { sel.section = s; render(); } });
  } else {
    renderTree(t.rounds, $("bracket"), t, cov, openMatchup);
  }
}

// The draw does not wait on this. It is rendered from ./data/brackets.json, which is
// same-origin and already on disk; the depth shading is the one thing on the page that needs
// the database, so it arrives when it arrives and the page says which of the two states it is
// in meanwhile. A failure is re-rendered rather than only logged: the legend has to stop
// promising a scale the cards are not wearing.
async function loadCoverage() {
  try {
    const rows = await query("SELECT gender, player, matches_charted FROM player_summary");
    const next = {};
    for (const r of rows) next[r.gender + "|" + r.player] = Number(r.matches_charted);
    cov = next;
    covState = "ready";
  } catch (e) {
    covState = "down";
    console.warn("insights db unavailable:", e);
  }
  render();
}

function wireDrawer() {
  // closeMatchup owns the rest of it — the page scroll lock and handing focus back to
  // the match tile that opened the panel.
  $("matchupClose").onclick = closeMatchup;
  $("scrim").onclick = closeMatchup;
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeMatchup(); });
}

main();
