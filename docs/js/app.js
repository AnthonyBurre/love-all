// Orchestration: load the brackets feed, build tabs, theme the page to the
// selected tournament, render the bracket into #bracket (quarter view by default,
// full draw on demand, round list on phones), and wire the matchup drawer.
import { renderTree, renderQuarters, renderRoundList, currentRound } from "./bracket.js";
import { openMatchup } from "./matchup.js";
import { query } from "./db.js";

let data = null;
const cov = {};                 // "G|player" -> charted match count
// view: null = auto — full draw early in an event, by-quarter from the round of 16 on.
// section: which sixteenth of the draw (0-7) is unfolded below the round of 16.
const sel = { key: null, gender: null, view: null, section: 0, round: null };

const $ = (id) => document.getElementById(id);

// A tournament group spans its two draws (men/women). Completed events are keyed and
// labelled by year, so Wimbledon 2025 and a live Wimbledon never collide in the dropdown.
const SEP = "␟";
const gkey = (t) => (t.completed ? `${t.name}${SEP}${t.season}` : t.name);
const glabel = (t) => (t.completed ? `${t.name} ${t.season}` : t.name);

// Season/tournament theme: slams get their own palette, 1000s follow their surface.
const CLAY = ["french", "roland", "madrid", "rome", "italian", "monte", "hamburg", "charleston"];
const AUS = ["australian"];
function themeFor(name) {
  const n = (name || "").toLowerCase();
  if (n.includes("wimbledon")) return "";          // grass = the default palette
  if (CLAY.some((c) => n.includes(c))) return "clay";
  if (AUS.some((c) => n.includes(c))) return "aus-hard";
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
    $("status").textContent = "No Grand Slam or 1000 draws are live right now. Check back during an event.";
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
// so the round of 16 is truly 8 matches). Odd-sized 1000 draws fall back to the full draw.
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
function barsIcon(vertical) {
  const s = document.createElement("span");
  s.className = "ico";
  s.innerHTML = vertical
    ? `<svg viewBox="0 0 14 14" width="14" height="14" aria-hidden="true"><rect x="1.2" y="1" width="2.8" height="12" rx="1.4"/><rect x="5.6" y="1" width="2.8" height="12" rx="1.4"/><rect x="10" y="1" width="2.8" height="12" rx="1.4"/></svg>`
    : `<svg viewBox="0 0 14 14" width="14" height="14" aria-hidden="true"><rect x="1" y="1.2" width="12" height="2.8" rx="1.4"/><rect x="1" y="5.6" width="12" height="2.8" rx="1.4"/><rect x="1" y="10" width="12" height="2.8" rx="1.4"/></svg>`;
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
    sel.view = null;            // back to the per-event default
    buildTabs();
    render();
  };

  const g = gendersFor(sel.key);
  seg($("genderTabs"), g.map((x) => [x, x === "M" ? "Men" : "Women"]), sel.gender, (x) => {
    sel.gender = x;
    sel.round = null;
    buildTabs();
    render();
  });
  $("genderTabs").style.display = g.length > 1 ? "" : "none";

  // Quarter view needs trustworthy slot ordering (fixture-backed or finished draws).
  const t = pick();
  const q = quarterable(t);
  $("viewTabs").style.display = q ? "" : "none";
  seg($("viewTabs"), [
    ["quarters", barsIcon(false), "By quarter — the business end, top-down"],
    ["full", barsIcon(true), "Full draw — every round side by side"],
  ], q ? viewFor(t) : "full", (v) => {
    sel.view = v;
    sel.round = null;
    buildTabs();
    render();
  });
}

// A finished draw with charting reads as a plain charted / not-charted split; everything
// else keeps the four-step coverage scale.
function updateLegend(t) {
  const perMatch = t.rounds.some((r) => r.matches.some((m) => m.charted != null));
  $("legend").innerHTML = perMatch
    ? `<span class="chip t-rich">charted</span>
       <span class="chip t-none">not charted yet</span>`
    : `<span class="chip t-rich">deep charting</span>
       <span class="chip t-some">decent</span>
       <span class="chip t-thin">thin</span>
       <span class="chip t-none">uncharted</span>`;
}

function render() {
  $("status").hidden = true;
  const t = pick();
  document.body.dataset.theme = themeFor(t.name);
  $("pageTitle").textContent = glabel(t);
  document.title = `${glabel(t)} — Love All`;
  updateLegend(t);

  // Phones skip the quarter view entirely: the whole draw, one round at a time,
  // opened on the current round. Wide screens keep the quarter view (one top-down
  // grid, see renderQuarters) or the full tree.
  const mobile = window.matchMedia("(max-width: 700px)").matches;
  const quarters = !mobile && quarterable(t) && viewFor(t) === "quarters";
  $("viewTabs").style.display = !mobile && quarterable(t) ? "" : "none";

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

async function loadCoverage() {
  try {
    const rows = await query("SELECT gender, player, matches_charted FROM player_summary");
    for (const r of rows) cov[r.gender + "|" + r.player] = Number(r.matches_charted);
    render();                   // re-render to shade the match tiers
  } catch (e) {
    console.warn("insights db unavailable:", e);
  }
}

// Temporary while the new panel styles are auditioned: A/B/C switches the dialog's
// look live (data-variant drives the CSS), and the pick sticks across opens.
const PANEL_VARIANTS = [
  ["paper", "A", "Paper — quiet card"],
  ["hero", "B", "Hero — tournament colours"],
  ["board", "C", "Scoreboard — score tiles"],
];

function wireDrawer() {
  const close = () => {
    $("matchup").hidden = true;
    $("scrim").hidden = true;
  };
  $("matchupClose").onclick = close;
  $("scrim").onclick = close;
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") close(); });

  const box = $("mVariants");
  const apply = (v) => {
    $("matchup").dataset.variant = v;
    localStorage.setItem("panelVariant", v);
    for (const b of box.children) b.classList.toggle("on", b.dataset.v === v);
  };
  for (const [val, label, title] of PANEL_VARIANTS) {
    const b = document.createElement("button");
    b.dataset.v = val;
    b.textContent = label;
    b.title = title;
    b.setAttribute("aria-label", title);
    b.onclick = () => apply(val);
    box.appendChild(b);
  }
  const stored = localStorage.getItem("panelVariant");
  apply(PANEL_VARIANTS.some(([v]) => v === stored) ? stored : "hero");
}

main();
