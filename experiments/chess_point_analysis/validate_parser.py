"""Check the parser against the project's own pre-aggregated stat lines.

The Match Charting Project ships per-match stat totals (``stats_overview``: aces,
double faults, forehand/backhand winners and unforced errors) that the repo loads
as a validation reference. If our decoding of the point strings is right, then
re-aggregating the parsed points should reproduce those totals. This mirrors the
repo's existing "flag, don't drop" validation philosophy: we measure agreement
and surface systematic gaps rather than assume correctness.

Run: ``python experiments/chess_point_analysis/validate_parser.py [n_matches]``
"""

import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from parser import parse_point  # noqa: E402

# Parsed-outcome -> the stats_overview columns it should land in.
STAT_COLS = ["aces", "dfs", "winners", "winners_fh", "winners_bh",
             "unforced", "unforced_fh", "unforced_bh"]


def _connect():
    from match_charting_project.analysis.coverage import connect
    return connect(read_only=True)


def tally_match(points_rows) -> "dict[int, dict[str, int]]":
    """Aggregate parsed outcomes per player number (1/2) for one match."""
    acc: dict[int, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for svr, fs, ss, win in points_rows:
        p = parse_point(fs, ss, svr, win)
        side = "fh" if p.ending_side == "FH" else "bh" if p.ending_side == "BH" else None
        if p.outcome == "ace":
            acc[p.server]["aces"] += 1
        elif p.outcome == "double_fault":
            acc[p.server]["dfs"] += 1
        elif p.outcome == "winner" and p.last_hitter:
            acc[p.last_hitter]["winners"] += 1
            if side:
                acc[p.last_hitter][f"winners_{side}"] += 1
        elif p.outcome == "unforced_error" and p.last_hitter:
            acc[p.last_hitter]["unforced"] += 1
            if side:
                acc[p.last_hitter][f"unforced_{side}"] += 1
    return acc


def main(n_matches: int = 1500) -> None:
    con = _connect()
    matches = con.execute(
        f"""
        SELECT match_id, player1, player2
        FROM matches
        WHERE match_id IN (SELECT DISTINCT match_id FROM stats_overview)
        USING SAMPLE reservoir({int(n_matches)} ROWS) REPEATABLE (7)
        """
    ).fetchall()
    ids = [m[0] for m in matches]
    names = {m[0]: {1: m[1], 2: m[2]} for m in matches}

    pts = con.execute(
        "SELECT match_id, svr, first_serve, second_serve, pt_winner "
        "FROM points WHERE match_id IN ?",
        [ids],
    ).fetchall()
    by_match: dict[str, list] = defaultdict(list)
    for mid, svr, fs, ss, win in pts:
        by_match[mid].append((svr, fs, ss, win))

    stats = con.execute(
        f"SELECT match_id, player, {', '.join(STAT_COLS)} "
        "FROM stats_overview WHERE set = 'Total' AND match_id IN ?",
        [ids],
    ).fetchall()
    con.close()
    charted = {(r[0], r[1]): {c: int(r[2 + i] or 0) for i, c in enumerate(STAT_COLS)}
               for r in stats}

    # Compare parsed vs charted, per stat, summed over all matched player-rows.
    tot_charted = defaultdict(int)
    tot_abserr = defaultdict(int)
    exact = defaultdict(int)
    rows = 0
    unmatched = 0
    for mid in ids:
        parsed = tally_match(by_match.get(mid, []))
        for num, nm in names[mid].items():
            ref = charted.get((mid, nm))
            if ref is None:
                unmatched += 1
                continue
            rows += 1
            got = parsed.get(num, {})
            for c in STAT_COLS:
                # Upstream folds double faults into the unforced total and aces
                # into the winners total (verified as exact identities over the
                # whole dataset); apply the same convention so totals compare.
                if c == "unforced":
                    g = got.get("unforced", 0) + got.get("dfs", 0)
                elif c == "winners":
                    g = got.get("winners", 0) + got.get("aces", 0)
                else:
                    g = got.get(c, 0)
                r = ref[c]
                tot_charted[c] += r
                tot_abserr[c] += abs(g - r)
                exact[c] += (g == r)

    print(f"Validated {rows} player-rows across {len(ids)} matches "
          f"({unmatched} name-unmatched rows skipped)\n")
    print(f"{'stat':<14}{'charted':>9}{'abs_err':>9}{'rel_err':>9}{'exact%':>9}")
    for c in STAT_COLS:
        ch = tot_charted[c] or 1
        print(f"{c:<14}{tot_charted[c]:>9}{tot_abserr[c]:>9}"
              f"{tot_abserr[c]/ch:>8.1%}{exact[c]/max(rows,1):>9.0%}")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 1500)
