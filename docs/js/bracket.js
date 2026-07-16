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

// The wide layout groups by column instead of by player — both names on one line, both
// scores on the line below — so a match reads in one row instead of two. Used in the by-
// quarter view (cascade + pinned/scrolling fan), where cards run wide enough for it.
function nameSpan(s) {
  const named = s.name && s.name !== "TBD";
  const span = el("span", "nm " + (s.winner ? "win" : named ? "lose" : ""));
  if (s.seed) span.append(el("span", "seed", s.seed));
  span.append(document.createTextNode(s.name || "TBD"));
  return span;
}

function setsSpan(s) {
  return el("span", "sets", (s.sets || []).map((x) => (x == null ? "" : Math.trunc(x))).join(" "));
}

function matchCard(m, t, cov, onClick, wide) {
  const tier = matchTier(m, t.gender, cov);
  const card = el("div", "match " + tier.cls + (wide ? " wide" : "") + (m.placeholder ? " ghost" : ""));
  card.title = tier.note;
  if (wide) {
    const names = el("div", "namesrow");
    names.append(nameSpan(m.a), nameSpan(m.b));
    const scores = el("div", "scoresrow");
    scores.append(setsSpan(m.a), setsSpan(m.b));
    card.append(names, scores);
  } else {
    card.append(sideRow(m.a), sideRow(m.b));
  }
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

// Slice a set of rounds' matches into n equal groups, keeping group i.
function sliceGroup(rounds, i, n) {
  return rounds.map((r) => {
    const size = r.matches.length / n;
    return { ...r, matches: r.matches.slice(i * size, (i + 1) * size) };
  });
}

// Rounds up to the quarterfinals, sliced to quarter q (0-3): R1 16, …, QF 1.
export function quarterRounds(t, q) {
  const upToQF = t.rounds.slice(0, t.rounds.length - 2);
  return sliceGroup(upToQF, q, 4);
}

// A quarter's round of 32 always has 4 matches — one per quarter of *it*. Slice an
// already quarter-scoped set of rounds (its round of 64 and, on a slam, round of 128)
// down to slot s (0-3), one for each of those 4 round-of-32 matches.
export function slotRounds(rounds, s) {
  return sliceGroup(rounds, s, 4);
}

// The "business end" cascade: final on top, the two semifinals below it, and the
// four quarter selectors below those — each chip under the semifinal its winner
// feeds, wired with the same SVG connectors, so the structure reads top-down.
export function renderCascade(t, root, cov, onClick, quarter) {
  root.innerHTML = "";
  const final = t.rounds[t.rounds.length - 1].matches[0];
  const sfs = t.rounds[t.rounds.length - 2].matches;
  const qfs = t.rounds[t.rounds.length - 3].matches;

  const label = (text) => root.append(el("div", "cascade-label", text));
  const cell = (cls, ...nodes) => {
    const c = el("div", "cslot " + cls);
    c.append(...nodes);
    root.append(c);
  };
  label("Final");
  const fc = matchCard(final, t, cov, onClick, true);
  cell("slot-final", fc);

  label("Semifinals");
  const sf1 = matchCard(sfs[0], t, cov, onClick, true);
  const sf2 = matchCard(sfs[1], t, cov, onClick, true);
  cell("slot-sf", sf1);
  cell("slot-sf", sf2);

  label("Quarterfinals");
  // Each quarterfinal is a real match card with its own selector beneath — pick one and the
  // fan below flows down from it. The card still opens the matchup drawer on click.
  const qsels = [];
  const qfCards = qfs.map((qf, q) => {
    const card = matchCard(qf, t, cov, onClick, true);
    const sel = el("button", "qsel" + (q === quarter.selected ? " on" : ""), quarter.labels[q]);
    sel.title = `Show ${quarter.labels[q]} — round of 16 down to round 1`;
    sel.onclick = () => quarter.onPick(q);
    cell("slot-qf" + (q === quarter.selected ? " qf-on" : ""), card, sel);
    qsels.push(sel);
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
  return { qfCards, qsels };
}

// A picked fan (round of 16 down through round of 32, or a slot's round of 64 down through
// round of 128) has no card of its own for the thing that was picked — that's already shown,
// once, a level up — so this draws the one connector that has to cross containers: the
// selected chip down to the first row of cards below it. Appended into the upper container's
// own root so it inherits that container's wire styling and can overflow below its box into
// the pinned block that follows it. Used both for cascade → quarter fan and quarter fan →
// slot fan, since the two crossings are structurally identical.
export function wireQuarterToFan(parentRoot, chip, childCards) {
  if (!chip || !childCards.length) return;
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("class", "wires");
  const rect = parentRoot.getBoundingClientRect();
  const anchor = (n, edge) => {
    const r = n.getBoundingClientRect();
    return { x: r.left - rect.left + r.width / 2,
             y: r.top - rect.top + (edge === "top" ? 0 : r.height) };
  };
  const a = anchor(chip, "bottom");
  let bottom = 0;
  for (const card of childCards) {
    const b = anchor(card, "top");
    bottom = Math.max(bottom, anchor(card, "bottom").y);
    const mid = (a.y + b.y) / 2;
    const p = document.createElementNS("http://www.w3.org/2000/svg", "path");
    p.setAttribute("d", `M ${a.x} ${a.y} C ${a.x} ${mid}, ${b.x} ${mid}, ${b.x} ${b.y}`);
    p.setAttribute("class", "hot");
    svg.appendChild(p);
  }
  svg.setAttribute("width", parentRoot.scrollWidth);
  svg.setAttribute("height", bottom);
  parentRoot.appendChild(svg);
}

// The chosen quarter, flowing straight down from its quarterfinal: rounds stacked as rows
// (R16 at top → R32 at bottom), each match centered over its two feeders in the row below
// and wired in one SVG. `opts.pick`, when given, plants a selector under every card of the
// *last* round — one per match, same idea as the cascade's quarterfinal selectors — so a
// deeper fan (that match's own earlier rounds) can be picked and pinned in below rather than
// needing to scroll sideways into view.
export function renderFan(rounds, root, t, cov, onClick, opts = {}) {
  const { cardWidth = 176, wide = false, pick = null, scale = 8 } = opts;
  root.innerHTML = "";
  root.classList.remove("aslist");
  root.classList.add("asfan");
  if (!rounds.length) return { cards: new Map(), picks: [] };

  const CARD = cardWidth, GAP = 14, U = CARD + GAP;
  const widest = Math.max(...rounds.map((r) => r.matches.length));
  const W = widest * U;
  // Every round shown here is small enough (2 or 4 matches wide, at most) to fit under the
  // wider cascade above, so the fan centers itself in the container; its labels should
  // instead read flush with the Final/Semifinals/Quarterfinals column to their left, so pull
  // them back by whatever the centering has inset them by.
  const fits = W <= root.clientWidth;
  const inset = fits ? (root.clientWidth - W) / 2 : 0;

  const fan = el("div", "fan");
  fan.style.width = W + "px";
  const cards = new Map();
  const picks = [];
  rounds.forEach((round, ri) => {
    const label = el("div", "fan-label" + (fits ? " flush" : ""), `Round of ${round.matches.length * scale}`);
    if (inset) label.style.marginLeft = `-${inset}px`;
    fan.append(label);
    const row = el("div", "fan-row");
    const n = round.matches.length;
    const isPickRound = pick && ri === rounds.length - 1;
    round.matches.forEach((m, j) => {
      const card = matchCard(m, t, cov, onClick, wide);
      card.style.width = CARD + "px";
      // Center each round at its natural width so narrow rows (the QF apex, R16, R32) stay
      // put and fully visible.
      const cx = W / 2 + (j - (n - 1) / 2) * U;
      let node = card;
      if (isPickRound) {
        node = el("div", "fan-cell" + (j === pick.selected ? " picked" : ""));
        node.style.width = CARD + "px";        // keep the selector's width from skewing centering
        card.style.position = "static";        // the cell carries the absolute placement now
        const btn = el("button", "qsel" + (j === pick.selected ? " on" : ""), pick.labels[j]);
        btn.title = `Show ${pick.labels[j]} — earlier rounds`;
        btn.onclick = () => pick.onPick(j);
        node.append(card, btn);
        picks.push(btn);
      }
      node.style.left = (cx - CARD / 2) + "px";
      row.append(node);
      cards.set(m.id, card);
    });
    fan.append(row);
  });
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

  return { cards, picks };
}

// Label each of a round's n equal slices by its best-seeded (or first-named) entrant,
// e.g. "Sinner" — falling back to an ordinal ("Quarter 2") when nobody's decided yet.
function bestSeedLabels(round, n, suffix, fallbackPrefix) {
  const labels = [];
  const size = round.matches.length / n;
  for (let i = 0; i < n; i++) {
    let best = null;                       // {seed, name}
    for (const m of round.matches.slice(i * size, (i + 1) * size)) {
      for (const s of [m.a, m.b]) {
        const seed = parseInt(s.seed, 10);
        if (!s.name || s.name === "TBD" || isNaN(seed)) continue;
        if (!best || seed < best.seed) best = { seed, name: s.name };
      }
    }
    const surname = best && best.name.split(" ").slice(-1)[0];
    labels.push(surname ? `${surname}${suffix}` : `${fallbackPrefix} ${i + 1}`);
  }
  return labels;
}

export function quarterLabels(t) {
  return bestSeedLabels(t.rounds[0], 4, " ¼", "Quarter");
}

// Label each of a quarter's 4 round-of-32 matches by its earliest round's best seed —
// the same idea as quarterLabels, one level deeper. `overflow` is that quarter's own
// round of 64 (and, on a slam, round of 128); the earliest of those is the widest.
export function slotLabels(overflow) {
  const earliest = overflow.reduce((a, b) => (b.matches.length > a.matches.length ? b : a));
  return bestSeedLabels(earliest, 4, "", "Section");
}
