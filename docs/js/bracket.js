// Render a tournament's rounds as columns of match cards, with charted-coverage dots.

const el = (tag, cls, text) => {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text != null) n.textContent = text;
  return n;
};

function sideRow(s, gender, cov) {
  const named = s.name && s.name !== "TBD";
  const row = el("div", "side " + (s.winner ? "win" : named ? "lose" : ""));
  const key = gender + "|" + (s.matched || "");
  const n = s.matched ? cov[key] : undefined;
  const cls = !s.matched ? "none" : n == null ? "none" : n >= 30 ? "rich" : "some";
  const dot = el("span", "dot " + cls);
  dot.title = !s.matched
    ? "no charting history — chart a match!"
    : n != null ? `${n} charted matches` : "charted";
  const sets = el("span", "sets", (s.sets || []).map((x) => (x == null ? "" : Math.trunc(x))).join(" "));
  row.append(dot, el("span", "nm", s.name || "TBD"), sets);
  return row;
}

function matchCard(m, t, cov, onClick) {
  const card = el("div", "match");
  card.append(sideRow(m.a, t.gender, cov), sideRow(m.b, t.gender, cov));
  if (m.state === "in") {
    const d = el("div", "detail live", "● " + (m.detail || "Live"));
    card.append(d);
  } else if (m.state === "pre" && m.detail) {
    card.append(el("div", "detail", m.detail));
  }
  card.onclick = () => onClick(m, t);
  return card;
}

export function renderBracket(t, cov, onClick) {
  const root = document.getElementById("bracket");
  root.innerHTML = "";
  for (const round of t.rounds) {
    const col = el("div", "round");
    col.append(el("h3", null, round.label));
    const list = el("div", "round-list");
    for (const m of round.matches) list.append(matchCard(m, t, cov, onClick));
    col.append(list);
    root.append(col);
  }
}
