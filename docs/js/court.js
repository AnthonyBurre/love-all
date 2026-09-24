// Mini tennis-court ball-path renderer, the client-side twin of
// `match_charting_project.viz.rally_svg` (src/match_charting_project/viz/court.py). The site is
// static, so drawings are made in the browser from the pattern text in the DB and none are
// stored.
//
// It mirrors court.py's token path only (serves and rally placements, no misses or terminal
// markers), which is all a stored pattern string encodes. Keep the geometry in sync with
// court.py, the canonical renderer for reports. Styling differs because these draw at ~96px:
// arrowheads, a dashed neutral line for the opponent's ball, a tinted half for the profiled
// player, and a ring on one bounce only.
//
// The vocabulary: tint = the profiled player's half, solid and coloured = a ball they hit,
// dashed and neutral = one the opponent hit. Lines run contact to contact, and a ring marks a
// bounce, so a line with no ring is a ball taken out of the air. pairSvg knows who hit what
// from its shape; rallySvg works it out (see the note there).

// --- court geometry (a 150 x 190 field; matches court.py and the notation-key courts) ---
const LEFT = 20, RIGHT = 130, TOP = 10, BOTTOM = 180, NET = 95, HALF = NET - TOP;
const SERVICE_F = 0.5;                       // service line, as a fraction of a half
const LANE_L = 40, LANE_MID = 75, LANE_R = 110;
const DEPTH_DEFAULT = 0.62;                  // rally bounce depth (tokens carry no depth)
// Two strokes whose whole point is their depth, and which a stored pattern never carries a
// charted depth for: a drop shot dies just over the net, a lob lands on the baseline. Same
// numbers as court.py.
const KIND_DEPTH = { drop: 0.20, lob: 0.92 };
const SERVE_DEPTH_F = 0.42;                  // serve lands a touch inside the service line
const SERVE_TOKEN_DIR = { W: "4", B: "5", T: "6" };

// Where a player meets the ball, which is never where it bounced. A groundstroke is
// struck a step past the bounce, as the ball rises off it; a return is struck from around
// the baseline however short the serve landed, because the returner's stance sets that,
// not the serve; a volley is struck before the ball reaches the ground at all. Fractions
// of one half's net-to-baseline depth, and the same numbers as court.py.
const STEP_F = 0.12;                         // a rally ball is met this far past its bounce
const RETURN_DEPTH_F = 0.92;                 // a serve is returned from about the baseline
const NET_CONTACT_F = 0.25;                  // a volley is taken this far in front of the net
const CONTACT_PAD = 3;                       // how far outside a sideline a contact may sit
const SERVE_STANCE = 4;                      // the server stands this far behind the baseline
const RALLY_STANCE = 4;                      // a mid-rally opening is anchored just inside it

// The token alphabet's kind letter. Only "net" changes the drawing, but the full map
// keeps the vocabulary the same as court.py's _TOKEN_KIND.
const TOKEN_KIND = { d: "drive", s: "slice", v: "net", p: "drop", l: "lob", o: "other" };
const tokenKind = (tok) => (tok.startsWith("sv") ? "serve" : (TOKEN_KIND[tok[1]] ?? "other"));

// Crop the 150×190 field to the court (x 20–130, y 10–180) plus a little air for the player
// markers and arrowheads. Coordinates are still court.py's.
const FRAME_PAD = 6;
const FRAME_FOOT = 3;                        // extra, for a server standing off the court
const FRAME = [LEFT - FRAME_PAD, TOP - FRAME_PAD,
  RIGHT - LEFT + 2 * FRAME_PAD, BOTTOM - TOP + 2 * FRAME_PAD + FRAME_FOOT].join(" ");

// Direction wingtips: two small chevrons per segment, at these fractions along it.
const TIP_AT = [0.38, 0.72];
const TIP_BACK = 3.4;                        // how far the wings trail behind the apex
const TIP_HALF = 2.5;                        // half-width of the V
const TIP_MIN = 9;                           // shorter than this, no room for a tip
const TIP_TWO_MIN = 20;                      // shorter than this, one centred tip

// Terminal arrowhead: marks where a drawn ball finished, so the last stroke of a
// sequence reads as an endpoint rather than as one more segment.
const HEAD_LEN = 6.5;
const HEAD_HALF = 3.2;

const f = (v) => String(Math.round(v * 10) / 10);

// Small chevrons pointing from (x1,y1) toward (x2,y2). A zig-zag of bounces reads the
// same either way round without them; short segments get one, hair-thin ones none.
function tips(x1, y1, x2, y2, cls) {
  const dx = x2 - x1, dy = y2 - y1, len = Math.hypot(dx, dy);
  if (len < TIP_MIN) return [];
  const ux = dx / len, uy = dy / len;
  const nx = -uy, ny = ux;                   // unit normal: the wings' spread
  const ats = len >= TIP_TWO_MIN ? TIP_AT : [0.5];
  return ats.map((t) => {
    const ax = x1 + dx * t, ay = y1 + dy * t;              // apex, on the line
    const bx = ax - TIP_BACK * ux, by = ay - TIP_BACK * uy; // wings trail behind it
    return `<path d="M${f(bx + TIP_HALF * nx)} ${f(by + TIP_HALF * ny)} L${f(ax)} ${f(ay)} L${f(bx - TIP_HALF * nx)} ${f(by - TIP_HALF * ny)}" fill="none" stroke-linecap="round" stroke-linejoin="round" class="${cls}"/>`;
  });
}

// A filled triangle at (x2,y2), pointing along the segment. Used on the stroke that
// finishes a drawing — one head reads faster than a trail of chevrons, and it puts the
// emphasis where the ball landed.
function head(x1, y1, x2, y2, cls) {
  const dx = x2 - x1, dy = y2 - y1, len = Math.hypot(dx, dy);
  if (len < HEAD_LEN + 2) return "";
  const ux = dx / len, uy = dy / len;
  const nx = -uy, ny = ux;
  const bx = x2 - HEAD_LEN * ux, by = y2 - HEAD_LEN * uy;
  return `<path d="M${f(x2)} ${f(y2)}L${f(bx + HEAD_HALF * nx)} ${f(by + HEAD_HALF * ny)}` +
    `L${f(bx - HEAD_HALF * nx)} ${f(by - HEAD_HALF * ny)}Z" class="${cls}"/>`;
}

// One drawn ball: the line plus its direction marks. Exported for the notation-key courts in
// matchup.js. `incoming` marks the opponent's ball (dashed and neutral in CSS). `arrow` swaps
// the mid-line chevrons for a head at the far end; `bare` drops both.
export function shotLine(x1, y1, x2, y2,
  { faint = false, shot = null, arrow = false, incoming = false, bare = false } = {}) {
  const mods = (faint ? " faint" : "") + (incoming ? " incoming" : "");
  const idx = shot == null ? "" : ` data-shot="${shot}"`;
  const line = `<line${idx} x1="${f(x1)}" y1="${f(y1)}" x2="${f(x2)}" y2="${f(y2)}" class="ct-shot${mods}" fill="none"/>`;
  if (bare) return line;
  return line + (arrow
    ? head(x1, y1, x2, y2, "ct-head" + mods)
    : tips(x1, y1, x2, y2, "ct-tip" + mods).join(""));
}

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

// The wash marking the profiled player's half. Drawn before the court, so the lines and
// the balls sit over it rather than under.
const tintHalf = (top) =>
  `<rect x="${LEFT}" y="${top ? TOP : NET}" width="${RIGHT - LEFT}" ` +
  `height="${top ? NET - TOP : BOTTOM - NET}" class="ct-mine"/>`;

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
      return { x: serveX(dir, court), y: depthY(SERVE_DEPTH_F, true), isServe: true };
    }
    const top = i % 2 === 0;
    const dir = tok.length > 2 && "123".includes(tok[2]) ? tok[2] : null;
    const frac = KIND_DEPTH[TOKEN_KIND[tok[1]]] ?? DEPTH_DEFAULT;
    return { x: laneX(dir, top), y: depthY(frac, top), isServe: false };
  });
}

// Where the line through a and b sits at height y, extended past b if needed. An extension
// that would leave the court stops at the sideline, so the contact stays on the ball's line.
function pointAtDepth(a, b, y) {
  const lo = LEFT - CONTACT_PAD, hi = RIGHT + CONTACT_PAD;
  if (Math.abs(b[1] - a[1]) < 1e-9) return [Math.min(Math.max(b[0], lo), hi), y];
  const x = a[0] + (y - a[1]) / (b[1] - a[1]) * (b[0] - a[0]);
  if ((x >= lo && x <= hi) || Math.abs(b[0] - a[0]) < 1e-9) {
    return [Math.min(Math.max(x, lo), hi), y];
  }
  const edge = x < lo ? lo : hi;
  return [edge, a[1] + (edge - a[0]) / (b[0] - a[0]) * (b[1] - a[1])];
}

// Where each stroke was struck from, and which balls bounced. A contact lies on the incoming
// ball's line past the bounce: a step for a groundstroke, a stride for a return, and short of
// the bounce for a volley. `bounced` is per incoming ball, false where a volley answered it.
function contactPoints(bs, kinds, start) {
  const contacts = [start];
  const bounced = bs.map(() => true);
  for (let i = 1; i < bs.length; i++) {
    const prev = bs[i - 1];
    const a = contacts[i - 1], b = [prev.x, prev.y];
    const top = prev.y < NET;
    const away = top ? -1 : 1;                 // away from the net, in screen y
    let y;
    if (kinds[i] === "net") {
      bounced[i - 1] = false;
      y = depthY(NET_CONTACT_F, top);
      if ((y - prev.y) * away >= 0) y = prev.y; // aimed shorter than a volley is taken
    } else if (prev.isServe) {
      y = depthY(RETURN_DEPTH_F, top);
    } else {
      y = prev.y + away * STEP_F * HALF;
    }
    contacts.push(pointAtDepth(a, b, Math.min(Math.max(y, TOP - 4), BOTTOM + 4)));
  }
  return { contacts, bounced };
}

// Render a token list ("svW", "Bs3", ...) as a court SVG string, css-classed for the site.
//
// Hitters alternate and the last token is the opponent's ball the player attacked, so
// ownership runs backwards from the end. Shipped cues are two-shot lead-ups; odd lengths are
// handled too. The player's half is wherever the last ball lands, with a ring where it
// bounced. The aggressive shot itself isn't drawn, since the pattern never says where it went.
export function rallySvg(tokens, court = "deuce") {
  const bs = bounces(tokens, court);
  if (!bs.length) return "";
  const mineTop = bs.length % 2 === 1;
  const isMine = (i) => i % 2 === bs.length % 2;
  const opens = bs[0].isServe;
  // Opening contact, anchoring stroke 1: a server stands behind their baseline, and a
  // sequence that starts mid-rally has no real origin, so it is anchored just inside one.
  const start = [serveOriginX(court), BOTTOM + (opens ? SERVE_STANCE : -RALLY_STANCE)];
  const { contacts } = contactPoints(bs, tokens.map(tokenKind), start);
  const [sx, sy] = contacts[0];
  const els = [isMine(0)
    ? `<circle cx="${f(sx)}" cy="${f(sy)}" r="2.3" class="ct-player"/>`
    : `<circle cx="${f(sx)}" cy="${f(sy)}" r="2.6" class="ct-them"/>`];
  // Each ball runs from the contact that struck it to the contact that answered it, so
  // every kink is a player meeting the ball. The intermediate bounces along the way are
  // left unmarked: at 88px a second ring is a smudge, and the line passes through the
  // bounce by construction, so a serve's placement still reads off where it crosses the
  // box. court.py rings every one of them, because it draws at full size.
  bs.forEach((b, i) => {
    const [x1, y1] = contacts[i];
    const [x2, y2] = i === bs.length - 1 ? [b.x, b.y] : contacts[i + 1];
    els.push(shotLine(x1, y1, x2, y2, { incoming: !isMine(i), shot: i + 1 }));
  });
  // The serve's landing is the one intermediate bounce that gets a mark. Every other
  // one is left to the line passing through it, but a serve read only off the angle of
  // a line running on to the returner does not read as a serve at all: the drawing needs
  // the spot in the box.
  if (opens && bs.length > 1) {
    els.push(`<circle cx="${f(bs[0].x)}" cy="${f(bs[0].y)}" r="2.4" class="ct-bounce faint"/>`);
  }
  const end = bs[bs.length - 1];
  els.push(`<circle cx="${f(end.x)}" cy="${f(end.y)}" r="3" class="ct-bounce"/>`);
  return `<svg viewBox="${FRAME}" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="ball path">${tintHalf(mineTop)}${COURT}${els.join("")}</svg>`;
}

// --- pattern string -> tokens (the inverse of shot_language.tokens.pretty) --------------
// Stored trigger contexts are the human-readable form: "serve wide · BH slice→3"
// (dot separated lead-up shots).
const SHOT_RE = /serve (?:wide|body|T)|(?:FH|BH|\?) (?:drive|slice|net|drop|lob|shot)→[123·]/g;
const SERVE_TOK = { "serve wide": "svW", "serve body": "svB", "serve T": "svT" };
const SIDE_TOK = { FH: "F", BH: "B", "?": "?" };
const KIND_TOK = { drive: "d", slice: "s", net: "v", drop: "p", lob: "l", shot: "o" };

// Court thirds mirrored, for a sequence stored in a left-hander's own frame.
const MIRROR_DIR = { 1: "3", 2: "2", 3: "1" };

function labelToToken(label, mirror = false) {
  label = label.trim();
  // Serves are never mirrored: wide/body/T name the box the server is aiming into and
  // mean the same shot in either hand, which is why the experiments leave them alone.
  if (label.startsWith("serve")) return SERVE_TOK[label] ?? "sv?";
  const sp = label.indexOf(" ");
  const side = label.slice(0, sp);
  const [kind, dir] = label.slice(sp + 1).split("→");
  const d = (dir ?? "").trim() || "·";
  return (SIDE_TOK[side] ?? "?") + (KIND_TOK[kind.trim()] ?? "o")
    + (mirror ? (MIRROR_DIR[d] ?? d) : d);
}

// A stored pattern string -> its court SVG, or "" if it holds no recognizable shots.
//
// `mirror` undoes the hand-relative storage (mirrored for a left-hander), so it's set from
// the player's hand alone. `court` matters only when the sequence opens with a serve, since a
// wide serve is a different ball on each side; pooled cues use rallySvg's default.
export function patternSvg(pattern, mirror = false, court = "deuce") {
  const labels = String(pattern).match(SHOT_RE);
  if (!labels || !labels.length) return "";
  return rallySvg(labels.map((l) => labelToToken(l, mirror)), court);
}

// --- court-state patterns (player_patterns table) ----------------------------------------
// One incoming ball, one response. The incoming ball lands on the near half (the profiled
// player's side) and the response lands up top. Return-depth states move the incoming bounce
// short or deep; other bounces sit at the default rally depth.
//
// The player's half is tinted, the ball they receive is dashed and neutral, the one they hit
// is solid in their colour, and only the response gets an arrowhead. A fourth mark shows the
// pivot (see `pivot`). The response leaves from where the player met the ball, a step past
// the bounce.
const PAIR_DEPTH = { short: 0.33, "mid-depth": DEPTH_DEFAULT, deep: 0.86 };

// How deep each of the two balls landed. A charted return depth is what the ball actually
// did and wins; otherwise a drop shot and a lob are placed by what they are, and every
// other stroke sits at the ordinary rally depth. The response has no charted depth at all —
// only the return in a "ret" state does — so its kind is all there is to go on.
const incDepth = (depth, kind) => PAIR_DEPTH[depth] ?? KIND_DEPTH[kind] ?? DEPTH_DEFAULT;
const outDepth = (kind) => KIND_DEPTH[kind] ?? DEPTH_DEFAULT;

// The pivot marker, which says what happened at the ball the answer was played off.
// A hollow ring is a bounce. A filled dot in the player's colour is a contact with no
// bounce under it — they took it out of the air — and it sits where they met it, up near
// the net, which is the other half of the same fact.
const pivot = (bounced, land, contact) => (bounced
  ? `<circle cx="${f(land.x)}" cy="${f(land.y)}" r="3" class="ct-bounce"/>`
  : `<circle cx="${f(contact[0])}" cy="${f(contact[1])}" r="2.6" class="ct-player"/>`);

export function pairSvg(incCode, respCode, depth = "", incKind = "", respKind = "") {
  const inc = {
    x: laneX(String(incCode), false),
    y: depthY(incDepth(depth, incKind), false),
    isServe: false,
  };
  const out = { x: laneX(String(respCode), true), y: depthY(outDepth(respKind), true) };
  // An opponent who volleyed was standing at the net, not behind their baseline.
  const oy = incKind === "net" ? depthY(NET_CONTACT_F, true) : TOP + 4;
  const { contacts, bounced } = contactPoints([inc, out], ["", respKind], [LANE_MID, oy]);
  const [ox, oyy] = contacts[0];
  const mine = contacts[1];
  if (!String(respCode)) out.x = mine[0];   // a lob: no third to draw, so claim no lane
  // Two balls with fixed roles: the player always receives and always answers, so their
  // half is always the near one — no parity to work out, unlike rallySvg.
  const els = [
    `<circle cx="${f(ox)}" cy="${f(oyy)}" r="2.6" class="ct-them"/>`,
    // This one ball runs marker-to-contact, so its endpoints already say which way it
    // went; rallySvg's opponent balls sit mid-chain and keep their chevrons.
    shotLine(ox, oyy, mine[0], mine[1], { incoming: true, bare: true, shot: 1 }),
    pivot(bounced[0], inc, mine),
    shotLine(mine[0], mine[1], out.x, out.y, { arrow: true, shot: 2 }),
  ];
  return `<svg viewBox="${FRAME}" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="ball path">${tintHalf(false)}${COURT}${els.join("")}</svg>`;
}

// --- serve+1 (the "off the return" family) ------------------------------------------------
// The same picture with the serve in front of it, since a wide serve opens opposite wings on
// the two courts (the serve_plus_one finding). The server is the profiled player. The serve is
// drawn faint, as context; the third ball keeps the arrowhead. The serve line runs past its
// bounce to where the returner met it.
//
// Three levels, matching what the pattern row knows:
//   both court and direction  a serve from the right side, landing where it landed
//   court only                no serve line; the players stand on the correct sides
//   neither                   pairSvg, unchanged
export function retSvg(court, serveDir, incCode, respCode, depth = "",
  incKind = "", respKind = "") {
  const side = String(court || "").toLowerCase();
  if (side !== "deuce" && side !== "ad") return pairSvg(incCode, respCode, depth, incKind, respKind);
  const dir = String(serveDir || "");
  const known = dir === "4" || dir === "5" || dir === "6";

  const inc = {
    x: laneX(String(incCode), false),
    y: depthY(incDepth(depth, incKind), false),
    isServe: false,
  };
  const out = { x: laneX(String(respCode), true), y: depthY(outDepth(respKind), true) };
  // With no charted direction this is the middle of the correct service box, which says
  // which side the point was played from without asserting a placement inside it.
  const land = { x: serveX(known ? dir : null, side), y: depthY(SERVE_DEPTH_F, true),
    isServe: true };
  const start = [serveOriginX(side), BOTTOM + SERVE_STANCE];
  const { contacts, bounced } = contactPoints([land, inc, out], ["serve", incKind, respKind],
    start);
  const them = contacts[1];        // the returner, out where the serve pushed them
  const mine = contacts[2];        // the server, stepping in behind their own delivery
  if (!String(respCode)) out.x = mine[0];   // a lob: no third to draw, so claim no lane

  const els = [
    `<circle cx="${f(start[0])}" cy="${f(start[1])}" r="2.3" class="ct-player"/>`,
    known ? shotLine(start[0], start[1], them[0], them[1], { faint: true, bare: true, shot: 1 }) : "",
    // The serve's landing. The line runs on past it to the returner, so without the spot
    // in the box the first ball reads as a long diagonal rather than as a serve.
    known ? `<circle cx="${f(land.x)}" cy="${f(land.y)}" r="2.4" class="ct-bounce faint"/>` : "",
    `<circle cx="${f(them[0])}" cy="${f(them[1])}" r="2.6" class="ct-them"/>`,
    shotLine(them[0], them[1], mine[0], mine[1], { incoming: true, bare: true, shot: 2 }),
    pivot(bounced[1], inc, mine),
    shotLine(mine[0], mine[1], out.x, out.y, { arrow: true, shot: 3 }),
  ];
  return `<svg viewBox="${FRAME}" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="serve and third ball">${tintHalf(false)}${COURT}${els.join("")}</svg>`;
}
