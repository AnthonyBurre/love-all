// Bracket rendering: a reusable tree renderer (columns per round, cards centered
// between their feeders, SVG wires) plus quarter-slicing helpers. app.js decides
// which slice of the draw goes into which container.

const el = (tag, cls, text) => {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text != null) n.textContent = text;
  return n;
};

// A match is only as analyzable as its lesser-charted player: tier = min(both).
// Completed draws that have any charting shade per *match* instead — charted or not —
// which is the signal that matters once the result is in (`m.charted` is a bool then,
// null otherwise). A finished draw with nothing charted yet falls back to the coverage view.
export function matchTier(m, gender, cov) {
  if (m.placeholder) return { cls: "t-tbd", note: "path to this match — not decided yet" };
  if (m.charted != null) {
    return m.charted
      ? { cls: "t-rich", note: "charted — open to view the full chart" }
      : { cls: "t-none", note: "not charted yet — open to help chart it" };
  }
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
// when a column mixes linked and unlinked matches.
function placeColumn(matches, cards, centers, gap) {
  let bottom = 0;
  for (const m of matches) {
    const card = cards.get(m.id);
    const h = card.offsetHeight;
    const fed = centers.get(m.id);
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

function drawConnectors(rounds, root, cards) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("class", "wires");
  const rootRect = root.getBoundingClientRect();
  const pos = (id) => {
    const r = cards.get(id).getBoundingClientRect();
    const x = r.left - rootRect.left + root.scrollLeft;
    const y = r.top - rootRect.top + root.scrollTop + r.height / 2;
    return { l: x, r: x + r.width, y };
  };
  for (const round of rounds) {
    for (const m of round.matches) {
      if (!m.feeds || !cards.has(m.feeds)) continue;    // target outside this slice
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

// Render a set of rounds as a linked tree into `root` (any .bracket-styled container).
export function renderTree(rounds, root, t, cov, onClick) {
  root.innerHTML = "";
  root.classList.remove("aslist", "asfan");
  const cards = new Map();
  for (const round of rounds) {
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
  const gap = 8;
  const centers = new Map();
  let maxBottom = 0;
  for (const round of rounds) {
    maxBottom = Math.max(maxBottom, placeColumn(round.matches, cards, centers, gap));
  }
  for (const listEl of root.querySelectorAll(".round-list")) listEl.style.height = maxBottom + "px";
  drawConnectors(rounds, root, cards);
  root.scrollLeft = 0;
}

// Phones get a structurally different layout: one round at a time as a vertical
// list (no horizontal panning), with chips to move through the rounds. Consecutive
// pairs are bracketed together when ordering is slot-true — those winners meet.
const shortLabel = (label) => {
  const m = /^round (?:of )?(\d+)$/i.exec(label);
  if (m) return { 128: "R1", 64: "R2", 32: "R3", 16: "R16" }[m[1]] || "R" + m[1];
  const r = /^round (\d+)$/i.exec(label);
  if (r) return "R" + r[1];
  return { quarterfinal: "QF", quarterfinals: "QF", semifinal: "SF", semifinals: "SF",
           final: "F" }[label.toLowerCase()] || label;
};

export function renderRoundList(rounds, root, t, cov, onClick, roundSel) {
  root.innerHTML = "";
  root.classList.add("aslist");
  root.classList.remove("asfan");

  const chips = el("div", "roundchips");
  rounds.forEach((r, i) => {
    const b = el("button", "qchip" + (i === roundSel.selected ? " on" : ""), shortLabel(r.label));
    b.title = r.label;
    b.onclick = () => roundSel.onPick(i);
    chips.append(b);
  });
  root.append(chips);

  const round = rounds[roundSel.selected];
  root.append(el("h3", "roundtitle", round.label));
  const list = el("div", "rlist");
  const ms = round.matches;
  const paired = roundSel.paired && ms.length > 1 && ms.length % 2 === 0;
  if (paired) {
    for (let i = 0; i < ms.length; i += 2) {
      const pair = el("div", "pair");
      pair.append(matchCard(ms[i], t, cov, onClick), matchCard(ms[i + 1], t, cov, onClick));
      list.append(pair);
    }
  } else {
    for (const m of ms) list.append(matchCard(m, t, cov, onClick));
  }
  root.append(list);
}

// Default round to open on: the earliest with something still to play.
export function currentRound(rounds) {
  const i = rounds.findIndex((r) => r.matches.some((m) => !m.placeholder && m.state !== "post"));
  return i === -1 ? rounds.length - 1 : i;
}

// --- quarter slicing (valid only for slot-true, power-of-two draws: t.slotted) ---

// Rounds up to the quarterfinals, sliced to quarter q (0-3): R1 16, …, QF 1.
export function quarterRounds(t, q) {
  const upToQF = t.rounds.slice(0, t.rounds.length - 2);
  return upToQF.map((r) => {
    const size = r.matches.length / 4;
    return { ...r, matches: r.matches.slice(q * size, (q + 1) * size) };
  });
}

// The "business end" cascade: final on top, the two semifinals below it, and the
// four quarter selectors below those — each chip under the semifinal its winner
// feeds, wired with the same SVG connectors, so the structure reads top-down.
export function renderCascade(t, root, cov, onClick, quarter) {
  root.innerHTML = "";
  const final = t.rounds[t.rounds.length - 1].matches[0];
  const sfs = t.rounds[t.rounds.length - 2].matches;
  const qfs = t.rounds[t.rounds.length - 3].matches;

  const cell = (cls, ...nodes) => {
    const c = el("div", "cslot " + cls);
    c.append(...nodes);
    root.append(c);
  };
  const fc = matchCard(final, t, cov, onClick);
  cell("slot-final", fc);
  const sf1 = matchCard(sfs[0], t, cov, onClick);
  const sf2 = matchCard(sfs[1], t, cov, onClick);
  cell("slot-sf", sf1);
  cell("slot-sf", sf2);
  // Each quarterfinal is a real match card with its own selector beneath — pick one and the
  // fan below flows down from it. The card still opens the matchup drawer on click.
  const qfCards = qfs.map((qf, q) => {
    const card = matchCard(qf, t, cov, onClick);
    const sel = el("button", "qsel" + (q === quarter.selected ? " on" : ""), quarter.labels[q]);
    sel.title = `Show ${quarter.labels[q]} — round of 16 down to round 1`;
    sel.onclick = () => quarter.onPick(q);
    cell("slot-qf" + (q === quarter.selected ? " qf-on" : ""), card, sel);
    return card;
  });

  // Vertical wires: final ← each SF ← its two quarterfinals (the selected path is hot).
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("class", "wires");
  const rect = root.getBoundingClientRect();
  const anchor = (n, edge) => {
    const r = n.getBoundingClientRect();
    return { x: r.left - rect.left + r.width / 2,
             y: r.top - rect.top + (edge === "top" ? 0 : r.height) };
  };
  const wire = (from, to, hot) => {
    const a = anchor(from, "top"), b = anchor(to, "bottom");
    const mid = (a.y + b.y) / 2;
    const p = document.createElementNS("http://www.w3.org/2000/svg", "path");
    p.setAttribute("d", `M ${a.x} ${a.y} C ${a.x} ${mid}, ${b.x} ${mid}, ${b.x} ${b.y}`);
    if (hot) p.setAttribute("class", "hot");
    svg.appendChild(p);
  };
  wire(sf1, fc, quarter.selected < 2);
  wire(sf2, fc, quarter.selected >= 2);
  qfCards.forEach((qf, q) => wire(qf, q < 2 ? sf1 : sf2, q === quarter.selected));
  svg.setAttribute("width", root.scrollWidth);
  svg.setAttribute("height", root.scrollHeight);
  root.appendChild(svg);
}

// The chosen quarter, flowing straight down from its quarterfinal: rounds stacked as rows
// (R16 at top → R1 at bottom), each match centered over its two feeders in the row below and
// wired in one SVG. The block is as wide as its widest row and scrolls sideways inside the
// container, so cards and wires move together and the page itself never pans.
export function renderFan(rounds, root, t, cov, onClick) {
  root.innerHTML = "";
  root.classList.remove("aslist");
  root.classList.add("asfan");
  if (!rounds.length) return;

  const CARD = 176, GAP = 14;
  const widest = Math.max(...rounds.map((r) => r.matches.length));
  const W = widest * (CARD + GAP);

  const fan = el("div", "fan");
  fan.style.width = W + "px";
  const cards = new Map();
  for (const round of rounds) {
    const row = el("div", "fan-row");
    const n = round.matches.length;
    round.matches.forEach((m, j) => {
      const card = matchCard(m, t, cov, onClick);
      card.style.width = CARD + "px";
      card.style.left = ((j + 0.5) * (W / n) - CARD / 2) + "px";
      row.append(card);
      cards.set(m.id, card);
    });
    fan.append(row);
  }
  root.append(fan);

  // Rows carry absolutely-placed cards, so give each the measured card height to flow.
  for (const row of fan.querySelectorAll(".fan-row")) {
    let h = 0;
    for (const c of row.children) h = Math.max(h, c.offsetHeight);
    row.style.height = h + "px";
  }

  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("class", "wires");
  const rect = fan.getBoundingClientRect();
  const port = (node, edge) => {
    const r = node.getBoundingClientRect();
    return { x: r.left - rect.left + r.width / 2,
             y: r.top - rect.top + (edge === "top" ? 0 : r.height) };
  };
  for (let r = 0; r < rounds.length - 1; r++) {
    const kids = rounds[r + 1].matches;
    rounds[r].matches.forEach((m, j) => {
      const a = port(cards.get(m.id), "bottom");
      for (const kid of [kids[2 * j], kids[2 * j + 1]]) {
        if (!kid) continue;
        const b = port(cards.get(kid.id), "top");
        const mid = (a.y + b.y) / 2;
        const p = document.createElementNS("http://www.w3.org/2000/svg", "path");
        p.setAttribute("d", `M ${a.x} ${a.y} C ${a.x} ${mid}, ${b.x} ${mid}, ${b.x} ${b.y}`);
        svg.appendChild(p);
      }
    });
  }
  svg.setAttribute("width", W);
  svg.setAttribute("height", fan.scrollHeight);
  fan.appendChild(svg);

  root.scrollLeft = (W - root.clientWidth) / 2;   // open centered on the quarter
}

// Label each quarter by its best-seeded (or first-named) player, e.g. "Sinner".
export function quarterLabels(t) {
  const labels = [];
  const r1 = t.rounds[0].matches;
  const size = r1.length / 4;
  for (let q = 0; q < 4; q++) {
    let best = null;                       // {seed, name}
    for (const m of r1.slice(q * size, (q + 1) * size)) {
      for (const s of [m.a, m.b]) {
        const seed = parseInt(s.seed, 10);
        if (!s.name || s.name === "TBD" || isNaN(seed)) continue;
        if (!best || seed < best.seed) best = { seed, name: s.name };
      }
    }
    const surname = best ? best.name.split(" ").slice(-1)[0] : `Quarter ${q + 1}`;
    labels.push(best ? `${surname} ¼` : surname);
  }
  return labels;
}
