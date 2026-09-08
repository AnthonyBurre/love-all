// The browser's ball-path renderer — the client-side twin of viz/court.py.
//
// The site is static, so it cannot call the Python renderer at request time; this draws the
// same picture in the browser from the pattern text already in the DB. Two implementations
// of one geometry, and the file itself says "keep the geometry below in sync with court.py".
// tests/test_court_parity.py holds the shared constants equal; this holds the drawing's own
// structure, mirroring the invariants tests/test_court.py already pins on the Python side.
//
// Presentation has deliberately diverged and is not compared: these draw at ~96px in a
// panel, so they add arrowheads, a tinted half, and ring one bounce where court.py rings
// every one it draws past. Geometry is shared; styling is not.
//
// Coordinates are read out of the emitted SVG rather than asserted as pixel constants, so
// the drawing stays free to be retuned as long as the relationships hold.

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { rallySvg, shotLine } from "../../docs/js/court.js";

// The court's own frame, from court.js: x 20-130, y 10-180, net at 95.
const NET = 95, LANE_MID = 75, HALF = 85, BOTTOM = 180;

/** Each drawn stroke as {shot, x1, y1, x2, y2}, in stroke order. */
function segments(svg) {
  return [...svg.matchAll(
    /<line data-shot="(\d+)" x1="([-\d.]+)" y1="([-\d.]+)" x2="([-\d.]+)" y2="([-\d.]+)"/g)]
    .map(([, shot, x1, y1, x2, y2]) => ({
      shot: +shot, x1: +x1, y1: +y1, x2: +x2, y2: +y2 }));
}

/** Every circle in the drawing as {x, y, r, cls}. */
function circles(svg) {
  return [...svg.matchAll(
    /<circle cx="([-\d.]+)" cy="([-\d.]+)" r="([\d.]+)" class="([^"]+)"/g)]
    .map(([, x, y, r, cls]) => ({ x: +x, y: +y, r: +r, cls }));
}

const bounces = (svg) => circles(svg).filter((c) => c.cls.startsWith("ct-bounce"));
const lastBounce = (tokens, court) => bounces(rallySvg(tokens, court)).at(-1);

describe("rallySvg structure", () => {
  it("returns an svg document", () => {
    const svg = rallySvg(["svW", "Bd2"]);
    assert.ok(svg.startsWith("<svg"));
    assert.ok(svg.trimEnd().endsWith("</svg>"));
    assert.match(svg, /viewBox="[\d\s.]+"/);
  });

  it("draws one segment per stroke", () => {
    for (const [tokens, n] of [[["svW"], 1], [["svT", "Bd2"], 2],
                               [["svT", "Bd2", "Fd1", "Bs3"], 4]]) {
      assert.equal(segments(rallySvg(tokens)).length, n, tokens.join(","));
    }
  });

  it("draws nothing at all for a sequence with no shots in it", () => {
    assert.equal(rallySvg([]), "");
  });

  it("runs each ball from the contact that struck it to the one that answered it", () => {
    // Every kink is a player meeting the ball, so consecutive segments share an endpoint.
    // A gap between them would be a ball that teleported.
    const segs = segments(rallySvg(["svT", "Bd2", "Fd1", "Bs3"]));
    for (let i = 1; i < segs.length; i++) {
      assert.equal(segs[i].x1, segs[i - 1].x2);
      assert.equal(segs[i].y1, segs[i - 1].y2);
    }
  });
});

describe("where the ball lands", () => {
  it("mirrors a zone across the net", () => {
    // Zone 1 is a righty's forehand corner. The two ends face opposite ways, so it is
    // screen-left in the far half and screen-right in the near one — the single most
    // consequential rule here, because getting it wrong mirrors the whole drawing.
    const near = lastBounce(["svT", "Bd1"]);              // lands in the near half
    const far = lastBounce(["svT", "Bd1", "Fd1"]);        // the same zone, far half
    assert.ok(near.y > NET, "the return lands in the near half");
    assert.ok(far.y < NET, "the reply lands in the far half");
    assert.ok(near.x > LANE_MID, `zone 1 near is screen-right: ${near.x}`);
    assert.ok(far.x < LANE_MID, `zone 1 far is screen-left: ${far.x}`);
    // And zone 3 is zone 1's opposite in the same half.
    assert.ok(lastBounce(["svT", "Bd3"]).x < LANE_MID);
  });

  it("sends a serve diagonally, and mirrors the two courts about the centre", () => {
    const deuce = bounces(rallySvg(["svW", "Bd2"]))[0];
    const ad = bounces(rallySvg(["svW", "Bd2"], "ad"))[0];
    assert.ok(deuce.x < LANE_MID, "the deuce court plays into the left box");
    assert.ok(ad.x > LANE_MID, "the ad court plays into the right box");
    assert.equal(deuce.x + ad.x, 2 * LANE_MID);
    assert.equal(deuce.y, ad.y);
  });

  it("lands a drop shot short and a lob deep", () => {
    const drop = lastBounce(["svT", "Fp2"]).y;
    const drive = lastBounce(["svT", "Fd2"]).y;
    const lob = lastBounce(["svT", "Fl2"]).y;
    // All three are the second stroke, so all three land in the same half.
    for (const y of [drop, drive, lob]) assert.ok(y > NET);
    assert.ok(drop < drive && drive < lob, `${drop} < ${drive} < ${lob}`);
    assert.ok(drop - NET < 0.25 * HALF, "a drop shot dies near the net");
    assert.ok(lob - NET > 0.85 * HALF, "a lob lands on the baseline");
  });
});

describe("where the player was standing", () => {
  it("puts the server behind their own baseline", () => {
    // The one thing in the drawing every viewer can check against tennis.
    const served = segments(rallySvg(["svT", "Bd2"]))[0];
    assert.ok(served.y1 > BOTTOM, `struck from inside the court: ${served.y1}`);
  });

  it("anchors a sequence that opens mid-rally just inside the baseline instead", () => {
    // Those tokens are a lead-up with no serve, so there is no real origin to draw from —
    // and the difference from a serve is what tells the two apart.
    const mid = segments(rallySvg(["Fd1", "Bd3"]))[0];
    assert.ok(mid.y1 < BOTTOM, `mid-rally openings start inside: ${mid.y1}`);
  });

  it("never draws a volleyed ball reaching the ground", () => {
    // The ball a volley answers did not bounce, so the incoming line stops where it was
    // intercepted, short of where it was aimed. Same rally, one stroke changed.
    const drive = segments(rallySvg(["svT", "Bd2", "Fd1"]))[1];
    const volley = segments(rallySvg(["svT", "Bd2", "Fv1"]))[1];
    assert.equal(volley.y1, drive.y1);                   // struck from the same place
    assert.ok(volley.y2 < drive.y2, "cut off before the drive's contact");
    assert.ok(volley.y2 > NET, "and met in its own half");
  });
});

describe("the marks the drawing leaves", () => {
  it("rings the serve's landing as well as the last ball's, once the rally runs on", () => {
    // A serve read only off the angle of a line running on to the returner does not read
    // as a serve: the drawing needs the spot in the box. An ace has no rally to run on to.
    assert.equal(bounces(rallySvg(["svW"])).length, 1);
    assert.equal(bounces(rallySvg(["svW", "Bd2"])).length, 2);
    const serve = bounces(rallySvg(["svW", "Bd2"]))[0];
    assert.ok(serve.y < NET, "the serve landed in the receiver's half");
  });

  it("marks whose ball the sequence opens on", () => {
    // Ownership runs backwards from the end: the last token is always the ball the opponent
    // sent them, the one they attacked and the reason the sequence is in the panel. So an
    // even-length lead-up opens on the player's own stroke and an odd one on the opponent's.
    assert.equal(circles(rallySvg(["Fd1", "Bd3"]))[0].cls, "ct-player");
    assert.equal(circles(rallySvg(["Fd1", "Bd3", "Fd1"]))[0].cls, "ct-them");
  });

  it("draws the opponent's balls as incoming", () => {
    // Whose ball it is is the one thing every drawing here encodes the same way, so it is
    // never read off weight or position. The CSS draws `incoming` dashed and neutral.
    const svg = rallySvg(["Fd1", "Bd3"]);
    const [mine, theirs] = segments(svg);
    assert.ok(svg.includes(`x1="${mine.x1}"`));
    assert.equal((svg.match(/class="ct-shot incoming"/g) || []).length, 1);
    assert.ok(theirs.shot === 2);
  });
});

describe("shotLine", () => {
  it("carries direction marks unless asked not to", () => {
    const plain = shotLine(75, 176, 75, 60, {});
    const bare = shotLine(75, 176, 75, 60, { bare: true });
    const arrow = shotLine(75, 176, 75, 60, { arrow: true });
    assert.ok(plain.includes("<path"), "chevrons along the line");
    assert.ok(!bare.includes("<path"), "bare drops them");
    assert.equal((arrow.match(/<path/g) || []).length, 1, "arrow is a single head");
  });

  it("thins the marks out rather than smearing them on a cramped segment", () => {
    assert.ok(!shotLine(75, 100, 75, 101, { arrow: true }).includes("<path"));
  });

  it("labels a ball the opponent hit", () => {
    assert.match(shotLine(0, 0, 50, 50, { incoming: true }), /class="ct-shot incoming"/);
    assert.match(shotLine(0, 0, 50, 50, {}), /class="ct-shot"/);
  });
});
