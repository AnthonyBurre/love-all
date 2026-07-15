// Orchestration: load the brackets feed, build tabs, theme the page to the selected
// tournament, render the bracket (quarter view by default, full draw on demand),
// and wire the matchup drawer.
import { renderTree, renderCascade, renderFan, renderRoundList, currentRound,
         quarterRounds, quarterLabels } from "./bracket.js";
import { openMatchup } from "./matchup.js";
import { query } from "./db.js";

let data = null;
const cov = {};                 // "G|player" -> charted match count
const sel = { key: null, gender: null, view: "quarters", quarter: 0, round: null };

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

// A draw can be sliced into quarters only when its bracket ordering is trustworthy — a live
// fixture-backed draw or a finished one (both fully linked) — and its shape is a clean
// power-of-two down to the quarterfinal. Odd-sized 1000 draws fall back to the full draw.
function quarterable(t) {
  if (!(t.slotted || t.completed)) return false;
  const r = t.rounds;
  if (r.length < 4 || r[r.length - 1].matches.length !== 1) return false;
  return r.slice(0, r.length - 2).every((rd) => rd.matches.length % 4 === 0);
}

function seg(container, items, active, onPick) {
  container.innerHTML = "";
  for (const [val, label] of items) {
    const b = document.createElement("button");
    b.textContent = label;
    if (val === active) b.className = "on";
    b.onclick = () => onPick(val);
    container.appendChild(b);
  }
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
  seg($("viewTabs"), [["quarters", "By quarter"], ["full", "Full draw"]],
    q ? sel.view : "full", (v) => {
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

  // Phones skip the cascade and quarter machinery entirely: the whole draw,
  // one round at a time, opened on the current round. Wide screens keep the
  // quarter view (cascade + wired quarter tree) or the full tree.
  const mobile = window.matchMedia("(max-width: 700px)").matches;
  const quarters = !mobile && quarterable(t) && sel.view === "quarters";
  $("cascadeWrap").hidden = !quarters;
  $("viewTabs").style.display = !mobile && quarterable(t) ? "" : "none";

  if (mobile) {
    if (sel.round == null || sel.round >= t.rounds.length) sel.round = currentRound(t.rounds);
    renderRoundList(t.rounds, $("bracket"), t, cov, openMatchup, {
      selected: sel.round, paired: t.slotted,
      onPick: (i) => { sel.round = i; render(); },
    });
  } else if (quarters) {
    const labels = quarterLabels(t);
    renderCascade(t, $("cascade"), cov, openMatchup, {
      labels, selected: sel.quarter,
      onPick: (q) => { sel.quarter = q; render(); },
    });
    // The quarterfinal lives up in the cascade; the fan flows down from it: R16 → R1.
    const qr = quarterRounds(t, sel.quarter);
    const fanRounds = qr.slice(0, qr.length - 1).reverse();
    $("quarterTitle").textContent = labels[sel.quarter];
    renderFan(fanRounds, $("bracket"), t, cov, openMatchup);
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

function wireDrawer() {
  const close = () => {
    $("matchup").hidden = true;
    $("scrim").hidden = true;
  };
  $("matchupClose").onclick = close;
  $("scrim").onclick = close;
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") close(); });
}

main();
