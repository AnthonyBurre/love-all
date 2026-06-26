"""Catalog of source files in the Match Charting Project GitHub repo."""

from dataclasses import dataclass
from pathlib import Path

RAW_BASE = (
    "https://raw.githubusercontent.com/"
    "JeffSackmann/tennis_MatchChartingProject/master"
)
# Owner/repo used for the GitHub API (provenance / freshness lookups).
REPO = "JeffSackmann/tennis_MatchChartingProject"

GENDERS = ("m", "w")
POINT_DECADES = ("to-2009", "2010s", "2020s")

# Every pre-aggregated stats table the project publishes.
STATS_DATASETS = (
    "Overview", "ServeBasics", "ServeDirection", "ServeInfluence", "Rally",
    "ReturnOutcomes", "ReturnDepth", "KeyPointsServe", "KeyPointsReturn",
    "NetPoints", "ShotTypes", "ShotDirection", "ShotDirOutcomes", "SnV",
    "SvBreakSplit", "SvBreakTotal",
)
# The subset pulled by default ("core"): cheap, and useful as a validation
# reference for stats we derive ourselves from the raw points.
CORE_STATS = ("Overview",)


@dataclass(frozen=True)
class Source:
    category: str  # "matches" | "points" | "stats"
    gender: str    # "m" | "w"
    key: str       # decade or stats-name; "" for matches
    filename: str

    @property
    def url(self) -> str:
        return f"{RAW_BASE}/{self.filename}"

    @property
    def local_path(self) -> Path:
        from match_charting_project.paths import RAW_DIR

        return RAW_DIR / self.filename


def all_sources(what: str = "core") -> list[Source]:
    """Return the list of source files to fetch.

    what="core" -> matches + points + CORE_STATS
    what="all"  -> matches + points + every STATS_DATASETS table
    """
    stats = STATS_DATASETS if what == "all" else CORE_STATS
    sources: list[Source] = []
    for gender in GENDERS:
        sources.append(
            Source("matches", gender, "", f"charting-{gender}-matches.csv")
        )
        for decade in POINT_DECADES:
            sources.append(
                Source(
                    "points",
                    gender,
                    decade,
                    f"charting-{gender}-points-{decade}.csv",
                )
            )
        for name in stats:
            sources.append(
                Source(
                    "stats", gender, name, f"charting-{gender}-stats-{name}.csv"
                )
            )
    return sources
