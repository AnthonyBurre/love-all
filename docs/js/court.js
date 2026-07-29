// Mini tennis-court ball-path renderer — the client-side twin of the Python
// `match_charting_project.viz.rally_svg` (src/match_charting_project/viz/court.py).
//
// The Pages site is static, so it can't call the Python renderer at request time; this
// draws the same picture in the browser, on the fly, from the pattern text already in the
// DB — so no SVGs are stored and nothing has to be regenerated as players/tournaments grow.
//
// It mirrors court.py's TOKEN path only: serves + rally placements, no misses or terminal
// markers. That's all a stored pattern string ("serve wide · BH slice→3") ever encodes —
// the lead-up shots of a trigger, never a winner/error. Keep the geometry below in sync
// with court.py; that module stays the canonical renderer for reports.

// --- court geometry (viewBox 150 x 190; matches court.py and the notation-key courts) ---
const W = 150, H = 190;
const LEFT = 20, RIGHT = 130, TOP = 10, BOTTOM = 180, NET = 95, HALF = NET - TOP;
const SERVICE_F = 0.5;                       // service line, as a fraction of a half
const LANE_L = 40, LANE_MID = 75, LANE_R = 110;
const DEPTH_DEFAULT = 0.62;                  // rally bounce depth (tokens carry no depth)
const SERVE_DEPTH_F = 0.42;                  // serve lands a touch inside the service line
const SERVE_TOKEN_DIR = { W: "4", B: "5", T: "6" };

const f = (v) => String(Math.round(v * 10) / 10);

const depthY = (frac, top) => (top ? NET - frac * HALF : NET + frac * HALF);

// Lateral x for a rally zone (1/2/3), resolved for the end it lands in. Zone 1 is a
// righty's FH corner; because the ends face opposite ways it is screen-left in the far
// (top) half and screen-right in the near (bottom) half, so the mapping mirrors at the net.
function laneX(dir, top) {
  if (dir !== "1" && dir !== "3") return LANE_MID;    // middle, or direction not charted
  let left = dir === "1";
  if (!top) left = !left;                              // near half is mirrored
  return left ? LANE_L : LANE_R;
}

// A serve crosses diagonally: the deuce court (server right of centre) into the receiver's
// left box on screen, the ad court into the right box. Anything but "ad" is the deuce court.
const serveLeft = (court) => String(court).toLowerCase() !== "ad";

function serveX(dir, court) {
  const off = { "6": 6, "5": 25, "4": 45 }[dir] ?? 25;   // T / body / wide from centre line
  return serveLeft(court) ? LANE_MID - off : LANE_MID + off;
}

const serveOriginX = (court) => (serveLeft(court) ? LANE_MID + 20 : LANE_MID - 20);

// The static court: sidelines, service boxes, centre marks, net. Identical every render.
const COURT = [
  `<rect x="${LEFT}" y="${TOP}" width="${RIGHT - LEFT}" height="${BOTTOM - TOP}" class="ct-line"/>`,
  `<line x1="${LEFT}" y1="${f(depthY(SERVICE_F, true))}" x2="${RIGHT}" y2="${f(depthY(SERVICE_F, true))}" class="ct-line"/>`,
  `<line x1="${LEFT}" y1="${f(depthY(SERVICE_F, false))}" x2="${RIGHT}" y2="${f(depthY(SERVICE_F, false))}" class="ct-line"/>`,
  `<line x1="${LANE_MID}" y1="${f(depthY(SERVICE_F, true))}" x2="${LANE_MID}" y2="${f(depthY(SERVICE_F, false))}" class="ct-line"/>`,
  `<line x1="${LANE_MID}" y1="${TOP}" x2="${LANE_MID}" y2="${TOP + 4}" class="ct-line"/>`,
  `<line x1="${LANE_MID}" y1="${BOTTOM - 4}" x2="${LANE_MID}" y2="${BOTTOM}" class="ct-line"/>`,
  `<line x1="${LEFT}" y1="${NET}" x2="${RIGHT}" y2="${NET}" class="ct-net"/>`,
].join("");

// One bounce point per token (serve hits from the bottom, so even strokes land up top).
function bounces(tokens, court) {
  return tokens.map((tok, i) => {
    if (tok.startsWith("sv")) {
      const dir = SERVE_TOKEN_DIR[tok.slice(2)] ?? null;
      return { x: serveX(dir, court), y: depthY(SERVE_DEPTH_F, true) };
    }
    const top = i % 2 === 0;
    const dir = tok.length > 2 && "123".includes(tok[2]) ? tok[2] : null;
    return { x: laneX(dir, top), y: depthY(DEPTH_DEFAULT, top) };
  });
}

// Render a token list ("svW", "Bs3", ...) as a court SVG string, css-classed for the site.
export function rallySvg(tokens, court = "deuce") {
  const bs = bounces(tokens, court);
  let px = serveOriginX(court), py = BOTTOM - 4;         // server's contact, anchors stroke 1
  const els = [`<circle cx="${f(px)}" cy="${f(py)}" r="2.3" fill="none" class="ct-player"/>`];
  bs.forEach((b, i) => {
    const cls = "ct-shot" + (i === bs.length - 1 ? "" : " faint");   // bold the final stroke
    els.push(`<line data-shot="${i + 1}" x1="${f(px)}" y1="${f(py)}" x2="${f(b.x)}" y2="${f(b.y)}" class="${cls}" fill="none"/>`);
    px = b.x; py = b.y;
  });
  return `<svg viewBox="0 0 ${W} ${H}" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="ball path">${COURT}${els.join("")}</svg>`;
}

// --- pattern string -> tokens (the inverse of shot_language.tokens.pretty) --------------
// Stored trigger contexts are the human-readable form: "serve wide · BH slice→3"
// (dot separated lead-up shots).
const SHOT_RE = /serve (?:wide|body|T)|(?:FH|BH|\?) (?:drive|slice|net|shot)→[123·]/g;
const SERVE_TOK = { "serve wide": "svW", "serve body": "svB", "serve T": "svT" };
const SIDE_TOK = { FH: "F", BH: "B", "?": "?" };
const KIND_TOK = { drive: "d", slice: "s", net: "v", shot: "o" };

function labelToToken(label) {
  label = label.trim();
  if (label.startsWith("serve")) return SERVE_TOK[label] ?? "sv?";
  const sp = label.indexOf(" ");
  const side = label.slice(0, sp);
  const [kind, dir] = label.slice(sp + 1).split("→");
  return (SIDE_TOK[side] ?? "?") + (KIND_TOK[kind.trim()] ?? "o") + ((dir ?? "").trim() || "·");
}

// A stored pattern string -> its court SVG, or "" if it holds no recognizable shots.
export function patternSvg(pattern) {
  const labels = String(pattern).match(SHOT_RE);
  if (!labels || !labels.length) return "";
  return rallySvg(labels.map(labelToToken));
}

// --- court-state patterns (player_patterns table) ----------------------------------------
// One incoming ball, one response. The incoming ball lands on the near half — the profiled
// player's side, matching the "into the BH corner" wording — and the response lands up top,
// drawn bold. Return-depth states move the incoming bounce short or deep; every other
// bounce sits at the default rally depth, like the token drawings.
const PAIR_DEPTH = { short: 0.33, "mid-depth": DEPTH_DEFAULT, deep: 0.86 };

export function pairSvg(incCode, respCode, depth = "") {
  const inc = {
    x: laneX(String(incCode), false),
    y: depthY(PAIR_DEPTH[depth] ?? DEPTH_DEFAULT, false),
  };
  const out = { x: laneX(String(respCode), true), y: depthY(DEPTH_DEFAULT, true) };
  const ox = LANE_MID, oy = TOP + 4;      // opponent's contact, anchors the incoming ball
  const els = [
    `<circle cx="${f(ox)}" cy="${f(oy)}" r="2.3" fill="none" class="ct-player"/>`,
    `<line data-shot="1" x1="${f(ox)}" y1="${f(oy)}" x2="${f(inc.x)}" y2="${f(inc.y)}" class="ct-shot faint" fill="none"/>`,
    `<line data-shot="2" x1="${f(inc.x)}" y1="${f(inc.y)}" x2="${f(out.x)}" y2="${f(out.y)}" class="ct-shot" fill="none"/>`,
  ];
  return `<svg viewBox="0 0 ${W} ${H}" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="ball path">${COURT}${els.join("")}</svg>`;
}
