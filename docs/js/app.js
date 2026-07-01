// Orchestration: load the brackets feed, build tabs, render, wire the matchup drawer.
import { renderBracket } from "./bracket.js";
import { openMatchup } from "./matchup.js";
import { query } from "./db.js";

let data = null;
const cov = {};                 // "G|player" -> charted match count
const sel = { name: null, gender: null };

const $ = (id) => document.getElementById(id);

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
    $("status").textContent = "No Grand Slam or 1000 draws are live right now — check back during an event.";
    return;
  }
  const first = data.tournaments[0];
  sel.name = first.name;
  sel.gender = first.gender;
  $("controls").hidden = false;
  buildTabs();
  render();
  loadCoverage();               // fills coverage dots when the WASM db is ready
  wireDrawer();
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
    buildTabs();
    render();
  });
  const g = gendersFor(sel.name);
  seg($("genderTabs"), g.map((x) => [x, x === "M" ? "Men" : "Women"]), sel.gender, (x) => {
    sel.gender = x;
    buildTabs();
    render();
  });
  $("genderTabs").style.display = g.length > 1 ? "" : "none";
}

function render() {
  $("status").hidden = true;
  renderBracket(pick(), cov, openMatchup);
}

async function loadCoverage() {
  try {
    const rows = await query("SELECT gender, player, matches_charted FROM player_summary");
    for (const r of rows) cov[r.gender + "|" + r.player] = r.matches_charted;
    render();                   // re-render to light up the coverage dots
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
