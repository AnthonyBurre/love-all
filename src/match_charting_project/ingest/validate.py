"""Data-quality checks and repairs over the normalized frames.

Philosophy: never *silently* drop crowdsourced rows — but a row whose fields are
in the wrong columns is not data, it is noise wearing data's shape, and carrying
it forward costs more than losing it. So this module does three things in order:
repair what can be repaired deterministically, drop what can't, and account for
every row it touched in the report. Nothing goes without being counted and named.

The distinction that matters is between a *value* being wrong and a *row* being
wrong. Per-column checks — is this a real surface, does this date parse — only
ever see the first kind. A row that has slipped two columns to the left trips
several of them at once and looks like several unrelated problems: a per-column
report says "invalid surface: {'1': 7, 'Eva Asderaki-Moore': 2}" and leaves the
reader to notice that an umpire's name in the surface column means the row is
shifted, not that the surface is unusual. So the shape of a row is checked first
and on its own terms, and the report names the cause rather than the symptoms.
"""

import re

import pandas as pd

VALID_SURFACES = {"Hard", "Clay", "Grass", "Carpet"}
# Events outside professional tennis, dropped from the corpus by name.
#
# A scope rule rather than a quality one: these rows are sound, they just describe a
# different level of the sport, and a career rate that mixes levels is measuring two
# things at once. Age bracket is what decides it, so "juniors" in a name is not the test.
#
# The Nike Junior Tour is a 12-and-under series, and its one charted match is Sinner at
# 12. The junior slams read as juniors too and are kept: they are the ITF Junior Circuit's
# 18-and-under events, the top of junior tennis, and this corpus reaches them through
# Federer, Tsitsipas, De Minaur and Raducanu. The corpus itself separates the two — median
# years from the event to the player's first charted pro match is 1.1 at Wimbledon Juniors
# and 1.2 at the AO (Shapovalov 0.1, Andreeva 0.2, Federer 0.3), 0.2 at the NCAA finals,
# and 5.4 at the Nike Junior Tour.
OUT_OF_SCOPE_TOURNAMENTS = {"nike junior tour"}
QUALIFYING_ROUNDS = {"Q1", "Q2", "Q3", "Q4"}
# A hand cell holds one of these or nothing. Their appearing in the *player*
# column is the signature of the shift below.
HAND_CODES = {"R", "L", "U"}
# match_id is "YYYYMMDD-{M|W}-Tournament_Name-Round-Player_1-Player_2", '-' between
# fields and '_' inside them — so the players can be read back out of it when the
# columns that should hold them are missing.
_MATCH_ID_RE = re.compile(r"^(?P<date>\d{8})-(?P<gender>[MW])-(?P<rest>.+)$")


# The raw match columns in file order. Repairs work on positions, not names, so the
# order is stated once here rather than inferred from whatever order a frame arrives in.
MATCH_COLS = [
    "match_id", "player1", "player2", "player1_hand", "player2_hand", "date",
    "tournament", "round", "time", "court", "surface", "umpire", "best_of",
    "final_tb", "charted_by",
]


def _parse_match_id(match_id: str) -> "dict | None":
    """Split a match_id into the five fields it encodes, or None if it's ambiguous.

    ``rest`` is ``Tournament-Round-Player_1-Player_2`` with '-' between fields, so it
    splits into exactly four. Anything else means one of those fields contains a
    hyphen of its own — a surname like "Auger-Aliassime" — and there is no way to tell
    from the string alone which hyphen is a separator. That returns None and the caller
    drops the row, because guessing is how you invent a player.
    """
    m = _MATCH_ID_RE.match(str(match_id or "").strip())
    if not m:
        return None
    parts = m["rest"].split("-")
    if len(parts) != 4 or not all(parts):
        return None
    tournament, round_, p1, p2 = parts
    return {"date": m["date"], "gender": m["gender"],
            "tournament": tournament.replace("_", " "), "round": round_,
            "player1": p1.replace("_", " "), "player2": p2.replace("_", " ")}


def repair_matches(matches: pd.DataFrame) -> "tuple[pd.DataFrame, dict]":
    """Repair or drop match rows whose fields have slipped out of their columns.

    A handful of rows in the upstream files are short: ``Player 1`` and ``Player 2``
    are absent rather than empty, so the fields after them sit to the left of where
    they belong and the reader pads the row's *end* with nulls. The tell is a bare
    hand code sitting in the player column — no one is called "R".

    Three outcomes, in order of preference:

    * the same match_id also arrives as an intact row — the shifted one is a partial
      duplicate and is dropped, losing nothing. This is what happens to most of them;
    * otherwise the row is rebuilt from its match_id, which is the one field still
      known to be in the right place;
    * otherwise — an ambiguous match_id — it is dropped, because a match with no
      players is not a match.

    What a rebuild restores is deliberately narrow: the five fields the match_id
    encodes, plus the two hands, which are self-validating (a hand cell holds R, L, U
    or nothing, so a wrong one cannot masquerade as a right one). *Everything from
    ``time`` onward is nulled rather than slid back into place.*

    That is not caution for its own sake. The obvious repair — shift every field right
    by the two missing columns — assumes the row is missing exactly those two, and the
    one row here that needs rebuilding is also missing ``Surface``, so its tail is
    displaced by three, not two. Shifted uniformly it comes out with the umpire in the
    surface column, best-of in the umpire column, and every value plausible enough to
    survive a per-column check. A repair that can silently produce that is worse than
    no repair: null says "unknown", which is true, where a positional guess says
    "Eva Asderaki", which is a surface nobody has ever played on.
    """
    df = matches.copy()
    tail = [c for c in MATCH_COLS[MATCH_COLS.index("time"):] if c in df.columns]
    p1 = df["player1"].fillna("").astype(str).str.strip().str.upper()
    shifted = p1.isin(HAND_CODES)
    rep = {"shifted_rows": int(shifted.sum()), "dropped_duplicate": [],
           "repaired": [], "dropped_unrecoverable": [], "tail_nulled": []}
    intact_ids = set(df.loc[~shifted, "match_id"])
    drop_idx = []
    for i in df.index[shifted]:
        mid = df.at[i, "match_id"]
        if mid in intact_ids:
            drop_idx.append(i)
            rep["dropped_duplicate"].append(mid)
            continue
        parsed = _parse_match_id(mid)
        if parsed is None:
            drop_idx.append(i)
            rep["dropped_unrecoverable"].append(mid)
            continue
        # The hands are where the players should be — that is what identified this row.
        hands = [str(df.at[i, c]).strip().upper() for c in ("player1", "player2")]
        for col, val in (("player1", parsed["player1"]), ("player2", parsed["player2"]),
                         ("player1_hand", hands[0] if hands[0] in HAND_CODES else None),
                         ("player2_hand", hands[1] if hands[1] in HAND_CODES else None),
                         ("date", parsed["date"]), ("tournament", parsed["tournament"]),
                         ("round", parsed["round"])):
            if col in df.columns:
                df.at[i, col] = val
        for col in tail:
            df.at[i, col] = None
        rep["repaired"].append(mid)
    if drop_idx:
        df = df.drop(index=drop_idx).reset_index(drop=True)

    # The other way these rows are damaged, and one the front-shift check cannot see:
    # a row that has all its players but is missing the `Surface` field, so everything
    # after it moves up one. Those rows read as an ordinary match until you notice the
    # surface is an umpire's name and best-of is 1 — and best-of is not decorative, it
    # feeds the win probability. Anything from the surface on is unusable, and how far
    # it has moved is unknowable (that depends on how many fields were omitted), so it
    # is nulled rather than realigned, for the reason given above.
    if "surface" in df.columns:
        surf = df["surface"].fillna("").astype(str).str.strip()
        bad = surf.ne("") & ~surf.isin(VALID_SURFACES)
        if bad.any():
            rep["tail_nulled"] = list(df.loc[bad, "match_id"])
            for col in [c for c in MATCH_COLS[MATCH_COLS.index("surface"):] if c in df.columns]:
                df.loc[bad, col] = None
    return df, rep


def drop_out_of_scope(matches: pd.DataFrame) -> "tuple[pd.DataFrame, dict]":
    """Drop matches played outside professional tennis, naming each one dropped.

    Separate from `repair_matches` because it answers a different question. That one asks
    whether a row is intact; this one asks whether an intact row belongs. Both report what
    they removed, and neither removes anything it cannot name.
    """
    tourn = matches["tournament"].fillna("").astype(str).str.strip().str.lower()
    out = tourn.isin(OUT_OF_SCOPE_TOURNAMENTS)
    rep = {"out_of_scope": [
        {"match_id": str(r.match_id), "tournament": str(r.tournament)}
        for r in matches.loc[out].itertuples()
    ]}
    return matches.loc[~out].reset_index(drop=True), rep


def dedupe_points(points: pd.DataFrame) -> "tuple[pd.DataFrame, dict]":
    """Keep one chart per match where a match has been charted more than once.

    Some matches appear in a points file as two consecutive runs of the same point
    sequence — the same match charted twice and both submissions appended under one
    match_id. Sackmann has called this useful in its own right: with few matches
    charted early on, a duplicate is how you measure how far two charters disagree
    about a subjective call like an unforced error. That is a real signal, and this
    project already reasons about it (see the serve-placement experiment's note on
    charters differing by several points on the same players).

    It is still wrong to *aggregate* over both. A match counted twice is weighted
    twice in every career rate, in the coverage counts and in the ace share, and the
    matches this happens to are not a random sample of matches — they are famous
    ones. So one chart per match goes forward.

    Which one: the most complete, not the most recent. Of the four matches here whose
    two charts genuinely differ, the second is the shorter, abandoned one in two
    cases, so "keep the newer" would throw away a full chart for a partial. Ties —
    which is every verbatim re-append — keep the first, so the choice is stable
    between builds.

    Three passes, because a few matches are not two charts appended but two charts
    *interleaved*, and taking one run does not separate those:

    1. keep one run per match, as above;
    2. drop rows that repeat a point number with byte-identical content — either copy
       will do, so this is lossless and needs no rule;
    3. whatever still repeats a point number now disagrees about it, and the match is
       dropped from the points table entirely.

    Step 3 is the whole match rather than the offending rows. The two charts behind
    these have drifted out of step — the same point number carries a different score
    and a different winner in each — so their point numbers have stopped referring to
    the same points, and cutting the rows where that is *visible* would leave a match
    whose remaining points are still silently misaligned, now with holes in it. The
    match row itself stays: the match was played and it was charted, and what is gone
    is our ability to read the chart, which is what the report says.
    """
    mid = points["match_id"]
    pt = pd.to_numeric(points["pt"], errors="coerce")
    new_match = ~mid.eq(mid.shift())
    # A second chart announces itself by repeating the match's opening point number.
    #
    # Not by failing to increase: `pt` is not sorted in the source files. One 1975
    # semifinal opens 45, 47, 46, 48 — a charter's rows as entered, not as played — so
    # "the number went down" fires thirteen times inside a single honest chart, and
    # treating each as a chart boundary found 2,174 double-charted matches where there
    # are 14. Nor is the opening number always 1, which is why this compares against
    # each match's own first row rather than a constant.
    first_pt = pt.groupby(mid).transform("first")
    restart = (pt.eq(first_pt) & ~new_match).fillna(False)
    block = (new_match | restart).cumsum()
    sizes = (points.assign(_block=block).groupby(["match_id", "_block"], sort=False)
             .size().rename("n").reset_index())
    multi = sizes.loc[sizes.duplicated("match_id", keep=False)]
    rep = {"double_charted": int(multi["match_id"].nunique()), "matches": []}
    if multi.empty:
        return points, rep
    best = (multi.sort_values(["match_id", "n", "_block"], ascending=[True, False, True])
            .groupby("match_id", as_index=False).first())
    for mid, grp in multi.groupby("match_id"):
        rep["matches"].append({
            "match_id": mid,
            "charts": [int(x) for x in grp.sort_values("_block")["n"]],
            "kept": int(best.loc[best["match_id"] == mid, "n"].iloc[0]),
        })
    keep_block = dict(zip(best["match_id"], best["_block"]))
    drop = points["match_id"].isin(keep_block) & (
        block != points["match_id"].map(keep_block))
    rep["dropped_rows"] = int(drop.sum())
    out = points.loc[~drop].reset_index(drop=True)
    return _resolve_overlaps(out, rep)


def _resolve_overlaps(points: pd.DataFrame, rep: dict) -> "tuple[pd.DataFrame, dict]":
    """Passes 2 and 3 of :func:`dedupe_points` — see its docstring for the reasoning."""
    # Two rows identical in every column are the same row recorded twice; keeping
    # either is the same answer, so no rule is needed and nothing is lost.
    exact = points.duplicated(keep="first")
    rep["exact_duplicates"] = int(exact.sum())
    out = points.loc[~exact]

    # What repeats a point number now actually disagrees about that point.
    conflict = out.duplicated(subset=["match_id", "pt"], keep=False)
    bad = sorted(out.loc[conflict, "match_id"].dropna().unique())
    rep["excluded_matches"] = [
        {"match_id": str(m), "rows": int((out["match_id"] == m).sum()),
         "conflicting_points": int(out.loc[conflict & (out["match_id"] == m), "pt"].nunique())}
        for m in bad
    ]
    if bad:
        out = out.loc[~out["match_id"].isin(bad)]
    rep["excluded_rows"] = int(len(points) - len(out) - rep["exact_duplicates"])
    return out.reset_index(drop=True), rep


def flag_matches(matches: pd.DataFrame) -> pd.DataFrame:
    """Return `matches` with added quality/derived flag columns."""
    df = matches.copy()
    df["surface_valid"] = df["surface"].isin(VALID_SURFACES)
    df["surface_clean"] = df["surface"].where(df["surface_valid"])
    df["is_qualifying"] = df["round"].isin(QUALIFYING_ROUNDS)
    df["date_valid"] = df["date"].notna()
    return df


def matches_report(matches: pd.DataFrame) -> dict:
    """Summarize match-level data-quality issues."""
    total = len(matches)
    bad_surface = matches.loc[~matches["surface"].isin(VALID_SURFACES)]
    bad_date = matches.loc[matches["date"].isna()]
    dup_ids = matches["match_id"].duplicated(keep=False)
    # A surface that is absent and a surface that is wrong are different findings, and
    # counting them together produced the report's least useful line: "invalid surface:
    # 3 (values: none)" — three rows failing a check with nothing to show for it, which
    # is what a null looks like when it is filed as a bad value.
    missing_surface = matches["surface"].isna().sum()
    return {
        "total_matches": total,
        "invalid_surface": int(len(bad_surface) - missing_surface),
        "missing_surface": int(missing_surface),
        "invalid_surface_values": (
            bad_surface["surface"].dropna().value_counts().head(10).to_dict()
        ),
        "unparseable_date": int(len(bad_date)),
        "duplicate_match_ids": int(dup_ids.sum()),
        "missing_match_id": int(matches["match_id"].isna().sum()),
    }


def points_report(points: pd.DataFrame) -> dict:
    """Summarize point-level data-quality issues."""
    dup = points.duplicated(subset=["match_id", "pt"], keep=False)
    # Which matches those are, by name. De-duplication runs before this and takes one
    # chart per match, so anything still repeating a point number is a match whose two
    # charts were *interleaved* rather than appended one after the other — and there is
    # no rule that separates those without reading them. Naming them is the point: this
    # is the short list that wants a person, not another heuristic.
    unresolved = sorted(points.loc[dup, "match_id"].dropna().unique())
    return {
        "total_points": len(points),
        "missing_match_id": int(points["match_id"].isna().sum()),
        "missing_pt_winner": int(points["pt_winner"].isna().sum()),
        "duplicate_match_pt": int(dup.sum()),
        "unresolved_matches": [str(m) for m in unresolved],
        "empty_first_serve": int((points["first_serve"].fillna("") == "").sum()),
    }


def render_markdown(m_rep: dict, p_rep: dict,
                    fix_m: "dict | None" = None, fix_p: "dict | None" = None) -> str:
    lines = ["# Data quality report", ""]
    # Repairs lead, because they are the only section that names a *cause*. The counts
    # below are symptoms, and a shifted row shows up in three of them at once.
    if fix_m and fix_m.get("out_of_scope"):
        rows = fix_m["out_of_scope"]
        lines.append("## Out of scope")
        lines.append(
            f"- **{len(rows)} match** dropped as not professional tennis "
            f"(**{fix_m.get('out_of_scope_points', 0):,}** point rows). Not a quality "
            f"finding: the rows are intact, they record a different level of the sport. "
            f"The rule is the age bracket, not the word \"juniors\" — the ITF Junior "
            f"Circuit's 18-and-under slam events are kept, and this corpus reaches them "
            f"through Federer, Tsitsipas, De Minaur and Raducanu."
        )
        for row in rows:
            lines.append(f"  - `{row['match_id']}` — {row['tournament']}")
        lines.append("")
    if fix_m or fix_p:
        lines.append("## Ingest repairs")
        if fix_m:
            lines.append(
                f"- Match rows with fields shifted out of their columns: "
                f"**{fix_m['shifted_rows']}**"
            )
            for key, label in (("dropped_duplicate", "dropped — the same match_id also "
                                "arrived intact, so nothing is lost"),
                               ("repaired", "repaired — fields realigned, players read "
                                "back out of the match_id"),
                               ("dropped_unrecoverable", "dropped — players unrecoverable")):
                ids = fix_m.get(key) or []
                lines.append(f"  - {label}: **{len(ids)}**")
                for mid in ids:
                    lines.append(f"    - `{mid}`")
            tail = fix_m.get("tail_nulled") or []
            if tail:
                lines.append(
                    f"- Match rows missing `Surface`, displacing everything after it "
                    f"(an umpire lands in the surface column, best-of reads 1): "
                    f"**{len(tail)}** — surface through charted-by nulled, since how far "
                    f"the tail moved is not knowable"
                )
                for mid in tail:
                    lines.append(f"    - `{mid}`")
        if fix_p:
            lines.append(
                f"- Matches charted more than once: **{fix_p['double_charted']}** "
                f"— one chart kept per match, **{fix_p.get('dropped_rows', 0):,}** "
                f"point rows dropped"
            )
            for row in fix_p.get("matches", []):
                charts = ", ".join(str(n) for n in row["charts"])
                note = "" if len(set(row["charts"])) == 1 else "  ← charts disagree"
                lines.append(
                    f"  - `{row['match_id']}` — charts of {charts}; "
                    f"kept {row['kept']}{note}"
                )
            if fix_p.get("exact_duplicates"):
                lines.append(
                    f"- Point rows repeating a point number with identical content: "
                    f"**{fix_p['exact_duplicates']:,}** — one copy kept, lossless"
                )
            excluded = fix_p.get("excluded_matches") or []
            if excluded:
                lines.append(
                    f"- **Excluded from analysis: {len(excluded)} match(es)** "
                    f"({fix_p.get('excluded_rows', 0):,} point rows). Two charts "
                    f"interleaved rather than appended and drifted out of step — the "
                    f"same point number carries a different score and winner in each, "
                    f"so the numbering no longer refers to the same points. The match "
                    f"rows stay; only their points are dropped."
                )
                for row in excluded:
                    lines.append(
                        f"  - `{row['match_id']}` — {row['rows']:,} rows, "
                        f"{row['conflicting_points']} point(s) in conflict"
                    )
        lines.append("")
    lines.append("## Matches")
    lines.append(f"- Total: **{m_rep['total_matches']:,}**")
    lines.append(
        f"- Invalid surface: **{m_rep['invalid_surface']}** "
        f"(values: {m_rep['invalid_surface_values'] or 'none'})"
    )
    lines.append(f"- Missing surface: **{m_rep.get('missing_surface', 0)}**")
    lines.append(f"- Unparseable date: **{m_rep['unparseable_date']}**")
    lines.append(f"- Duplicate match_ids: **{m_rep['duplicate_match_ids']}**")
    lines.append(f"- Missing match_id: **{m_rep['missing_match_id']}**")
    lines.append("")
    lines.append("## Points")
    lines.append(f"- Total: **{p_rep['total_points']:,}**")
    lines.append(f"- Missing match_id: **{p_rep['missing_match_id']}**")
    lines.append(f"- Missing pt_winner: **{p_rep['missing_pt_winner']}**")
    lines.append(f"- Duplicate (match_id, pt): **{p_rep['duplicate_match_pt']}**")
    unresolved = p_rep.get("unresolved_matches") or []
    if unresolved:
        lines.append(
            f"  - Needs review — **{len(unresolved)}** match(es) whose two charts are "
            f"interleaved rather than appended, so keeping one run does not separate "
            f"them. Every aggregate over these is counting some points twice:"
        )
        for mid in unresolved:
            lines.append(f"    - `{mid}`")
    lines.append(f"- Empty first_serve: **{p_rep['empty_first_serve']}**")
    lines.append("")
    return "\n".join(lines)
