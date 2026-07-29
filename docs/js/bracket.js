// Bracket rendering: a reusable tree renderer (columns per round, cards centered
// between their feeders, SVG wires), a phone round-list, and the by-quarter view
// (one top-down grid of the draw, sliced by selector chips).

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

// Per-set score cells: each set is its own span, bold when it's the higher score of
// the set (that set's winner). The match winner then reads as the row with more bold
// numbers — no need to hunt for the highlighted name. `theirs` is the opponent's sets.
function setsEl(mine, theirs) {
  const sets = el("span", "sets");
  (mine || []).forEach((x, i) => {
    if (x == null) return;
    const t = theirs && theirs[i];
    const won = t != null && Math.trunc(x) > Math.trunc(t);
    sets.append(el("span", "set" + (won ? " won" : ""), String(Math.trunc(x))));
  });
  return sets;
}

function sideRow(s, opp) {
  const named = s.name && s.name !== "TBD";
  const row = el("div", "side " + (s.winner ? "win" : named ? "lose" : ""));
  const nm = el("span", "nm");
  if (named) nm.dataset.full = s.name;
  if (s.seed) nm.append(el("span", "seed", s.seed));
  nm.append(document.createTextNode(s.name || "TBD"));
  row.append(nm, setsEl(s.sets, opp && opp.sets));
  return row;
}

// Names render in full; one that overflows its card is abbreviated to first initial
// + surname ("F. Auger-Aliassime"). If that still overflows, capitalized middle
// names go too ("R. Andres Burruchaga" → "R. Burruchaga") — but lowercase surname
// particles stay ("A. de Minaur") — and only then does the CSS ellipsis kick in.
// Run after the cards are in the laid-out DOM — it measures them.
const abbrev = (name) => {
  const cut = name.indexOf(" ");
  return cut > 0 ? `${name[0]}. ${name.slice(cut + 1)}` : name;
};
const abbrevHard = (name) => {
  const parts = name.split(" ");
  if (parts.length < 2) return name;
  const rest = parts.slice(1);
  let i = 0;
  while (i < rest.length - 1 && /^[A-Z]/.test(rest[i])) i++;
  return `${parts[0][0]}. ${rest.slice(i).join(" ")}`;
};
function fitNames(root) {
  for (const nm of root.querySelectorAll(".nm[data-full]")) {
    if (nm.scrollWidth <= nm.clientWidth) continue;
    nm.lastChild.textContent = abbrev(nm.dataset.full);        // "F. Auger-Aliassime", seed kept
    if (nm.scrollWidth <= nm.clientWidth) continue;
    const seed = nm.querySelector(".seed");                    // the seed badge goes next
    if (seed) { seed.remove(); if (nm.scrollWidth <= nm.clientWidth) continue; }
    nm.lastChild.textContent = abbrevHard(nm.dataset.full);    // then middle names, then CSS ellipsis
  }
}

// The wide layout groups by column instead of by player — both names on one line, both
// scores on the line below — so a match reads in one row instead of two. Used in the
// by-quarter view, where cards run wide enough for it.
function nameSpan(s) {
  const named = s.name && s.name !== "TBD";
  const span = el("span", "nm " + (s.winner ? "win" : named ? "lose" : ""));
  if (named) span.dataset.full = s.name;
  if (s.seed) span.append(el("span", "seed", s.seed));
  span.append(document.createTextNode(s.name || "TBD"));
  return span;
}

function matchCard(m, t, cov, onClick, wide) {
  const tier = matchTier(m, t.gender, cov);
  const card = el("div", "match " + tier.cls + (wide ? " wide" : "") + (m.placeholder ? " ghost" : ""));
  card.title = tier.note;
  if (wide) {
    const names = el("div", "namesrow");
    names.append(nameSpan(m.a), nameSpan(m.b));
    const scores = el("div", "scoresrow");
    scores.append(setsEl(m.a.sets, m.b.sets), setsEl(m.b.sets, m.a.sets));
    card.append(names, scores);
  } else {
    card.append(sideRow(m.a, m.b), sideRow(m.b, m.a));
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
  root.className = "bracket";
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
  fitNames(root);
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
  root.className = "bracket aslist";

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
  fitNames(root);
}

// Default round to open on: the earliest with something still to play.
export function currentRound(rounds) {
  const i = rounds.findIndex((r) => r.matches.some((m) => !m.placeholder && m.state !== "post"));
  return i === -1 ? rounds.length - 1 : i;
}

// --- the by-quarter view (valid only for slot-true, power-of-two draws: t.slotted) ---

// Slice a round's matches into n equal groups, keeping group i.
const sliceN = (matches, i, n) => matches.slice((i * matches.length) / n, ((i + 1) * matches.length) / n);

// Label each of a round's n equal slices by its best-seeded (or first-named) entrant,
// e.g. "Sinner" — falling back to an ordinal ("Section 2") when nobody's decided yet.
function bestSeedLabels(matches, n, fallbackPrefix) {
  const labels = [];
  for (let i = 0; i < n; i++) {
    let best = null;                       // {seed, name}
    for (const m of sliceN(matches, i, n)) {
      for (const s of [m.a, m.b]) {
        const seed = parseInt(s.seed, 10);
        if (!s.name || s.name === "TBD" || isNaN(seed)) continue;
        if (!best || seed < best.seed) best = { seed, name: s.name };
      }
    }
    const surname = best && best.name.split(" ").slice(-1)[0];
    labels.push(surname || `${fallbackPrefix} ${i + 1}`);
  }
  return labels;
}

// Textless selector chip glyph: two horizontal lines, echoing a match card's two rows.
const CHIP_ICON = `<svg viewBox="0 0 14 10" width="14" height="10" aria-hidden="true">
  <rect x="1" y="1" width="12" height="2.6" rx="1.3"/>
  <rect x="1" y="6.4" width="12" height="2.6" rx="1.3"/></svg>`;

// The by-quarter view is one 8-column grid read top-down: the final (1 card,
// spanning all 8 columns) over the semifinals (2) over the quarterfinals (4) over
// the whole round of 16 (8 across — those cards flip to the stacked two-line
// layout to fit). Deeper rounds don't fit whole, so a single selector chip under
// each round-of-16 match picks the sixteenth of the draw to unfold beneath it:
// round of 32 (2 cards), round of 64 (4), round of 128 (8, stacked again). Grid
// column spans center each match over its feeders; one SVG overlay draws all the
// wires, hot along the picked path.
export function renderQuarters(t, root, cov, onClick, section) {
  root.innerHTML = "";
  root.className = "quarters";
  const rs = t.rounds;
  const n = rs.length;

  const rows = [
    { label: "Final", matches: rs[n - 1].matches },
    { label: "Semifinals", matches: rs[n - 2].matches },
    { label: "Quarterfinals", matches: rs[n - 3].matches },
    { label: "Round of 16", matches: rs[n - 4].matches },
  ];
  // Rounds below the sixteen, latest first, sliced to the picked sixteenth. Labels
  // reflect the full round's size ("Round of 32"), not the slice's.
  const below = rs.slice(0, n - 4).reverse();
  if (below.length) {
    rows[3].pick = { ...section, labels: bestSeedLabels(rs[0].matches, 8, "Section") };
    for (const r of below) {
      rows.push({ label: `Round of ${r.matches.length * 2}`,
                  matches: sliceN(r.matches, section.selected, 8) });
    }
  }

  const cards = [];               // per row: card elements, for wiring
  const chips = [];               // per row: selector chips (pick rows only)
  rows.forEach((row, i) => {
    root.append(el("div", "qlabel", row.label));
    cards[i] = []; chips[i] = [];
    const span = 8 / row.matches.length;
    row.matches.forEach((m, j) => {
      const cell = el("div", "qcell span" + span);
      const card = matchCard(m, t, cov, onClick, span > 1);   // 8-across rows stack the names
      cell.append(card);
      if (row.pick) {
        // The chip itself is wordless; the seed-leader label lives in the tooltip.
        const btn = el("button", "qsel" + (j === row.pick.selected ? " on" : ""));
        btn.innerHTML = CHIP_ICON;
        btn.title = `Show ${row.pick.labels[j]} — earlier rounds`;
        btn.setAttribute("aria-label", btn.title);
        btn.onclick = () => row.pick.onPick(j);
        cell.append(btn);
        if (j === row.pick.selected) cell.classList.add("picked");
        chips[i].push(btn);
      }
      cards[i].push(card);
      root.append(cell);
    });
  });
  fitNames(root);

  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("class", "wires");
  const rect = root.getBoundingClientRect();
  const wire = (from, to, hot) => {
    const a = from.getBoundingClientRect(), b = to.getBoundingClientRect();
    const x1 = a.left - rect.left + a.width / 2, y1 = a.bottom - rect.top;
    const x2 = b.left - rect.left + b.width / 2, y2 = b.top - rect.top;
    const mid = (y1 + y2) / 2;
    const p = document.createElementNS("http://www.w3.org/2000/svg", "path");
    p.setAttribute("d", `M ${x1} ${y1} C ${x1} ${mid}, ${x2} ${mid}, ${x2} ${y2}`);
    if (hot) p.setAttribute("class", "hot");
    svg.appendChild(p);
  };
  rows.forEach((row, i) => {
    const next = rows[i + 1];
    if (!next) return;
    if (next.matches.length === row.matches.length * 2) {
      // A tree step: the next row's matches 2j and 2j+1 feed this row's match j.
      // Above the chips, the picked sixteenth's path up to the final is hot.
      row.matches.forEach((_, j) => {
        for (const k of [2 * j, 2 * j + 1]) {
          const hot = below.length > 0 && i < 3 &&
                      k === Math.floor((section.selected * next.matches.length) / 8);
          wire(cards[i][j], cards[i + 1][k], hot);
        }
      });
    } else if (row.pick) {
      // A chip step: the picked chip fans out to every match of the row below.
      for (const kid of cards[i + 1]) wire(chips[i][row.pick.selected], kid, true);
    }
  });
  svg.setAttribute("width", root.scrollWidth);
  svg.setAttribute("height", root.scrollHeight);
  root.appendChild(svg);
}
