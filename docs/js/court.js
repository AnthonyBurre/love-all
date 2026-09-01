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
// court.py's reports draw at full size. So this file adds arrowheads, a dashed neutral
// treatment for a ball the opponent hit, and a tinted half marking whose side is whose —
// cues that earn their place only at thumbnail scale. It also rings one bounce where
// court.py rings every one it draws past: at 88px a second ring is a smudge. Geometry is
// shared; styling is not, and nothing here needs porting back.
//
// Both renderers use that one vocabulary, so a drawing means the same thing wherever it
// appears: tint = the profiled player's half, solid and coloured = a ball they hit, dashed
// and neutral = one the opponent hit. Lines run contact to contact, so every kink is a
// player meeting the ball, and a ring on a line is where that ball bounced along the way —
// which leaves a line carrying no ring meaning something definite, that the ball never
// bounced and was taken out of the air. pairSvg knows the hitters' roles from its shape;
// rallySvg has to work them out — see the note there.

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

// The court occupies x 20–130, y 10–180 of the 150×190 field the geometry is written in, so
// a full-field viewBox spends a quarter of a thumbnail's width on blank margin. These draw
// at ~88px in the panel, where that margin is the difference between a ball path you can
// follow and a smudge. FRAME crops to the court plus a few units of air — enough for the two
// player markers and a terminal arrowhead, and nothing else. It is presentation, like the
// arrowheads and the tinted half: every coordinate below is still court.py's, so the two
// renderers stay in sync and nothing here needs porting back.
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
      return { x: serveX(dir, court), y: depthY(SERVE_DEPTH_F, true), isServe: true };
    }
    const top = i % 2 === 0;
    const dir = tok.length > 2 && "123".includes(tok[2]) ? tok[2] : null;
    const frac = KIND_DEPTH[TOKEN_KIND[tok[1]]] ?? DEPTH_DEFAULT;
    return { x: laneX(dir, top), y: depthY(frac, top), isServe: false };
  });
}

// Where the line through a and b sits at height y, extended past b when y is beyond it.
//
// A wide serve really does pull a returner off the court and the extension says so, but the
// drawing has no room to follow one indefinitely — and depth and width are drawn on
// different scales here, which exaggerates how far it runs. So an extension that would leave
// the court is stopped where it crosses the sideline rather than slid back inside at the
// depth asked for: the contact comes out shallower, which is what being yanked that wide
// actually does, and it stays *on the ball's line*. Keeping it there is what lets a bounce
// sit on the drawn segment instead of beside it.
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

// Where each stroke was struck from, and which balls reached the ground.
//
// A ball runs straight in plan view, so a player standing to it meets it on that line,
// past the bounce — which is why a contact is found by extending the incoming ball's own
// line rather than by stepping straight back from where it landed. How far along depends
// on the stroke: a groundstroke a step, a return a stride to wherever the returner was
// standing, and a volley not past the bounce at all but short of it, out of the air.
//
// `bounced` is per *incoming* ball, false where a volley answered it — the one fact a
// stroke can only learn from the stroke after it, and the reason nothing is drawn saying
// a volleyed ball landed.
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
// `mirror` puts the sequence back on the physical court. Trigger and deep-pattern contexts
// are both stored hand-relative — mirrored for a left-hander, so that a token names the
// shot rather than the half of the court it landed in and two players' sequences can be
// compared — and a drawing has to undo that or it draws a lefty's rally into the wrong
// third. So it is set from the player's hand alone, not from which family the row is in.
// `court` matters only when the sequence opens with a serve, and then it matters a lot:
// a wide serve is a different physical ball on the two sides, which is the whole reason
// the opening cues are split by court at all. Pooled cues have no side to pass and keep
// rallySvg's default; an opening cue passes its own.
export function patternSvg(pattern, mirror = false, court = "deuce") {
  const labels = String(pattern).match(SHOT_RE);
  if (!labels || !labels.length) return "";
  return rallySvg(labels.map((l) => labelToToken(l, mirror)), court);
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
// gets an arrowhead. A fourth marks the pivot the answer is played off — see `pivot`.
//
// The response leaves from where the player met the ball, a step past where it landed,
// rather than from the bounce itself. Small shift, and it earns its keep: an answer
// springing from the exact point the ball hit the ground reads as a shot struck from
// there, which for a ball down the middle is a shot nobody plays.
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
// The serve line runs past its own bounce to wherever the returner met it, which is what
// puts them at their baseline rather than standing in the service box: a returner's
// position is set by their stance, not by how short the serve landed. The bounce itself
// goes unmarked, but the line passes through it, so wide / body / T still reads off where
// the serve crosses the box.
//
// Three levels, matching the three tiers a pattern can be surfaced at, so the drawing never
// claims more than the row behind it knows:
//   both court and direction  a serve, struck from the right side, landing where it landed
//   court only                no serve line; the two players just stand on the correct sides
//   neither                   pairSvg, unchanged — there is nothing to add
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
