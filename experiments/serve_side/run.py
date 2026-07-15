"""Serve side (deuce vs ad court): descriptive splits, side vs pressure, serve+1.

Run:  python experiments/serve_side/run.py

No analysis in this repo conditions on which court a point is served to, yet the
serve-direction codes mean opposite wings on the two sides and the pressure
scores are unevenly distributed across them. This experiment derives the side
from the game score (``shots/score.py``) and reports:

  Step 1  descriptive splits per side — first-serve direction mix, first-serve-in
          rate, ace/double-fault rate, and serve-points-won on the 1st and 2nd
          serve; tour-wide and per heavily-charted player, with denominators.
  Step 2  side vs pressure — serve-points-won by leverage bucket *within* each
          side, isolating the pressure effect from the side effect (break points
          are mostly, but not only, ad-court points).
  Step 3  serve+1 — the forehand share and attempt rate of the server's first
          groundstroke, split by side, where a side split is most likely to
          change the story.

Writes reports/serve_side.md, reports/serve_side.csv,
reports/figures/serve_side.png.
"""

import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "score_aware_eval"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402
from model import pressure  # noqa: E402  (reuse the score-aware leverage buckets)

from match_charting_project.analysis.coverage import connect  # noqa: E402
from match_charting_project.paths import PROJECT_ROOT  # noqa: E402
from match_charting_project.shots.notation import SHOT_LETTERS, parse_point  # noqa: E402
from match_charting_project.shots.score import serve_side  # noqa: E402

MIN_SIDE_POINTS = 300     # per-side charting floor for a player to be ranked
MARQUEE_MIN = 2000        # a heavily-charted player's per-side floor for the tables
GLABEL = {"M": "Men", "W": "Women"}
MARQUEE = {
    "M": ["Roger Federer", "Novak Djokovic", "Rafael Nadal", "Pete Sampras", "Andre Agassi"],
    "W": ["Serena Williams", "Iga Swiatek", "Martina Navratilova", "Steffi Graf"],
}
DIRNAME = {"4": "wide", "5": "body", "6": "T"}
SIDES = ("deuce", "ad")
PBUCKETS = ("normal", "break_pt", "game_pt")   # the buckets we contrast within a side


def _first_serve_dir(fs: "str | None") -> str:
    """Direction (4/5/6) of the *first* delivery, or '?' if unknown/uncharted."""
    for ch in fs or "":
        if ch in "456":
            return ch
        if ch in SHOT_LETTERS:      # a stroke before any serve dir: nothing to read
            break
    return "?"


def _new_side() -> dict:
    return {"n": 0, "dir": defaultdict(int), "first_in": 0, "ace": 0, "df": 0,
            "s1_won": 0, "s2_n": 0, "s2_won": 0}


def collect(con, gender: str):
    """One pass: per-side counters tour-wide and per player, plus pressure & serve+1."""
    tour = defaultdict(_new_side)                              # side -> counters
    players = defaultdict(_new_side)                           # (player, side) -> counters
    press = defaultdict(lambda: [0, 0])                        # (scope, side, bucket) -> [n, won]
    sp1 = defaultdict(lambda: [0, 0, 0, 0])                    # (player, side) -> [n, fh, att, win]
    sql = (
        "SELECT m.player1, m.player2, p.svr, p.pts, p.gm1, p.gm2, "
        "       p.first_serve, p.second_serve, p.pt_winner "
        "FROM points p JOIN matches m USING (match_id) "
        "WHERE p.svr IN (1,2) AND p.pt_winner IN (1,2) AND m.gender = ?"
    )
    cur = con.execute(sql, [gender])
    while True:
        batch = cur.fetchmany(100_000)
        if not batch:
            break
        for p1, p2, svr, pts, g1, g2, fs, ss, win in batch:
            side = serve_side(pts)
            if side not in SIDES:
                continue
            pt = parse_point(fs, ss, svr, win)
            if not pt.parse_ok or pt.server_won is None:
                continue
            server = p1 if svr == 1 else p2
            won = 1 if pt.server_won else 0

            for acc in (tour[side], players[(server, side)]):
                acc["n"] += 1
                acc["dir"][_first_serve_dir(fs)] += 1
                if pt.serve_in_play == 1:
                    acc["first_in"] += 1
                    acc["s1_won"] += won
                else:
                    acc["s2_n"] += 1
                    acc["s2_won"] += won
                if pt.outcome == "ace":
                    acc["ace"] += 1
                elif pt.outcome == "double_fault":
                    acc["df"] += 1

            bucket = pressure(pts, g1, g2)
            if bucket in PBUCKETS:
                for scope in ("_tour_", server):
                    c = press[(scope, side, bucket)]
                    c[0] += 1
                    c[1] += won

            # serve+1 = the server's first groundstroke (shots: 0 serve, 1 return, 2 = +1)
            if len(pt.shots) >= 3:
                s = pt.shots[2]
                c = sp1[(server, side)]
                c[0] += 1
                c[1] += 1 if s.side == "FH" else 0
                if s.terminal in ("*", "@"):
                    c[2] += 1
                    c[3] += 1 if s.terminal == "*" else 0
    return tour, players, press, sp1


def side_rates(c: dict) -> dict:
    """Turn a side's raw counters into rates (with the denominators kept)."""
    n = c["n"]
    dirs = c["dir"]
    known = dirs["4"] + dirs["5"] + dirs["6"]
    return {
        "n": n,
        "first_in": c["first_in"] / n if n else 0.0,
        "ace": c["ace"] / n if n else 0.0,
        "df": c["df"] / n if n else 0.0,
        "s1_won": c["s1_won"] / c["first_in"] if c["first_in"] else float("nan"),
        "s2_won": c["s2_won"] / c["s2_n"] if c["s2_n"] else float("nan"),
        "s1_n": c["first_in"], "s2_n": c["s2_n"],
        "wide": dirs["4"] / known if known else float("nan"),
        "body": dirs["5"] / known if known else float("nan"),
        "t": dirs["6"] / known if known else float("nan"),
    }


def _fmt_pct(x) -> str:
    return "–" if x != x else f"{x:.0%}"   # x!=x catches NaN


def tour_table(md, tour):
    r = {s: side_rates(tour[s]) for s in SIDES}
    md.append("| side | points | 1st in | wide/body/T | ace | DF | 1st-serve won | 2nd-serve won |")
    md.append("|---|--:|--:|:-:|--:|--:|--:|--:|")
    for s in SIDES:
        v = r[s]
        md.append(f"| {s} | {v['n']:,} | {v['first_in']:.0%} | "
                  f"{_fmt_pct(v['wide'])}/{_fmt_pct(v['body'])}/{_fmt_pct(v['t'])} | "
                  f"{v['ace']:.1%} | {v['df']:.1%} | {_fmt_pct(v['s1_won'])} | "
                  f"{_fmt_pct(v['s2_won'])} |")
    md.append("")
    return r


def player_table(md, players, gender):
    md.append("| player | side | pts | 1st in | wide/T | ace | DF | 1st won | 2nd won |")
    md.append("|---|---|--:|--:|:-:|--:|--:|--:|--:|")
    for player in MARQUEE[gender]:
        rows = {s: players.get((player, s)) for s in SIDES}
        if not all(rows[s] and rows[s]["n"] >= MARQUEE_MIN for s in SIDES):
            continue
        for s in SIDES:
            v = side_rates(rows[s])
            md.append(f"| {player if s == 'deuce' else ''} | {s} | {v['n']:,} | "
                      f"{v['first_in']:.0%} | {_fmt_pct(v['wide'])}/{_fmt_pct(v['t'])} | "
                      f"{v['ace']:.1%} | {v['df']:.1%} | {_fmt_pct(v['s1_won'])} | "
                      f"{_fmt_pct(v['s2_won'])} |")
    md.append("")


def pressure_block(md, press, scope_label, scope_key):
    """Serve-points-won by leverage bucket, held within each side."""
    md.append("| side | normal | break pt | game pt | break−normal |")
    md.append("|---|--:|--:|--:|--:|")
    any_row = False
    rows = []
    for s in SIDES:
        cells = {}
        for b in PBUCKETS:
            n, won = press.get((scope_key, s, b), [0, 0])
            cells[b] = (won / n, n) if n else (float("nan"), 0)
        normal, brk = cells["normal"][0], cells["break_pt"][0]
        delta = brk - normal if (normal == normal and brk == brk) else float("nan")
        md.append(f"| {s} | {_fmt_pct(normal)} ({cells['normal'][1]:,}) | "
                  f"{_fmt_pct(brk)} ({cells['break_pt'][1]:,}) | "
                  f"{_fmt_pct(cells['game_pt'][0])} ({cells['game_pt'][1]:,}) | "
                  f"{'–' if delta != delta else f'{delta:+.0%}'} |")
        any_row = any_row or cells["normal"][1] > 0
        rows.append({"scope": scope_label, "side": s,
                     "normal_won": normal, "break_won": brk, "delta": delta,
                     "n_normal": cells["normal"][1], "n_break": cells["break_pt"][1]})
    md.append("")
    return rows if any_row else []


def sp1_block(md, sp1, gender):
    md.append("| player | side | serve+1 | FH share | attempt rate | convert |")
    md.append("|---|---|--:|--:|--:|--:|")
    rows = []
    for player in MARQUEE[gender]:
        sides = {s: sp1.get((player, s)) for s in SIDES}
        if not all(sides[s] and sides[s][0] >= MIN_SIDE_POINTS for s in SIDES):
            continue
        for s in SIDES:
            n, fh, att, win = sides[s]
            fh_share, att_rate = fh / n, att / n
            conv = win / att if att else float("nan")
            md.append(f"| {player if s == 'deuce' else ''} | {s} | {n:,} | "
                      f"{fh_share:.0%} | {att_rate:.0%} | {_fmt_pct(conv)} |")
            rows.append({"player": player, "gender": gender, "side": s, "n_serveplus1": n,
                         "fh_share": fh_share, "attempt_rate": att_rate, "convert": conv})
    md.append("")
    return rows


def main():
    con = connect(read_only=True)
    md = ["# Serve side — deuce vs ad court", ""]
    md.append("*Generated by `experiments/serve_side/run.py`. Side is derived from the "
              "game score (`shots/score.py`): every game and tiebreak opens on the deuce "
              "court, then alternates each point. First-serve **direction mix** is over "
              "serves whose target is charted; **serve-points-won** is split by which "
              "delivery started the point. Rates carry their denominators.*")
    md.append("")

    csv_rows, press_rows, sp1_rows = [], [], []
    tour_dir_mix = {}
    for g in ("M", "W"):
        tour, players, press, sp1 = collect(con, g)
        md.append(f"## {GLABEL[g]}\n")
        md.append("### Tour-wide splits\n")
        r = tour_table(md, tour)
        tour_dir_mix[g] = r
        for s in SIDES:
            v = side_rates(tour[s])
            csv_rows.append({"scope": "tour", "player": "", "gender": g, "side": s,
                             **{k: round(v[k], 4) if isinstance(v[k], float) else v[k]
                                for k in v}})

        md.append("### Heavily-charted players (both sides ≥ "
                  f"{MARQUEE_MIN:,} charted points)\n")
        player_table(md, players, g)
        for player in MARQUEE[g]:
            for s in SIDES:
                c = players.get((player, s))
                if c and c["n"] >= MIN_SIDE_POINTS:
                    v = side_rates(c)
                    csv_rows.append({"scope": "player", "player": player, "gender": g,
                                     "side": s, **{k: round(v[k], 4) if isinstance(v[k], float)
                                                   else v[k] for k in v}})

        md.append("### Step 2 — serve-points-won by leverage, within each side\n")
        md.append("*Tour-wide. Holding the side fixed and varying leverage isolates the "
                  "pressure effect from the side effect.*\n")
        press_rows += pressure_block(md, press, f"tour:{g}", "_tour_")
        md.append("Per player (break−normal on each side, the pressure swing net of side):\n")
        for player in MARQUEE[g]:
            has = any(press.get((player, s, "break_pt"), [0])[0] >= 40 for s in SIDES)
            if not has:
                continue
            md.append(f"**{player}**\n")
            press_rows += pressure_block(md, press, player, player)

        md.append("### Step 3 — serve+1 (server's first groundstroke), by side\n")
        md.append("*FH share = how often the serve+1 is a forehand; attempt = winner or "
                  "unforced error; claims stay in server-wing / side terms (no returner "
                  "handedness assumed).*\n")
        sp1_rows += sp1_block(md, sp1, g)

    con.close()

    # -- figure: the headline validation (dir mix by side) + pressure-within-side -
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(11, 4.4))
    x = range(3)
    labels = ["wide", "body", "T"]
    r = tour_dir_mix["M"]
    w = 0.38
    a1.bar([i - w / 2 for i in x], [r["deuce"][k] for k in ("wide", "body", "t")],
           width=w, label="deuce", color="#1a7f4b")
    a1.bar([i + w / 2 for i in x], [r["ad"][k] for k in ("wide", "body", "t")],
           width=w, label="ad", color="#b0512e")
    a1.set_xticks(list(x))
    a1.set_xticklabels(labels)
    a1.set_ylabel("share of charted first serves")
    a1.set_title("First-serve direction mix by side (men)")
    a1.legend(fontsize=8)

    pr = pd.DataFrame(press_rows)
    tour_pr = pr[pr.scope.str.startswith("tour")]
    if len(tour_pr):
        piv = tour_pr.pivot_table(index="side", values=["normal_won", "break_won"])
        piv = piv.reindex(SIDES)
        a2.bar([i - w / 2 for i in range(2)], piv["normal_won"], width=w,
               label="normal", color="#4c72b0")
        a2.bar([i + w / 2 for i in range(2)], piv["break_won"], width=w,
               label="break pt", color="#c44e52")
        a2.set_xticks(range(2))
        a2.set_xticklabels(SIDES)
        a2.set_ylabel("serve-points won")
        a2.set_title("Pressure within side (men+women tour)")
        a2.legend(fontsize=8)
    fig.suptitle("Serve side: direction mix validates the split; pressure holds within side")
    fig.tight_layout()
    figp = PROJECT_ROOT / "reports" / "figures" / "serve_side.png"
    figp.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(figp, dpi=110)
    plt.close(fig)

    md.append("![serve side](figures/serve_side.png)")
    md.append("")

    pd.DataFrame(csv_rows).to_csv(PROJECT_ROOT / "reports" / "serve_side.csv", index=False)
    pd.DataFrame(press_rows).to_csv(PROJECT_ROOT / "reports" / "serve_side_pressure.csv",
                                    index=False)
    pd.DataFrame(sp1_rows).to_csv(PROJECT_ROOT / "reports" / "serve_side_serveplus1.csv",
                                  index=False)
    (PROJECT_ROOT / "reports" / "serve_side.md").write_text("\n".join(md) + "\n")
    print("wrote reports/serve_side.md + .csv (+ pressure, serveplus1) + figure")


if __name__ == "__main__":
    main()
