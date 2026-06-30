"""Class-relative shot quality: rank players against their own style archetype.

The settled design (see ../class_aware_eval): keep ONE style-blind eval as the shared
currency, and put class-awareness in the *benchmark*. So: compute each player's
decision quality (avg win-probability conceded per stroke) with the general eval, then
express it as a deviation from their archetype's mean — controlling for the fact that,
e.g., aggressive shotmakers concede more by style, not necessarily by lack of skill.

Output is just ranking lists for others to slice:
  reports/class_relative_wpa.csv   one row per player, all the numbers
  reports/class_relative_wpa.md    top class-relative overperformers + best-in-class

Reuses the graduated eval + per-player quality (``match_charting_project.shots``) and
archetypes from player_styles; keyed by era entity via the ``player_eras`` layer when it
exists, so split careers are rated per era. No new modelling.
"""

import sys
from pathlib import Path

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2] / "src"))

import pandas as pd  # noqa: E402

from match_charting_project.shots.quality import player_quality  # noqa: E402
from match_charting_project.shots.winprob import WinProbModel  # noqa: E402
from match_charting_project.analysis.career_eras import load_era_map  # noqa: E402
from match_charting_project.analysis.coverage import connect  # noqa: E402
from match_charting_project.paths import PROJECT_ROOT  # noqa: E402
from match_charting_project.shots.notation import iter_parsed_points  # noqa: E402

FIT_SAMPLE = 300_000
MIN_SHOTS = 1500
CLUSTERS = PROJECT_ROOT / "reports" / "player_style_clusters.csv"


def main() -> None:
    if not CLUSTERS.exists():
        raise SystemExit("Missing reports/player_style_clusters.csv — run player_styles first.")
    clusters = pd.read_csv(CLUSTERS)[["player", "gender", "archetype"]]
    con = connect(read_only=True)
    era_map = load_era_map(con)   # keys WPA by era entity for split careers (matches clusters)

    frames = []
    for g in ("M", "W"):
        model = WinProbModel().fit(iter_parsed_points(con, where=f"gender='{g}'", sample=FIT_SAMPLE))
        q = player_quality(con, model, where=f"m.gender='{g}'", min_shots=MIN_SHOTS, era_map=era_map)
        df = q.merge(clusters[clusters.gender == g], on=["player", "gender"], how="inner")

        grp = df.groupby("archetype")["avg_wpa_lost"]
        df["archetype_mean"] = grp.transform("mean")
        df["archetype_size"] = grp.transform("size")
        std = grp.transform("std").replace(0, pd.NA)
        df["class_rel_z"] = (df["avg_wpa_lost"] - df["archetype_mean"]) / std  # <0 = better
        df["rank_overall"] = df["avg_wpa_lost"].rank(method="min").astype(int)
        df["rank_in_archetype"] = grp.rank(method="min").astype(int)
        frames.append(df)
    con.close()

    cols = ["player", "gender", "archetype", "shots", "avg_wpa_lost", "accuracy",
            "archetype_mean", "class_rel_z", "rank_overall", "rank_in_archetype",
            "archetype_size"]
    out = pd.concat(frames)[cols].round(4).sort_values(["gender", "class_rel_z"])
    out.to_csv(PROJECT_ROOT / "reports" / "class_relative_wpa.csv", index=False)

    # Brief markdown: overperformers vs their style, and the best in each archetype.
    md = ["# Class-relative shot quality\n",
          "*Decision quality (avg win-prob conceded per stroke, lower = better) measured "
          "with one style-blind eval, then compared **within each style archetype**. "
          "`class_rel_z` < 0 means a player concedes less than typical for their style — "
          "skill, not style. CSV has every player; below are the highlights.*\n"]
    for g in ("M", "W"):
        sub = out[out.gender == g]
        md.append(f"## {'Men' if g == 'M' else 'Women'}\n")
        md.append("**Best relative to their style** (most below their archetype's mean):\n")
        md.append("| player | archetype | avg_wpa_lost | z | overall rank |")
        md.append("|---|---|---|---|---|")
        for r in sub.dropna(subset=["class_rel_z"]).head(12).itertuples():
            md.append(f"| {r.player} | {r.archetype} | {r.avg_wpa_lost:.3f} | "
                      f"{r.class_rel_z:+.2f} | {r.rank_overall} |")
        md.append("\n**Best in each archetype:**\n")
        for arch, a in sub.groupby("archetype"):
            best = a.sort_values("avg_wpa_lost").iloc[0]
            md.append(f"- *{arch}* ({int(best.archetype_size)} players): "
                      f"**{best.player}** ({best.avg_wpa_lost:.3f})")
        md.append("")
    (PROJECT_ROOT / "reports" / "class_relative_wpa.md").write_text("\n".join(md))
    print(f"wrote reports/class_relative_wpa.csv ({len(out)} players) and class_relative_wpa.md")


if __name__ == "__main__":
    main()
