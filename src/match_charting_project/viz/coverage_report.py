"""Render the data-coverage figures to reports/figures/ (static PNGs).

Static matplotlib output keeps the repo dependency-light and the images
embeddable in a future GitHub Pages site. Interactive (Plotly) versions can be
layered on later for the web frontend.
"""

import matplotlib

matplotlib.use("Agg")  # headless: no display needed
import matplotlib.pyplot as plt  # noqa: E402

from match_charting_project.analysis import coverage  # noqa: E402
from match_charting_project.analysis.tiers import TIER_ORDER  # noqa: E402
from match_charting_project.paths import PROJECT_ROOT  # noqa: E402

FIG_DIR = PROJECT_ROOT / "reports" / "figures"
_GENDER_COLOR = {"M": "#1f77b4", "W": "#d62728"}


def _save(fig, name: str) -> str:
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    path = FIG_DIR / name
    fig.savefig(path, dpi=130, bbox_inches="tight")
    plt.close(fig)
    return str(path.relative_to(PROJECT_ROOT))


def fig_by_year(con) -> str:
    df = coverage.by_year(con)
    pivot = df.pivot(index="year", columns="gender", values="matches").fillna(0)
    fig, ax = plt.subplots(figsize=(10, 4.5))
    ax.stackplot(
        pivot.index,
        [pivot.get(g, 0) for g in ("M", "W")],
        labels=["Men", "Women"],
        colors=[_GENDER_COLOR["M"], _GENDER_COLOR["W"]],
        alpha=0.85,
    )
    ax.set_title("Matches charted per year, by gender")
    ax.set_xlabel("Year")
    ax.set_ylabel("Matches (by match date)")
    ax.legend(loc="upper left")
    ax.margins(x=0)
    return _save(fig, "coverage_by_year.png")


def fig_by_tier(con) -> str:
    df = coverage.by_tier(con)
    pivot = (
        df.pivot(index="tier", columns="gender", values="matches")
        .reindex(TIER_ORDER)
        .fillna(0)
    )
    fig, ax = plt.subplots(figsize=(9, 4.5))
    y = range(len(pivot))
    men = pivot.get("M", 0)
    women = pivot.get("W", 0)
    ax.barh(y, men, color=_GENDER_COLOR["M"], label="Men")
    ax.barh(y, women, left=men, color=_GENDER_COLOR["W"], label="Women")
    ax.set_yticks(list(y))
    ax.set_yticklabels(pivot.index)
    ax.invert_yaxis()
    ax.set_title("Matches charted by tournament tier")
    ax.set_xlabel("Matches")
    ax.legend(loc="lower right")
    return _save(fig, "coverage_by_tier.png")


def fig_year_tier(con) -> str:
    df = coverage.by_year_tier(con)
    pivot = (
        df.pivot(index="year", columns="tier", values="matches")
        .reindex(columns=TIER_ORDER)
        .fillna(0)
    )
    fig, ax = plt.subplots(figsize=(10, 4.5))
    ax.stackplot(
        pivot.index, [pivot[t] for t in TIER_ORDER], labels=TIER_ORDER, alpha=0.9
    )
    ax.set_title("Coverage by year and tier")
    ax.set_xlabel("Year")
    ax.set_ylabel("Matches")
    ax.legend(loc="upper left", fontsize=8)
    ax.margins(x=0)
    return _save(fig, "coverage_by_year_tier.png")


def fig_activity(con, months: int = 36) -> str:
    df = coverage.charting_activity(con, months=months)
    pivot = df.pivot(index="month", columns="gender", values="matches").fillna(0)
    fig, ax = plt.subplots(figsize=(10, 4))
    bottom = None
    for g in ("M", "W"):
        if g in pivot:
            ax.bar(
                pivot.index, pivot[g], bottom=bottom, width=20,
                color=_GENDER_COLOR[g], label={"M": "Men", "W": "Women"}[g],
            )
            bottom = pivot[g] if bottom is None else bottom + pivot[g]
    ax.set_title(f"Recent charting activity (last {months} months, by match date)")
    ax.set_xlabel("Month")
    ax.set_ylabel("Matches")
    ax.legend(loc="upper left")
    return _save(fig, "charting_activity.png")


def render_all(con, months: int = 36) -> list[str]:
    return [
        fig_by_year(con),
        fig_by_tier(con),
        fig_year_tier(con),
        fig_activity(con, months=months),
    ]
