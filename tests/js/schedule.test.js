// When a scheduled match is due, in the reader's timezone rather than ESPN's.
//
// Two feed quirks meet in this module, and both are the kind that look right from one desk
// and wrong from another:
//
//   * A match with no court and session assigned carries a *day marker* rather than a start
//     time: midnight at the venue, written in UTC. Read as UTC it names the wrong day for
//     every venue east of Greenwich — a Roland Garros round reads as the day before.
//   * A match that does have a time carries it in `detail`, always in US Eastern. A reader
//     anywhere else is left converting in their head.
//
// `localStart` trusts the real instant only when `detail` agrees with it on the Eastern
// wall time, and falls back to ESPN's own string otherwise. The suite pins the branch
// production actually takes, which needs the two to agree — the shape the live feed sends
// (`2026-09-03T21:00Z` with `9/3 - 5:00 PM EDT`), not a bare time with no instant.
//
// Run under TZ=UTC (see package.json) so the reader's zone is fixed and the converted
// output is a constant rather than whatever the machine is set to.

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { dayLong, dayShort, localStart, venueDay } from "../../docs/js/schedule.js";

const iso = (d) => d.toISOString().slice(0, 10);

describe("venueDay", () => {
  // Local midnight lands in the small hours of the same UTC day when the venue is behind
  // UTC, and in the evening of the day before when it is ahead. Splitting at noon separates
  // the two without knowing the offset. Every offset a tour stop has sat at:
  const markers = [
    ["Indian Wells", "-7", "2026-03-11T07:00Z", "2026-03-11"],
    ["Cincinnati",   "-4", "2026-08-23T04:00Z", "2026-08-23"],
    ["London",       "+1", "2026-07-05T23:00Z", "2026-07-06"],
    ["Roland Garros","+2", "2026-05-25T22:00Z", "2026-05-26"],
    ["Melbourne",   "+11", "2026-01-19T13:00Z", "2026-01-20"],
  ];

  for (const [venue, offset, marker, day] of markers) {
    it(`names the venue's own day at ${venue} (UTC${offset})`, () => {
      assert.equal(iso(venueDay(marker)), day);
    });
  }

  it("reads a marker just either side of noon the two different ways", () => {
    // The split itself. 11:59Z is still the same UTC day; 12:00Z is the evening before the
    // day it belongs to, and rolls forward.
    assert.equal(iso(venueDay("2026-06-01T11:59Z")), "2026-06-01");
    assert.equal(iso(venueDay("2026-06-01T12:00Z")), "2026-06-02");
  });

  it("has nothing to say about a missing or unreadable marker", () => {
    assert.equal(venueDay(null), null);
    assert.equal(venueDay(""), null);
    assert.equal(venueDay("soon"), null);
  });
});

describe("dayShort and dayLong", () => {
  it("print the venue's day, not the UTC one", () => {
    // 22:00Z on the 25th is midnight on the 26th in Paris. The bracket card and the panel
    // must agree, and both must say the 26th.
    assert.match(dayShort("2026-05-25T22:00Z"), /26/);
    assert.match(dayLong("2026-05-25T22:00Z"), /26/);
    assert.ok(!dayShort("2026-05-25T22:00Z").includes("25"));
  });

  it("differ only in whether they carry the year", () => {
    // A draw on screen is one fortnight long, so the card drops the year; the panel keeps
    // it, to read the same way as a finished match's date printed in the same place.
    assert.ok(!dayShort("2026-08-23T04:00Z").includes("2026"));
    assert.ok(dayLong("2026-08-23T04:00Z").includes("2026"));
  });

  it("print nothing rather than an error when there is no date", () => {
    assert.equal(dayShort(null), "");
    assert.equal(dayLong(null), "");
    assert.equal(dayShort("soon"), "");
  });
});

describe("localStart", () => {
  // The shape the live feed actually sends for a scheduled match.
  const START = "2026-09-03T21:00Z";
  const DETAIL = "9/3 - 5:00 PM EDT";

  it("converts the instant when the feed's two times agree", () => {
    // 21:00Z is 5:00 PM in New York, so the instant is trustworthy and gets read in the
    // reader's zone — here UTC, so 9:00 PM, with the zone named so nobody has to guess.
    const out = localStart(START, DETAIL);
    assert.match(out, /9:00 PM|9:00 PM/);
    assert.match(out, /UTC/);
    assert.ok(!out.includes("5:00"), `still showing Eastern: ${out}`);
  });

  it("falls back to ESPN's string when the instant disagrees with it", () => {
    // A real time paired with a stale day marker: midnight at the venue is not 5:00 PM in
    // New York, so the instant is not the start and must not be rendered as one.
    assert.equal(localStart("2026-09-03T04:00Z", DETAIL), "9/3 · 5:00 PM EDT");
  });

  it("falls back when there is no instant to check against", () => {
    assert.equal(localStart(null, DETAIL), "9/3 · 5:00 PM EDT");
    assert.equal(localStart("", DETAIL), "9/3 · 5:00 PM EDT");
    assert.equal(localStart("soon", DETAIL), "9/3 · 5:00 PM EDT");
  });

  it("labels the zone exactly once, however the feed wrote it", () => {
    // The fallback prints ESPN's Eastern clock time, so it has to say Eastern — and must
    // not say it twice when the feed already did.
    assert.equal(localStart(null, "8/31 - 12:30 PM"), "8/31 · 12:30 PM ET");
    assert.equal(localStart(null, "8/31 - 12:30 PM EDT"), "8/31 · 12:30 PM EDT");
    assert.equal(localStart(null, "8/31 - 12:30 PM EST"), "8/31 · 12:30 PM EST");
    assert.equal(localStart(null, "8/31 - 12:30 PM ET"), "8/31 · 12:30 PM ET");
  });

  it("separates with the middot the rest of the page separates with", () => {
    // ESPN's hyphen becomes the middot so the header's chrome lines punctuate alike.
    assert.ok(!localStart(null, DETAIL).includes(" - "));
    assert.ok(localStart(null, DETAIL).includes(" · "));
  });
});
