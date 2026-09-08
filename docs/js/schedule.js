// When a match is due — for the half of a draw that hasn't been scheduled yet.
//
// ESPN dates every match, but one without a court and a session assigned carries a *day
// marker* rather than a start time: midnight at the venue, written in UTC. Cincinnati's
// final reads "2026-08-23T04:00Z", which is midnight EDT; a Roland Garros round would read
// "...T22:00Z" on the day *before*, which is midnight CEST. So reading a marker in UTC names
// the wrong day for every venue east of Greenwich.
//
// The day is recoverable from the marker alone, without knowing the venue's offset: local
// midnight lands in the small hours of the same UTC day when the venue is behind UTC, and in
// the evening of the day before when it is ahead. Splitting at noon separates the two, which
// holds for every offset a tour stop has ever sat at (Indian Wells at -7 through Melbourne
// at +11). Nothing has to be plumbed through from the feed.

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

// A scheduled match's start in the reader's own timezone, self-labeled: "Sun, Aug 31,
// 12:30 PM EDT". ESPN writes a real UTC start instant into `iso` at the same time it puts a
// clock time in `detail`, but `detail`'s time is always US Eastern, so a reader anywhere
// else is left converting it in their head. This reads the instant instead.
//
// It trusts `iso` only when the two agree on the wall time in Eastern. Were the feed ever to
// pair a real `detail` time with a stale day marker in `iso` (midnight at the venue), the
// marker's Eastern wall time would not match, and this falls back to ESPN's own string —
// its Eastern zone labelled exactly once, whether or not the feed already spelled it out.
// Callers pass a real `detail` here (never "TBD"): the day-only cases are theirs to handle.
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
