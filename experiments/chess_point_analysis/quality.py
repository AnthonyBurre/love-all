"""Shot quality: the chess "blunder / centipawn-loss / accuracy" idea for tennis.

Given the win-probability eval in ``winprob.py``, every stroke is a transition
between two evaluated positions. The win-probability it *added* (WPA, from the
hitter's viewpoint) is the tennis analogue of the eval swing a chess move causes.
From that we get:

- per-stroke annotation marks (``??`` blunder, ``?`` mistake, ``?!`` dubious,
  ``!`` strong) by WPA thresholds -- exactly how engines tag moves;
- an annotated point, the analogue of an annotated game;
- a per-player decision-quality score: the average win-probability *conceded*
  per stroke (the centipawn-loss analogue), plus a 0-100 "accuracy"-style score.

Honest caveat (documented, not hidden): unlike a chess engine, this has no oracle
for the best stroke. A negative WPA blends shot *selection*, *execution*, and the
pressure the opponent applied. We lean on the charted forced/unforced flag to
isolate the cleanest, most self-inflicted losses (unforced errors).
"""

import math

# WPA thresholds for engine-style annotation marks (tunable).
BLUNDER = -0.25
MISTAKE = -0.12
DUBIOUS = -0.06
STRONG = 0.20


def annotate(wpa: float) -> str:
    if wpa <= BLUNDER:
        return "??"
    if wpa <= MISTAKE:
        return "?"
    if wpa <= DUBIOUS:
        return "?!"
    if wpa >= STRONG:
        return "!"
    return ""


def render_point(model, point, names: "dict[int, str] | None" = None) -> str:
    """Render one point as an annotated 'game': stroke, eval, WPA, mark."""
    shots = model.shot_wpa(point)
    head = (f"serve {'1st' if point.serve_in_play == 1 else '2nd'} | "
            f"server=P{point.server} | outcome={point.outcome} | "
            f"won by P{point.winner_by_notation}")
    lines = [head, "-" * len(head)]
    for s in shots:
        who = (names or {}).get(s["hitter"], f"P{s['hitter']}")
        mark = annotate(s["wpa"])
        lines.append(
            f"{s['idx']:>2}. {who:<20} {s['stroke']:<18} "
            f"P(srv win)={s['v_after']:.2f}  WPA={s['wpa']:+.3f} {mark}"
        )
    return "\n".join(lines)


def find_demo_points(model, points, n: int = 3, min_len: int = 6) -> list:
    """Pick long rallies that contain a real blunder -- the best annotations."""
    scored = []
    for p in points:
        if not p.parse_ok or p.server_won is None or len(p.shots) < min_len:
            continue
        worst = min((s["wpa"] for s in model.shot_wpa(p)), default=0.0)
        if worst <= BLUNDER:
            scored.append((len(p.shots), worst, p))
    scored.sort(key=lambda t: (t[1], -t[0]))  # biggest blunder, then longest
    return [p for _, _, p in scored[:n]]


def accuracy_score(avg_loss: float, scale: float = 6.0) -> float:
    """Map average win-prob conceded per stroke to a 0-100 score (higher=better)."""
    return 100.0 * math.exp(-scale * avg_loss)


def player_quality(con, model, where: str = "", min_shots: int = 400):
    """Per-player decision quality over the points matched by ``where``.

    Returns a tidy pandas DataFrame. ``model`` should be fit on the same
    population (e.g. one gender) so the eval baseline matches.
    """
    import pandas as pd

    sql = (
        "SELECT p.svr, p.first_serve, p.second_serve, p.pt_winner, "
        "       m.player1, m.player2, m.gender "
        "FROM points p JOIN matches m USING (match_id) "
        "WHERE p.svr IN (1,2) AND p.pt_winner IN (1,2)"
    )
    if where:
        sql += f" AND {where}"

    from match_charting_project.shots.notation import parse_point

    acc: dict = {}
    for svr, fs, ss, win, p1, p2, gender in con.execute(sql).fetchall():
        point = parse_point(fs, ss, svr, win)
        if not point.parse_ok or point.server_won is None:
            continue
        names = {1: p1, 2: p2}
        for s in model.shot_wpa(point):
            name = names[s["hitter"]]
            rec = acc.setdefault(name, {
                "player": name, "gender": gender, "shots": 0,
                "loss": 0.0, "gain": 0.0, "unforced_loss": 0.0,
                "unforced": 0, "winners": 0,
            })
            loss = max(0.0, -s["wpa"])
            rec["shots"] += 1
            rec["loss"] += loss
            rec["gain"] += max(0.0, s["wpa"])
            if s["terminal"] == "@":
                rec["unforced_loss"] += loss
                rec["unforced"] += 1
            elif s["terminal"] == "*" and s["side"]:
                rec["winners"] += 1

    df = pd.DataFrame(acc.values())
    if df.empty:
        return df
    df = df[df["shots"] >= min_shots].copy()
    df["avg_wpa_lost"] = df["loss"] / df["shots"]
    df["unforced_lost_share"] = df["unforced_loss"] / df["loss"].clip(lower=1e-9)
    df["accuracy"] = df["avg_wpa_lost"].map(accuracy_score)
    return df.sort_values("avg_wpa_lost").reset_index(drop=True)
