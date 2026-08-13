"""Match ESPN player names to the Match Charting player universe + per-player coverage.

Both datasets use "First Last" names; the differences are accents, punctuation, and the
odd transliteration. Normalize aggressively, match exact-on-normalized, then fall back to
a fuzzy match. Misses simply read as "no charted history" on the site — which is exactly
the message that drives the "go contribute" call to action.
"""

import re
import unicodedata
from difflib import get_close_matches

# Known ESPN → MCP name fixes (normalized ESPN name -> canonical MCP name). Extend as found.
_OVERRIDES: dict = {}


def normalize(name: str) -> str:
    s = unicodedata.normalize("NFKD", name or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower().replace(".", " ").replace("-", " ")
    s = re.sub(r"[^a-z ]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


# Tournament name -> stable key, so the charted DB (dirty names like 'Wimbledon ') and the
# ESPN feed ('Wimbledon', 'French Open') agree. Both build paths must key through this.
# The Canadian Open alternates cities by tour and year, and the db carries all three
# spellings ('Canada Masters', 'Montreal', 'Toronto') — collapse them onto one key.
_TOURN_ALIASES = {"french open": "roland garros",
                  "us open tennis championships": "us open",
                  "montreal": "canada", "toronto": "canada"}


def tourn_key(name: str) -> str:
    """Stable key for a tournament name *or* an ESPN venue city.

    The charted db names events by city ('Washington', 'Cincinnati', sometimes with a
    'Masters' suffix); the live feed names them by sponsor ('Mubadala DC Open'). Callers
    key through this from both sides — and for the feed, off the venue city rather than
    the event name, since only the city is a word the db would recognize.
    """
    k = re.sub(r"\s+", " ", re.sub(r"\bmasters\b", " ", normalize(name))).strip()
    return _TOURN_ALIASES.get(k, k or normalize(name))


def universe_from_rows(rows) -> dict:
    """Build ``gender -> {normalized_name: canonical name}`` from (gender, player) rows."""
    uni: dict = {"M": {}, "W": {}}
    for g, p in rows:
        if g in uni and p:
            uni[g][normalize(p)] = p
    return uni


def player_universe(con) -> dict:
    """``gender -> {normalized_name: canonical MCP name}`` from the main matches table."""
    return universe_from_rows(con.execute(
        "SELECT DISTINCT gender, player FROM ("
        "  SELECT gender, player1 AS player FROM matches "
        "  UNION ALL SELECT gender, player2 FROM matches) WHERE player IS NOT NULL"
    ).fetchall())


def match_player(name: str, gender: str, universe: dict, cutoff: float = 0.88) -> "str | None":
    """Canonical MCP name for an ESPN name, or None if there's no charted history."""
    norm = normalize(name)
    table = universe.get(gender, {})
    if norm in _OVERRIDES:
        return _OVERRIDES[norm]
    if norm in table:
        return table[norm]
    close = get_close_matches(norm, list(table), n=1, cutoff=cutoff)
    return table[close[0]] if close else None


# One player's charted matches, as rows to aggregate. Written once because ``coverage`` and
# ``coverage_by_year`` are the same count at two resolutions, and two copies of the
# player1/player2 union is how the totals and the per-year breakdown come to disagree.
_COVERAGE_ROWS = (
    "WITH mp AS (SELECT match_id, count(*) n FROM points WHERE svr IN (1,2) GROUP BY match_id), "
    "     played AS ("
    "  SELECT gender, player1 AS player, match_id, year FROM matches "
    "  UNION ALL SELECT gender, player2, match_id, year FROM matches) "
    "SELECT {cols} FROM played JOIN mp USING (match_id) GROUP BY {keys}"
)


def coverage(con) -> dict:
    """``(gender, canonical player) -> {'matches', 'points', 'year_min', 'year_max'}`` charted."""
    rows = con.execute(_COVERAGE_ROWS.format(
        cols="gender, player, count(*) AS matches, sum(n) AS points, "
             "min(year) AS year_min, max(year) AS year_max",
        keys="gender, player")).fetchall()
    return {(g, p): {"matches": int(mt), "points": int(pts),
                     "year_min": int(y0), "year_max": int(y1)}
            for g, p, mt, pts, y0, y1 in rows}


def coverage_by_year(con):
    """The same counts cut by calendar year: one row per ``(gender, player, year)``.

    Charting is not spread evenly over a career — a player picks up volunteers when they
    start winning and loses them when they stop, and the corpus as a whole has grown — so
    "61 matches, 2015–2024" can be sixty matches in one season or six a year for ten. The
    panel draws this so a reader can tell which, and so two players' spans can be compared
    on one axis rather than as two date ranges to hold in the head.

    Years with no charted match are simply absent; the renderer fills the gaps, since only
    it knows the axis it is filling them across.

    Matches with no year are dropped rather than bucketed into an "unknown" slot. There are
    ten of them in a corpus of ~11,600 — the column-shifted rows the ingest report already
    names, whose date and tournament came through null — and a match that cannot be placed on
    a calendar cannot be drawn on a time axis. ``coverage`` above already leaves them out of
    ``year_min``/``year_max`` for the same reason, since ``min``/``max`` skip nulls, so this
    keeps the breakdown agreeing with the span it is drawn under. It does mean the bars sum to
    marginally fewer matches than the total beside them; at 0.09% of the corpus that is below
    the resolution of anything drawn here.
    """
    return con.execute(_COVERAGE_ROWS.format(
        cols="gender, player, year, count(*) AS matches, sum(n) AS points",
        keys="gender, player, year") + " HAVING year IS NOT NULL").fetchall()
