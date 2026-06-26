"""Lightweight data-quality checks over the normalized frames.

Philosophy: never silently drop crowdsourced rows. We *flag* problems (adding
boolean columns during the build) and produce a human-readable report so issues
are visible and tracked rather than hidden.
"""

import pandas as pd

VALID_SURFACES = {"Hard", "Clay", "Grass", "Carpet"}
QUALIFYING_ROUNDS = {"Q1", "Q2", "Q3", "Q4"}


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
    return {
        "total_matches": total,
        "invalid_surface": int(len(bad_surface)),
        "invalid_surface_values": (
            bad_surface["surface"].value_counts().head(10).to_dict()
        ),
        "unparseable_date": int(len(bad_date)),
        "duplicate_match_ids": int(dup_ids.sum()),
        "missing_match_id": int(matches["match_id"].isna().sum()),
    }


def points_report(points: pd.DataFrame) -> dict:
    """Summarize point-level data-quality issues."""
    dup = points.duplicated(subset=["match_id", "pt"], keep=False)
    return {
        "total_points": len(points),
        "missing_match_id": int(points["match_id"].isna().sum()),
        "missing_pt_winner": int(points["pt_winner"].isna().sum()),
        "duplicate_match_pt": int(dup.sum()),
        "empty_first_serve": int((points["first_serve"].fillna("") == "").sum()),
    }


def render_markdown(m_rep: dict, p_rep: dict) -> str:
    lines = ["# Data quality report", ""]
    lines.append("## Matches")
    lines.append(f"- Total: **{m_rep['total_matches']:,}**")
    lines.append(
        f"- Invalid surface: **{m_rep['invalid_surface']}** "
        f"(values: {m_rep['invalid_surface_values'] or 'none'})"
    )
    lines.append(f"- Unparseable date: **{m_rep['unparseable_date']}**")
    lines.append(f"- Duplicate match_ids: **{m_rep['duplicate_match_ids']}**")
    lines.append(f"- Missing match_id: **{m_rep['missing_match_id']}**")
    lines.append("")
    lines.append("## Points")
    lines.append(f"- Total: **{p_rep['total_points']:,}**")
    lines.append(f"- Missing match_id: **{p_rep['missing_match_id']}**")
    lines.append(f"- Missing pt_winner: **{p_rep['missing_pt_winner']}**")
    lines.append(f"- Duplicate (match_id, pt): **{p_rep['duplicate_match_pt']}**")
    lines.append(f"- Empty first_serve: **{p_rep['empty_first_serve']}**")
    lines.append("")
    return "\n".join(lines)
