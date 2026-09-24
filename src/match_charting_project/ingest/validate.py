"""Data-quality checks and repairs over the normalized frames.

Rows whose fields sit in the wrong columns are noise, not data. This module repairs what
can be repaired deterministically, drops what can't, and counts and names every row it
touched in the report.

Row shape is checked first and on its own terms. A row shifted two columns trips several
per-column checks at once (an umpire's name in the surface column), and the report should
name the cause, not the symptoms.
"""

import re

import pandas as pd

VALID_SURFACES = {"Hard", "Clay", "Grass", "Carpet"}
# Events outside professional tennis, dropped by name. Sound rows, but a different level of
# the sport. Age bracket decides it: the Nike Junior Tour is 12-and-under (its one charted
# match is Sinner at 12), while the junior slams (18-and-under) are kept. Median years from
# event to first charted pro match: 1.1 at Wimbledon Juniors, 1.2 at the AO, 5.4 at the Nike
# Junior Tour.
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

    ``rest`` must split into exactly four '-'-separated fields. More means a field contains
    a hyphen (e.g. "Auger-Aliassime"), and the caller drops the row rather than guess.
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

    Some upstream rows lack ``Player 1`` and ``Player 2``, so later fields shift left. The
    tell is a bare hand code in the player column. In order of preference:

    * if an intact row has the same match_id, the shifted one is dropped (most cases);
    * otherwise the row is rebuilt from its match_id;
    * otherwise (an ambiguous match_id) it is dropped.

    A rebuild restores only the five match_id fields and the two hands (R, L, U or empty).
    Everything from ``time`` onward is nulled, not shifted back: the one row that needs
    rebuilding is also missing ``Surface``, so a uniform shift would put the umpire in the
    surface column.
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

    # Rows missing only the `Surface` field shift everything after it by one (the surface
    # reads as an umpire's name, best-of as 1). Best-of feeds win probability, so those
    # fields are nulled, not realigned.
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

    Some matches appear as two consecutive runs of the same point sequence under one
    match_id. Counting both would double-weight them in every career rate, and they tend to
    be famous matches.

    The most complete chart is kept, not the newest: in two of the four matches whose charts
    differ, the second is the shorter, abandoned one. Ties keep the first, so the choice is
    stable between builds.

    Three passes, since a few matches are two charts interleaved rather than appended:

    1. keep one run per match;
    2. drop rows that repeat a point number with identical content;
    3. drop from the points table any match that still repeats a point number with
       different content.

    Step 3 drops the whole match because the two charts have drifted out of step, so the
    remaining point numbers can't be trusted either. The match row stays, and the report
    says so.
    """
    mid = points["match_id"]
    pt = pd.to_numeric(points["pt"], errors="coerce")
    new_match = ~mid.eq(mid.shift())
    # A second chart repeats the match's opening point number. Not "the number went down":
    # `pt` isn't sorted in the source (one 1975 semifinal opens 45, 47, 46, 48), and that
    # test found 2,174 double-charted matches where there are 14. The opening number isn't
    # always 1, so each match is compared with its own first row.
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
