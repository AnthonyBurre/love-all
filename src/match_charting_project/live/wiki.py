"""Draw sheets and tour calendars from Wikipedia — the structural feed ESPN doesn't have.

ESPN gives scores but no draw: no slot positions, no seeds, nothing (verified against the
scoreboard, the core API's event/competition/competitor objects, and ``/bracket``,
``/draws``, ``/rounds``, which all 404). The sources that *do* carry draw structure are
licensed feeds — Sportradar sells it, Sofascore reverse-engineered it and TLS-fingerprints
every non-browser client.

Wikipedia's per-event draw pages carry the same thing in the open: ``{{16TeamBracket}}``
templates whose parameters are *positional*, which is precisely a draw sheet.

    RD1-seed01=1     RD1-team01='''{{flagicon|AUS}} [[Alex de Minaur|A de Minaur]]'''
    RD1-seed02=WC    RD1-team02={{flagicon|GRE}} [[Stefanos Tsitsipas|S Tsitsipas]]

Blocks appear in draw order under ``==Draw==`` — "Top half"/"Bottom half" for a 32, eight
"Section N" blocks for a slam's 128 — so concatenating them yields the full round-1 slot
order, with seeds and entry tags (``1``, ``Q``, ``WC``, ``LL``) already in the shape our
fixtures use.

**This is crowdsourced data.** It is usually right and occasionally stale — the men's
Washington calendar row claimed a 48-player field when the draw was 32. So nothing here is
trusted blindly: the consumer validates a parsed draw against the live feed and falls back
to name inference if it doesn't fit, and the site labels what came from here so a reader who
spots an error can go fix it at the source.
"""

import json
import re
import urllib.parse
import urllib.request

from match_charting_project.live import UA

API = "https://en.wikipedia.org/w/api.php"
# Wikipedia asks for a descriptive UA; anonymous API reads need no key.

BYE = "Bye"


def page_url(page: str) -> str:
    """The human URL for a page title — what we point a reader at to fix the data."""
    return "https://en.wikipedia.org/wiki/" + urllib.parse.quote(page.replace(" ", "_"))


def _api(**params) -> "dict | None":
    qs = "&".join(f"{k}={urllib.parse.quote(str(v))}" for k, v in params.items())
    req = urllib.request.Request(f"{API}?{qs}", headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=25) as r:
        doc = json.load(r)
    return None if "error" in doc else doc.get("parse")


def fetch_wikitext(page: str, section: "int | str | None" = None) -> "str | None":
    """Raw wikitext for a page title, or None if the title doesn't exist.

    ``section`` limits the fetch to one section, which matters on the season pages: their
    Key legend and end-of-year statistics mention every tier and every Grand Slam, so
    reading the whole page turns a legend bullet into a phantom tournament.
    """
    params = dict(action="parse", page=page, prop="wikitext",
                  format="json", formatversion=2, redirects=1)
    if section is not None:
        params["section"] = section
    doc = _api(**params)
    return doc.get("wikitext") if doc else None


def find_section(page: str, name: str) -> "str | None":
    """The section index whose heading equals ``name``, for use with ``fetch_wikitext``."""
    doc = _api(action="parse", page=page, prop="sections",
               format="json", formatversion=2, redirects=1)
    if not doc:
        return None
    for s in doc.get("sections", []):
        if s.get("line", "").strip().lower() == name.strip().lower():
            return s.get("index")
    return None


# --- wiki markup -----------------------------------------------------------------------

_FLAG = re.compile(r"\{\{\s*flagicon\s*\|[^}]*\}\}", re.I)
_LINK = re.compile(r"\[\[\s*([^\]|]+?)\s*(?:\|[^\]]*)?\]\]")
_COMMENT = re.compile(r"<!--.*?-->", re.S)
_TAG = re.compile(r"<[^>]+>")


_DISAMBIG = re.compile(r"\s*\([^)]*\)\s*$")
# Standard entry routes. Preferred over rarer markers when a cell carries several, so
# "Alt/LL" reads as the lucky loser it describes.
_SEED_TAGS = ("Q", "WC", "LL", "PR", "SE")


def clean_player(raw: str) -> str:
    """A player name out of a bracket cell.

    Cells wrap the name in a flag, bold-for-winner, and a piped link whose *display* text
    is abbreviated. The link target is the full name, so prefer it: ``[[Alex de
    Minaur|A de Minaur]]`` -> ``Alex de Minaur``. Wikipedia's disambiguating suffixes are
    article-title bookkeeping, not part of the name — ``Tommy Paul (tennis)`` and ``Martin
    Damm (born 2003)`` are "Tommy Paul" and "Martin Damm", which is also what the feed calls
    them.
    """
    s = _COMMENT.sub("", raw or "")
    link = _LINK.search(s)
    if link:
        return _DISAMBIG.sub("", re.sub(r"\s+", " ", link.group(1)).strip())
    s = _FLAG.sub("", s).replace("'''", "").replace("''", "")
    s = _TAG.sub(" ", s).replace("&nbsp;", " ")
    return re.sub(r"\s+", " ", s).strip()


def clean_seed(raw: str) -> "str | None":
    """A seed or entry tag (``1``, ``Q``, ``WC``, ``LL``), or None when unseeded.

    A cell can carry more than one, slash-separated and sometimes wrapped in markup:
    ``<small>2/WC</small>`` is a seeded wildcard, ``Alt/LL`` a lucky loser who was also an
    alternate. A seed number always wins — that's what a bracket badge shows — and
    otherwise the standard route wins over rarer markers.
    """
    s = _COMMENT.sub("", raw or "").replace("&nbsp;", " ")
    s = _FLAG.sub("", s).replace("'''", "")
    s = _TAG.sub(" ", s)
    tokens = [t for t in re.split(r"[^A-Za-z0-9]+", s) if t]
    for t in tokens:
        if t.isdigit():
            return t
    for t in tokens:
        if t.upper() in _SEED_TAGS:
            return t.upper()
    return tokens[0].upper() if tokens else None


# --- draw pages ------------------------------------------------------------------------

_DRAW_HEAD = re.compile(r"^==\s*Draw\s*==\s*$", re.M | re.I)
_L2_HEAD = re.compile(r"^==[^=].*?==\s*$", re.M)
_BRACKET = re.compile(r"\{\{\s*(\d+)TeamBracket[^\s|}]*", re.I)


def draw_section(text: str) -> str:
    """Just the main ``==Draw==`` section — keeps the qualifying draws out of the slots."""
    head = _DRAW_HEAD.search(text or "")
    if not head:
        return text or ""
    rest = text[head.end():]
    nxt = _L2_HEAD.search(rest)
    return rest[:nxt.start()] if nxt else rest


def _split_params(body: str) -> "list[str]":
    """Split a template body on its top-level ``|`` separators.

    Naive splitting breaks immediately: a cell reads
    ``'''{{flagicon|AUS}} [[Alex de Minaur|A de Minaur]]'''`` and both of those inner pipes
    belong to nested markup, not to the template. So track ``{{}}`` and ``[[]]`` depth and
    only cut at depth zero.
    """
    depth = {"{{": 0, "[[": 0}
    opens = {"{{": "}}", "[[": "]]"}
    parts, buf = [], []
    i = 0
    while i < len(body):
        two = body[i:i + 2]
        nested = next((o for o, c in opens.items() if two in (o, c)), None)
        if nested:
            depth[nested] += 1 if two == nested else -1
            buf.append(two)
            i += 2
        elif body[i] == "|" and not any(depth.values()):
            parts.append("".join(buf))
            buf = []
            i += 1
        else:
            buf.append(body[i])
            i += 1
    parts.append("".join(buf))
    return parts


def _params(block: str) -> dict:
    """``{'RD1-TEAM01': '…'}`` for one bracket template's parameters."""
    out = {}
    for part in _split_params(block):
        key, sep, val = part.partition("=")
        if not sep:
            continue
        k = key.strip().upper()
        if re.fullmatch(r"RD\d+-(?:TEAM|SEED)\d+", k):
            out[k] = val
    return out


def _blocks(section: str, size: int = 16) -> "list[str]":
    """The ``{{<size>TeamBracket…}}`` template bodies in a draw section, in document order.

    The half/section blocks carry round one; the separate ``4``/``8TeamBracket`` "Finals"
    block holds only the closing rounds, which the live feed already gives us. Each body is
    read to its balanced ``}}`` so one block can't bleed into the next.
    """
    out = []
    for m in _BRACKET.finditer(section):
        if m.group(1) != str(size):
            continue
        i, depth = m.start(), 0
        while i < len(section):
            two = section[i:i + 2]
            if two == "{{":
                depth += 1
                i += 2
            elif two == "}}":
                depth -= 1
                i += 2
                if depth == 0:
                    break
            else:
                i += 1
        out.append(section[m.start() + 2:i - 2])   # the body, without the outer {{ }}
    return out


def parse_draw(text: str, size: int = 16) -> "list[dict]":
    """Round-1 slots from a draw page's wikitext, in the fixture shape ``data/draws`` uses.

    Each entry is ``{slot, a, b, seed_a, seed_b}`` plus ``bye: True`` where the field is
    short of a power of two. A bye is written by *omitting* the round-1 pair — the entrant
    appears straight in round two — so ``RD1-team(2k-1)``/``RD1-team(2k)`` missing means
    slot k is a bye held by ``RD2-team(k)``.

    Returns [] when nothing parses (an un-started event's page is created before its draw
    is published), which the caller reads as "no fixture yet".
    """
    out: list = []
    for block in _blocks(draw_section(text), size):
        p = _params(block)
        for k in range(1, size // 2 + 1):
            a_raw, b_raw = p.get(f"RD1-TEAM{2 * k - 1:02d}"), p.get(f"RD1-TEAM{2 * k:02d}")
            a, b = clean_player(a_raw or ""), clean_player(b_raw or "")
            slot = len(out) + 1
            if a and b:
                out.append({"slot": slot, "a": a, "b": b,
                            "seed_a": clean_seed(p.get(f"RD1-SEED{2 * k - 1:02d}", "")),
                            "seed_b": clean_seed(p.get(f"RD1-SEED{2 * k:02d}", ""))})
                continue
            through = clean_player(p.get(f"RD2-TEAM{k:02d}", ""))
            if through and not (a or b):
                out.append({"slot": slot, "a": through, "b": None,
                            "seed_a": clean_seed(p.get(f"RD2-SEED{k:02d}", "")),
                            "seed_b": None, "bye": True})
            elif a or b:                    # half-filled: the draw is still being typed in
                out.append({"slot": slot, "a": a or b, "b": None,
                            "seed_a": None, "seed_b": None, "partial": True})
            else:
                out.append({"slot": slot, "a": None, "b": None,
                            "seed_a": None, "seed_b": None, "partial": True})
    return out


# --- season calendar pages -------------------------------------------------------------

# "ATP 500" / "WTA 1000"; slams are marked by their own template rather than a number.
_TIER = re.compile(r"\b(ATP|WTA)\s*(1000|500|250|125)\b")
_GRAND_SLAM = re.compile(r"\bGrand Slam\b", re.I)
_SURFACE = re.compile(r"\b(Hard|Clay|Grass|Carpet)\b\s*(\(i\))?", re.I)
_DRAW_SIZE = re.compile(r"\b(\d+)S\b")
# The draw pages we want to read later; the calendar links them, so we never guess a title.
_SINGLES = re.compile(r"\[\[\s*([^\]|]*?\bsingles)\s*(?:\|[^\]]*)?\]\]", re.I)
_WIKILINK = re.compile(r"\[\[\s*([^\]|]+?)\s*(?:\|\s*([^\]]*?)\s*)?\]\]")


_TIER_OR_SLAM = re.compile(r"\b(?:(?:ATP|WTA)\s*(?:1000|500|250|125)|Grand Slam)\b")
_CELL_START = re.compile(r"\|-|\n\s*[|!]|\|\|")


def _cell_at(text: str, pos: int) -> str:
    """The wikitable cell containing ``pos``.

    Scanning forward has to respect nesting: a cell is full of ``[[Target|Display]]`` whose
    pipes are not cell delimiters, so a naive search for the next ``|`` cuts the cell in half
    and loses the draw links that sit at its end.
    """
    starts = [m.end() for m in _CELL_START.finditer(text[:pos])]
    start = starts[-1] if starts else 0

    i, brace, brack = pos, 0, 0
    while i < len(text):
        two = text[i:i + 2]
        if two == "{{":
            brace += 1
            i += 2
        elif two == "}}":
            brace = max(0, brace - 1)
            i += 2
        elif two == "[[":
            brack += 1
            i += 2
        elif two == "]]":
            brack = max(0, brack - 1)
            i += 2
        elif brace == 0 and brack == 0 and (two == "||" or text[i] == "\n"):
            break
        else:
            i += 1
    return text[start:i]


_MONTHS = ("January", "February", "March", "April", "May", "June",
           "July", "August", "September", "October", "November", "December")
_MONTH_HEAD = re.compile(r"^=+\s*(" + "|".join(_MONTHS) + r")\s*=+\s*$", re.M | re.I)


def _month_at(text: str, pos: int) -> "int | None":
    """Month number from the nearest preceding ``===January===``-style heading."""
    heads = list(_MONTH_HEAD.finditer(text[:pos]))
    if not heads:
        return None
    return _MONTHS.index(heads[-1].group(1).title()) + 1


def parse_calendar(text: str) -> "list[dict]":
    """Events from a ``20xx ATP Tour`` / ``20xx WTA Tour`` page's schedule.

    Each schedule cell packs the event on consecutive lines — common name, city, tier,
    then surface and field sizes — and links its own per-draw pages:

        [[2026 Mubadala Citi DC Open|Washington Open]]
        [[Washington, D.C.]], United States
        ATP 500
        Hard – $2,469,450 – 48S/24Q/16D
        [[2026 Mubadala Citi DC Open – Men's singles|Singles]] – …

    Returns one dict per event with ``tier``, ``surface``, ``indoor``, ``city``, ``month``,
    ``draw_size`` and ``singles_pages``. Draw size is reported but deliberately advisory —
    the men's Washington row claims a 48-player field for a draw that is actually 32 — so
    the caller validates it against the live feed rather than trusting it. ``month`` comes
    from the enclosing month heading and exists to disambiguate a city that hosts more than
    one event a year: Rome holds both a 1000 in May and a 125 in July.
    """
    text = text or ""
    out, seen = [], {}
    # Anchor on the tier label and take the whole cell around it. Anchoring on the draw-page
    # link instead looks tidier but goes blind to every event whose draw isn't out yet — the
    # season page carried nine ATP 1000s and only the five already played had singles pages —
    # and an upcoming event's tier is exactly what the site needs to know.
    for anchor in _TIER_OR_SLAM.finditer(text):
        cell = _cell_at(text, anchor.start())
        if "<br" not in cell:
            continue                        # the Key legend: a bare tier link, no event
        tier_m, slam = _TIER.search(cell), _GRAND_SLAM.search(cell)
        if not (tier_m or slam):
            continue
        pages = [p for p in (m.group(1).strip() for m in _SINGLES.finditer(cell))
                 if "qualif" not in p.lower()]
        surf = _SURFACE.search(cell)
        size = _DRAW_SIZE.search(cell)
        links = _WIKILINK.findall(cell)
        event = (links[0][1] or links[0][0]) if links else ""
        # The city is the next <br/>-delimited line, linked or not:
        # "[[Washington, D.C.]], United States" / "Iasi, Romania".
        city, segs = "", [s for s in re.split(r"<br\s*/?>", cell) if s.strip()]
        if len(segs) > 1:
            line = _WIKILINK.sub(lambda m: m.group(1), segs[1])
            city = re.sub(r"\s+", " ", line.split(",")[0]).strip(" '|")
        if not city:
            for target, _disp in links[1:]:
                if not re.search(r"singles|doubles", target, re.I):
                    city = target.split(",")[0].strip()
                    break
        rec = seen.get(event)
        if rec is None:
            rec = {"event": event, "city": city,
                   "tier": "Grand Slam" if slam else f"{tier_m.group(1)} {tier_m.group(2)}",
                   "surface": surf.group(1).title() if surf else None,
                   "indoor": bool(surf and surf.group(2)),
                   "month": _month_at(text, anchor.start()),
                   "draw_size": int(size.group(1)) if size else None,
                   "singles_pages": []}
            seen[event] = rec
            out.append(rec)
        for page in pages:
            if page not in rec["singles_pages"]:
                rec["singles_pages"].append(page)
    return out


def is_usable(slots: "list[dict]") -> bool:
    """True when a parsed draw is complete enough to scaffold a bracket: a power-of-two
    slot count and every slot resolved (a real pairing or a bye)."""
    n = len(slots)
    if n < 2 or n & (n - 1):
        return False
    return not any(s.get("partial") for s in slots)


def feed_agreement(slots: "list[dict]", tournament) -> float:
    """Fraction of the live feed's first-round *pairings* this draw actually reproduces.

    The guard that makes a crowdsourced, search-resolved draw safe to use. Structural checks
    pass happily on a draw for the wrong event — resolving "Cincinnati Open" by search once
    returned the Australian Open's, a perfectly well-formed 64 slots. Nor is comparing the
    *set of players* enough: tour fields overlap so heavily that a slam's draw contains ~84%
    of a 500's entrants, which is far too close to the real thing to threshold against.

    Who plays whom is the discriminator. Two players share a slot in exactly one draw, so a
    wrong, stale, or vandalised page collapses to near zero while the right one scores 1.0.
    """
    from match_charting_project.live.players import normalize

    pairs = {frozenset((normalize(s["a"]), normalize(s["b"])))
             for s in slots if s.get("a") and s.get("b")}
    if not pairs or not tournament.matches:
        return 0.0

    first = min(m.round_rank for m in tournament.matches)
    live = [frozenset((normalize(m.a.name), normalize(m.b.name)))
            for m in tournament.matches if m.round_rank == first
            and all(sd.name and sd.name != "TBD" for sd in (m.a, m.b))]
    if not live:
        return 0.0
    return sum(1 for p in live if p in pairs) / len(live)
