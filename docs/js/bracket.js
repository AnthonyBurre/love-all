// Render a tournament as a linked bracket tree: columns per round, each match card
// vertically centered between the two matches that feed it (where the linkage is
// known — see live/brackets.py), with SVG connectors and match-level charting tiers.

const el = (tag, cls, text) => {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text != null) n.textContent = text;
  return n;
};

// A match is only as analyzable as its lesser-charted player: tier = min(both).
export function matchTier(m, gender, cov) {
  if (m.placeholder) return { cls: "t-tbd", note: "path to this match — not decided yet" };
  const n = (s) => (s.matched ? cov[gender + "|" + s.matched] || 0 : s.name && s.name !== "TBD" ? 0 : null);
  const [na, nb] = [n(m.a), n(m.b)];
  if (na == null || nb == null) return { cls: "t-tbd", note: "opponent not decided yet" };
  const min = Math.min(na, nb);
  const note = `${na} + ${nb} charted matches`;
  if (min >= 30) return { cls: "t-rich", note: `deep charting on both — ${note}` };
  if (min >= 8) return { cls: "t-some", note: `decent charting on both — ${note}` };
  if (min >= 1) return { cls: "t-thin", note: `thin charting — ${note}` };
  return { cls: "t-none", note: `uncharted matchup — ${note}` };
}

function sideRow(s) {
  const named = s.name && s.name !== "TBD";
  const row = el("div", "side " + (s.winner ? "win" : named ? "lose" : ""));
  const sets = el("span", "sets", (s.sets || []).map((x) => (x == null ? "" : Math.trunc(x))).join(" "));
  const nm = el("span", "nm");
  if (s.seed) nm.append(el("span", "seed", s.seed));
  nm.append(document.createTextNode(s.name || "TBD"));
  row.append(nm, sets);
  return row;
}

function matchCard(m, t, cov, onClick) {
  const tier = matchTier(m, t.gender, cov);
  const card = el("div", "match " + tier.cls + (m.placeholder ? " ghost" : ""));
  card.title = tier.note;
  card.append(sideRow(m.a), sideRow(m.b));
  if (m.state === "in") {
    card.append(el("div", "detail live", "● " + (m.detail || "Live")));
  } else if (m.state === "pre" && m.detail && m.detail !== "TBD") {
    card.append(el("div", "detail", m.detail));
  }
  if (!m.placeholder) card.onclick = () => onClick(m, t);
  return card;
}

// Lay out one column: a match with known feeders sits at their vertical midpoint,
// anything else stacks below the previous card. max() keeps cards from overlapping
// when a column mixes linked and unlinked matches (mid-tournament).
function placeColumn(matches, cards, centers, gap) {
  let bottom = 0;
  for (const m of matches) {
    const card = cards.get(m.id);
    const h = card.offsetHeight;
    const fed = centers.get(m.id);        // [feederCenterY, ...] set by the earlier column
    let y = bottom;
    if (fed && fed.length) y = Math.max(fed.reduce((a, b) => a + b, 0) / fed.length - h / 2, bottom);
    card.style.top = y + "px";
    m._cy = y + h / 2;
    bottom = y + h + gap;
    if (m.feeds) {
      if (!centers.has(m.feeds)) centers.set(m.feeds, []);
      centers.get(m.feeds).push(m._cy);
    }
  }
  return bottom;
}

function drawConnectors(t, root, cards) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("class", "wires");
  // Coordinates relative to the bracket's scroll content (offsetLeft/Top would be
  // relative to each card's own positioned column, not the bracket).
  const rootRect = root.getBoundingClientRect();
  const pos = (id) => {
    const r = cards.get(id).getBoundingClientRect();
    const x = r.left - rootRect.left + root.scrollLeft;
    const y = r.top - rootRect.top + root.scrollTop + r.height / 2;
    return { l: x, r: x + r.width, y };
  };
  for (const round of t.rounds) {
    for (const m of round.matches) {
      if (!m.feeds || !cards.has(m.feeds)) continue;
      const a = pos(m.id), b = pos(m.feeds);
      const mid = (a.r + b.l) / 2;
      const p = document.createElementNS("http://www.w3.org/2000/svg", "path");
      p.setAttribute("d", `M ${a.r} ${a.y} C ${mid} ${a.y}, ${mid} ${b.y}, ${b.l} ${b.y}`);
      svg.appendChild(p);
    }
  }
  svg.setAttribute("width", root.scrollWidth);
  svg.setAttribute("height", root.scrollHeight);
  root.appendChild(svg);
}

export function renderBracket(t, cov, onClick) {
  const root = document.getElementById("bracket");
  root.innerHTML = "";
  const cards = new Map();
  for (const round of t.rounds) {
    const col = el("div", "round");
    col.append(el("h3", null, round.label));
    const list = el("div", "round-list");
    for (const m of round.matches) {
      const card = matchCard(m, t, cov, onClick);
      cards.set(m.id, card);
      list.append(card);
    }
    col.append(list);
    root.append(col);
  }
  // Second pass, once heights are measurable: tree-position the cards, then wire them.
  const gap = 8;
  const centers = new Map();              // match id -> center-y of each known feeder
  let maxBottom = 0;
  for (const round of t.rounds) {
    maxBottom = Math.max(maxBottom, placeColumn(round.matches, cards, centers, gap));
  }
  for (const listEl of root.querySelectorAll(".round-list")) listEl.style.height = maxBottom + "px";
  drawConnectors(t, root, cards);
}
