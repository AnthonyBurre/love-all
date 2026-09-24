// When a match is due, for the part of a draw that isn't scheduled yet.
//
// An unscheduled match carries a day marker, not a start time: midnight at the venue, in UTC
// (Cincinnati's final reads "2026-08-23T04:00Z"; a Roland Garros round reads "...T22:00Z" on
// the day before). Local midnight falls early in the same UTC day west of Greenwich and in the
// evening of the day before east of it, so splitting at noon recovers the day for every tour
// stop's offset (-7 to +11) without knowing the venue.

export function venueDay(iso) {
  if (!iso) return null;
  const d = new Date(iso);
  if (isNaN(d)) return null;
  if (d.getUTCHours() >= 12) d.setUTCDate(d.getUTCDate() + 1);
  d.setUTCHours(0, 0, 0, 0);
  return d;
}

const fmt = (iso, opts) => {
  const d = venueDay(iso);
  return d ? d.toLocaleDateString([], { ...opts, timeZone: "UTC" }) : "";
};

// "Sun, Aug 23" — the bracket card, where this line shares a small box with two names and
// a score. No year: a draw on screen is one fortnight long.
export const dayShort = (iso) =>
  fmt(iso, { weekday: "short", month: "short", day: "numeric" });

// "Aug 23, 2026" — the match panel, matching how a played match already prints its date
// there, so a scheduled one and a finished one read the same way.
export const dayLong = (iso) =>
  fmt(iso, { year: "numeric", month: "short", day: "numeric" });

// A scheduled match's start in the reader's timezone, labelled: "Sun, Aug 31, 12:30 PM EDT".
// ESPN's `detail` time is always US Eastern, so this reads the UTC instant in `iso` instead,
// trusting it only when the two agree on the Eastern wall time; otherwise it falls back to
// ESPN's string with the zone labelled once. Callers never pass "TBD".
export function localStart(iso, detail) {
  const raw = (detail || "").replace(/ - /g, " · ");
  const stated = raw.match(/\d{1,2}:\d{2}\s*[AP]M/i);
  const d = iso ? new Date(iso) : null;
  if (d && !isNaN(d) && stated) {
    const norm = (s) => s.replace(/\s+/g, " ").trim().toUpperCase();
    const eastern = norm(d.toLocaleTimeString("en-US",
      { timeZone: "America/New_York", hour: "numeric", minute: "2-digit" }));
    if (norm(stated[0]) === eastern)
      return d.toLocaleString([], { weekday: "short", month: "short", day: "numeric",
        hour: "numeric", minute: "2-digit", timeZoneName: "short" });
  }
  return /\b(ET|EDT|EST)\b/i.test(raw) ? raw : `${raw} ET`;
}
