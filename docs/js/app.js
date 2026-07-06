// Orchestration: load the brackets feed, build tabs, theme the page to the selected
// tournament, render the bracket (quarter view by default, full draw on demand),
// and wire the matchup drawer.
import { renderTree, renderCascade, renderRoundList, currentRound,
         quarterRounds, quarterLabels } from "./bracket.js";
import { openMatchup } from "./matchup.js";
import { query } from "./db.js";

let data = null;
const cov = {};                 // "G|player" -> charted match count
const sel = { name: null, gender: null, view: "quarters", quarter: 0, round: null };

const $ = (id) => document.getElementById(id);

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
  const first = data.tournaments[0];
  sel.name = first.name;
  sel.gender = first.gender;
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

function names() {
  const out = [];
  for (const t of data.tournaments) if (!out.includes(t.name)) out.push(t.name);
  return out;
}

function gendersFor(name) {
  return data.tournaments.filter((t) => t.name === name).map((t) => t.gender);
}

function pick() {
  return (
    data.tournaments.find((t) => t.name === sel.name && t.gender === sel.gender) ||
    data.tournaments.find((t) => t.name === sel.name) ||
    data.tournaments[0]
  );
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
  seg($("tourTabs"), names().map((n) => [n, n]), sel.name, (n) => {
    sel.name = n;
    if (!gendersFor(n).includes(sel.gender)) sel.gender = gendersFor(n)[0];
    sel.round = null;
    buildTabs();
    render();
  });
  const g = gendersFor(sel.name);
  seg($("genderTabs"), g.map((x) => [x, x === "M" ? "Men" : "Women"]), sel.gender, (x) => {
    sel.gender = x;
    sel.round = null;
    buildTabs();
    render();
  });
  $("genderTabs").style.display = g.length > 1 ? "" : "none";

  // Quarter view needs slot-true ordering; otherwise only the full draw is honest.
  const t = pick();
  $("viewTabs").style.display = t.slotted ? "" : "none";
  seg($("viewTabs"), [["quarters", "By quarter"], ["full", "Full draw"]],
    t.slotted ? sel.view : "full", (v) => {
      sel.view = v;
      sel.round = null;
      buildTabs();
      render();
    });
}

function render() {
  $("status").hidden = true;
  const t = pick();
  document.body.dataset.theme = themeFor(t.name);
  $("pageTitle").textContent = t.name;
  document.title = `${t.name} — Charted Court`;

  const quarters = t.slotted && sel.view === "quarters";
  const mobile = window.matchMedia("(max-width: 700px)").matches;
  $("cascadeWrap").hidden = !quarters;

  // Phones page through one round at a time; wide screens get the wired tree.
  const show = (rounds) => {
    if (mobile) {
      if (sel.round == null || sel.round >= rounds.length) sel.round = currentRound(rounds);
      renderRoundList(rounds, $("bracket"), t, cov, openMatchup, {
        selected: sel.round, paired: t.slotted,
        onPick: (i) => { sel.round = i; render(); },
      });
    } else {
      renderTree(rounds, $("bracket"), t, cov, openMatchup);
    }
  };

  if (quarters) {
    const labels = quarterLabels(t);
    renderCascade(t, $("cascade"), cov, openMatchup, {
      labels, selected: sel.quarter,
      onPick: (q) => { sel.quarter = q; sel.round = null; render(); },
    });
    $("quarterTitle").textContent = `${labels[sel.quarter]} — round 1 to quarterfinal`;
    show(quarterRounds(t, sel.quarter));
  } else {
    show(t.rounds);
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
