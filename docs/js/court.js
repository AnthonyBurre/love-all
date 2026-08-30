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
//
// Presentation has deliberately diverged, though: these draw at ~96px in a panel, where
// court.py's reports draw at full size. So this file adds arrowheads, bounce rings, a
// dashed neutral treatment for a ball the opponent hit, and a tinted half marking whose
// side is whose — cues that earn their place only at thumbnail scale. Geometry is shared;
// styling is not, and nothing here needs porting back.
//
// Both renderers use that one vocabulary, so a drawing means the same thing wherever it
// appears: tint = the profiled player's half, solid and coloured = a ball they hit, dashed
// and neutral = one the opponent hit, ring = the bounce the drawing turns on. pairSvg
// knows those roles from its shape; rallySvg has to work them out — see the note there.

// --- court geometry (a 150 x 190 field; matches court.py and the notation-key courts) ---
const LEFT = 20, RIGHT = 130, TOP = 10, BOTTOM = 180, NET = 95, HALF = NET - TOP;
const SERVICE_F = 0.5;                       // service line, as a fraction of a half
const LANE_L = 40, LANE_MID = 75, LANE_R = 110;
const DEPTH_DEFAULT = 0.62;                  // rally bounce depth (tokens carry no depth)
const SERVE_DEPTH_F = 0.42;                  // serve lands a touch inside the service line
const SERVE_TOKEN_DIR = { W: "4", B: "5", T: "6" };

// The court occupies x 20–130, y 10–180 of the 150×190 field the geometry is written in, so
// a full-field viewBox spends a quarter of a thumbnail's width on blank margin. These draw
// at ~88px in the panel, where that margin is the difference between a ball path you can
// follow and a smudge. FRAME crops to the court plus a few units of air — enough for the two
// player markers and a terminal arrowhead, and nothing else. It is presentation, like the
// arrowheads and the tinted half: every coordinate below is still court.py's, so the two
// renderers stay in sync and nothing here needs porting back.
const FRAME_PAD = 6;
const FRAME = [LEFT - FRAME_PAD, TOP - FRAME_PAD,
  RIGHT - LEFT + 2 * FRAME_PAD, BOTTOM - TOP + 2 * FRAME_PAD].join(" ");

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

// One drawn ball: the line plus its direction marks. Exported so the notation-key courts
// in matchup.js draw their example shots the same way as a real ball path.
// `incoming` marks a ball the opponent hit rather than the profiled player, which the CSS
// draws dashed and neutral: whose ball it is is the one thing every drawing here encodes
// the same way, so it never has to be read off weight or position.
// `arrow` swaps the mid-line chevrons for a single head at the far end; `bare` drops both,
// for a ball whose direction its own endpoints already give away.
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
      return { x: serveX(dir, court), y: depthY(SERVE_DEPTH_F, true) };
    }
    const top = i % 2 === 0;
    const dir = tok.length > 2 && "123".includes(tok[2]) ? tok[2] : null;
    return { x: laneX(dir, top), y: depthY(DEPTH_DEFAULT, top) };
  });
}

// Render a token list ("svW", "Bs3", ...) as a court SVG string, css-classed for the site.
//
// Who hit what isn't fixed here the way it is in pairSvg. A trigger's tokens are the K
// strokes *before* the player's aggressive shot and hitters alternate, so ownership runs
// backwards from the end: the last token is always the ball the opponent sent them — the
// one they attacked, and the reason the sequence is in the panel — and every second token
// before it is theirs. Every shipped cue is a 2-shot lead-up, so token 1 is the player's
// own — the odd-K branch is kept because the drawing is written for any K and a deeper
// tier has shipped here before — and it puts the player's half wherever the last ball
// lands.
//
// Everything else follows from that one fact, in pairSvg's vocabulary: their half tinted,
// their own balls solid and in their colour, the opponent's dashed and neutral, and a
// hollow ring where the last one bounced. The ring is the pivot the sequence exists to set
// up — the aggressive shot played from it is what the numbers beside the drawing measure,
// and it is deliberately not drawn, because a stored pattern never says where it went.
export function rallySvg(tokens, court = "deuce") {
  const bs = bounces(tokens, court);
  if (!bs.length) return "";
  const mineTop = bs.length % 2 === 1;
  const isMine = (i) => i % 2 === bs.length % 2;
  let px = serveOriginX(court), py = BOTTOM - 4;         // opening contact, anchors stroke 1
  const els = [isMine(0)
    ? `<circle cx="${f(px)}" cy="${f(py)}" r="2.3" class="ct-player"/>`
    : `<circle cx="${f(px)}" cy="${f(py)}" r="2.6" class="ct-them"/>`];
  bs.forEach((b, i) => {
    els.push(shotLine(px, py, b.x, b.y, { incoming: !isMine(i), shot: i + 1 }));
    px = b.x; py = b.y;
  });
  const end = bs[bs.length - 1];
  els.push(`<circle cx="${f(end.x)}" cy="${f(end.y)}" r="3" class="ct-bounce"/>`);
  return `<svg viewBox="${FRAME}" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="ball path">${tintHalf(mineTop)}${COURT}${els.join("")}</svg>`;
}

// --- pattern string -> tokens (the inverse of shot_language.tokens.pretty) --------------
// Stored trigger contexts are the human-readable form: "serve wide · BH slice→3"
// (dot separated lead-up shots).
const SHOT_RE = /serve (?:wide|body|T)|(?:FH|BH|\?) (?:drive|slice|net|shot)→[123·]/g;
const SERVE_TOK = { "serve wide": "svW", "serve body": "svB", "serve T": "svT" };
const SIDE_TOK = { FH: "F", BH: "B", "?": "?" };
const KIND_TOK = { drive: "d", slice: "s", net: "v", shot: "o" };

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
// `mirror` puts the sequence back on the physical court. Trigger and deep-pattern contexts
// are both stored hand-relative — mirrored for a left-hander, so that a token names the
// shot rather than the half of the court it landed in and two players' sequences can be
// compared — and a drawing has to undo that or it draws a lefty's rally into the wrong
// third. So it is set from the player's hand alone, not from which family the row is in.
export function patternSvg(pattern, mirror = false) {
  const labels = String(pattern).match(SHOT_RE);
  if (!labels || !labels.length) return "";
  return rallySvg(labels.map((l) => labelToToken(l, mirror)));
}

// --- court-state patterns (player_patterns table) ----------------------------------------
// One incoming ball, one response. The incoming ball lands on the near half — the profiled
// player's side, matching the "into the BH corner" wording — and the response lands up top.
// Return-depth states move the incoming bounce short or deep; every other bounce sits at
// the default rally depth, like the token drawings.
//
// These render at thumbnail size, where a viewer has to know instantly which half is whose
// and which of the two balls came first. Three cues carry that, so no one of them has to
// survive alone: the profiled player's half is tinted, the ball they *receive* is dashed
// and neutral while the one they *hit* is solid and in their colour, and only the response
// gets an arrowhead. A hollow ring sits where the incoming ball bounced — the pivot the
// answer is played from.
const PAIR_DEPTH = { short: 0.33, "mid-depth": DEPTH_DEFAULT, deep: 0.86 };

export function pairSvg(incCode, respCode, depth = "") {
  const inc = {
    x: laneX(String(incCode), false),
    y: depthY(PAIR_DEPTH[depth] ?? DEPTH_DEFAULT, false),
  };
  const out = { x: laneX(String(respCode), true), y: depthY(DEPTH_DEFAULT, true) };
  const ox = LANE_MID, oy = TOP + 4;      // opponent's contact, anchors the incoming ball
  // Two balls with fixed roles: the player always receives and always answers, so their
  // half is always the near one — no parity to work out, unlike rallySvg.
  const els = [
    `<circle cx="${f(ox)}" cy="${f(oy)}" r="2.6" class="ct-them"/>`,
    // This one ball runs marker-to-ring, so its endpoints already say which way it went;
    // rallySvg's opponent balls sit mid-chain and keep their chevrons.
    shotLine(ox, oy, inc.x, inc.y, { incoming: true, bare: true, shot: 1 }),
    `<circle cx="${f(inc.x)}" cy="${f(inc.y)}" r="3" class="ct-bounce"/>`,
    shotLine(inc.x, inc.y, out.x, out.y, { arrow: true, shot: 2 }),
  ];
  return `<svg viewBox="${FRAME}" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="ball path">${tintHalf(false)}${COURT}${els.join("")}</svg>`;
}

// --- serve+1 (the "off the return" family) ------------------------------------------------
// The same picture with the serve that started the point in front of it, because for this
// family the serve *is* the state: the serve_plus_one experiment exists on the finding that
// a wide serve opens the forehand in the deuce court and the backhand in the ad court, and
// a drawing that begins at the return cannot show that. Here the server is the profiled
// player, so the near half is theirs in the same way pairSvg's is.
//
// The serve is drawn faint. It is context — the reason the return arrived where it did —
// while the ball the numbers beside the drawing actually measure is the third one, which
// keeps the arrowhead. Without the fade all three balls read as equally the point.
//
// Three levels, matching the three tiers a pattern can be surfaced at, so the drawing never
// claims more than the row behind it knows:
//   both court and direction  a serve, struck from the right side, landing where it landed
//   court only                no serve line; the two players just stand on the correct sides
//   neither                   pairSvg, unchanged — there is nothing to add
export function retSvg(court, serveDir, incCode, respCode, depth = "") {
  const side = String(court || "").toLowerCase();
  if (side !== "deuce" && side !== "ad") return pairSvg(incCode, respCode, depth);
  const dir = String(serveDir || "");
  const known = dir === "4" || dir === "5" || dir === "6";

  const inc = {
    x: laneX(String(incCode), false),
    y: depthY(PAIR_DEPTH[depth] ?? DEPTH_DEFAULT, false),
  };
  const out = { x: laneX(String(respCode), true), y: depthY(DEPTH_DEFAULT, true) };
  // With no charted direction this is the middle of the correct service box, which says
  // which side the point was played from without asserting a placement inside it.
  const land = { x: serveX(known ? dir : null, side), y: depthY(SERVE_DEPTH_F, true) };
  const sx = serveOriginX(side), sy = BOTTOM - 4;

  const els = [
    `<circle cx="${f(sx)}" cy="${f(sy)}" r="2.3" class="ct-player"/>`,
    known ? shotLine(sx, sy, land.x, land.y, { faint: true, bare: true, shot: 1 }) : "",
    `<circle cx="${f(land.x)}" cy="${f(land.y)}" r="2.6" class="ct-them"/>`,
    shotLine(land.x, land.y, inc.x, inc.y, { incoming: true, bare: true, shot: 2 }),
    `<circle cx="${f(inc.x)}" cy="${f(inc.y)}" r="3" class="ct-bounce"/>`,
    shotLine(inc.x, inc.y, out.x, out.y, { arrow: true, shot: 3 }),
  ];
  return `<svg viewBox="${FRAME}" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="serve and third ball">${tintHalf(false)}${COURT}${els.join("")}</svg>`;
}
