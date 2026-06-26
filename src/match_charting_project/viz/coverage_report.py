"""Render the data-coverage figures to reports/figures/ (static PNGs).

Every figure is produced once per gender (``*_men.png`` / ``*_women.png``);
men's and women's tennis are treated as distinct throughout the project and are
never combined into a single chart. Static matplotlib output keeps the repo
dependency-light and the images embeddable in a future GitHub Pages site.
"""

import matplotlib

matplotlib.use("Agg")  # headless: no display needed
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from match_charting_project.analysis import coverage  # noqa: E402
from match_charting_project.paths import PROJECT_ROOT  # noqa: E402

FIG_DIR = PROJECT_ROOT / "reports" / "figures"
GENDERS = ("M", "W")
_GENDER_COLOR = {"M": "#1f77b4", "W": "#d62728"}
_GENDER_LABEL = {"M": "Men", "W": "Women"}
_GENDER_FILE = {"M": "men", "W": "women"}


def _save(fig, name: str) -> str:
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    path = FIG_DIR / name
    fig.savefig(path, dpi=130, bbox_inches="tight")
    plt.close(fig)
    return str(path.relative_to(PROJECT_ROOT))


def _heatmap(values, row_labels, years, title, cbar_label, fname) -> str:
    """Generic coverage heatmap: rows x years, colour = percentage (0-100).

    `values` maps (row_label, year) -> pct; missing cells render grey ("none").
    """
    grid = np.full((len(row_labels), len(years)), np.nan)
    for i, key in enumerate(row_labels):
        for j, year in enumerate(years):
            v = values.get((key, year))
            if v is not None:
                grid[i, j] = v

    cmap = plt.cm.YlGnBu.copy()
    cmap.set_bad("#ededed")  # no coverage / edition not held
    fig, ax = plt.subplots(
        figsize=(max(11, len(years) * 0.32), 0.5 * len(row_labels) + 1.9)
    )
    im = ax.imshow(np.ma.masked_invalid(grid), aspect="auto", cmap=cmap, vmin=0, vmax=100)
    ax.set_xticks(range(len(years)))
    ax.set_xticklabels(years, rotation=90, fontsize=6)
    ax.set_yticks(range(len(row_labels)))
    ax.set_yticklabels(row_labels, fontsize=8)
    for i in range(len(row_labels)):
        for j in range(len(years)):
            v = grid[i, j]
            if not np.isnan(v) and v >= 1:
                ax.text(j, i, f"{v:.0f}", ha="center", va="center",
                        fontsize=5, color="white" if v >= 55 else "#222")
    cbar = fig.colorbar(im, ax=ax, fraction=0.025, pad=0.01)
    cbar.set_label(cbar_label, fontsize=8)
    ax.set_title(title, fontsize=10)
    ax.set_xlabel("Year")
    return _save(fig, fname)


def _round_heatmap(con, gender, getter, rounds, since, title, fname) -> str:
    """Round x year coverage heatmap for one gender (mirrors the event heatmaps)."""
    full = getter(con)
    years = list(range(since, int(full["year"].max()) + 1))
    df = full[full["gender"] == gender]
    values = {(r.round, int(r.year)): r.coverage_pct for r in df.itertuples()}
    return _heatmap(
        values, list(rounds), years,
        title=title,
        cbar_label="% of the round's matches charted",
        fname=fname,
    )


# --- True coverage (charted vs. played) -------------------------------------

def fig_slam_coverage(con, gender: str) -> str:
    full = coverage.slam_coverage(con)
    years = list(range(coverage.SLAM_SINCE, int(full["year"].max()) + 1))
    df = full[full["gender"] == gender]
    values = {(r.slam, int(r.year)): r.coverage_pct for r in df.itertuples()}
    return _heatmap(
        values, list(coverage.SLAMS), years,
        title=f"Grand Slam coverage — {_GENDER_LABEL[gender]}: share of each "
              f"singles draw charted (grey = none; since {coverage.SLAM_SINCE})",
        cbar_label="% of the 127-match draw charted",
        fname=f"slam_coverage_{_GENDER_FILE[gender]}.png",
    )


def fig_slam_round_coverage(con, gender: str) -> str:
    return _round_heatmap(
        con, gender, coverage.slam_round_coverage,
        coverage.SLAM_MAIN_ROUNDS, coverage.SLAM_SINCE,
        title=f"Grand Slam coverage by round — {_GENDER_LABEL[gender]}: share of "
              f"each round charted (grey = none; since {coverage.SLAM_SINCE})",
        fname=f"slam_round_coverage_{_GENDER_FILE[gender]}.png",
    )


def fig_masters_coverage(con, gender: str) -> str:
    full = coverage.masters_coverage(con)
    years = list(range(coverage.MASTERS_SINCE, int(full["year"].max()) + 1))
    df = full[full["gender"] == gender]
    order = df.groupby("event")["charted"].sum().sort_values(ascending=False).index.tolist()
    values = {(r.event, int(r.year)): r.coverage_pct for r in df.itertuples()}
    return _heatmap(
        values, order, years,
        title=f"Masters 1000 coverage — {_GENDER_LABEL[gender]}: share of the "
              f"R16-onward matches charted (15 per draw; grey = none)",
        cbar_label="% of the 15 late-round matches charted",
        fname=f"masters_coverage_{_GENDER_FILE[gender]}.png",
    )


def fig_masters_round_coverage(con, gender: str) -> str:
    return _round_heatmap(
        con, gender, coverage.masters_round_coverage,
        coverage.MASTERS_LATE_ROUNDS, coverage.MASTERS_SINCE,
        title=f"Masters 1000 coverage by late round — {_GENDER_LABEL[gender]}: "
              f"share of each round charted (grey = none; since {coverage.MASTERS_SINCE})",
        fname=f"masters_round_coverage_{_GENDER_FILE[gender]}.png",
    )


def render_all(con) -> list[tuple[str, str, str]]:
    """Render every figure for both genders.

    Returns (section, gender, path) records so callers can group the output.
    """
    out: list[tuple[str, str, str]] = []
    for g in GENDERS:
        out.append(("slam", g, fig_slam_coverage(con, g)))
        out.append(("slam", g, fig_slam_round_coverage(con, g)))
        out.append(("masters", g, fig_masters_coverage(con, g)))
        out.append(("masters", g, fig_masters_round_coverage(con, g)))
    return out
