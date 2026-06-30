"""Optional ``player_eras`` layer: split long, *genuinely evolving* careers into eras.

A long career (Federer spans 24 charted years) is one blurry "player" to every
per-player analysis, hiding real evolution. This materializes a mapping that splits
a career into eras **only when its style actually changed** — judged by whether the
chronological early-vs-late style gap exceeds the gap from random halves of the same
points (pure sampling noise). The formulation and its justification (most careers are
stable; ~36 evolve clearly; the threshold/span sensitivity) live in
``experiments/career_splits/`` and its report; this module is the reproducible
*production* version of that finding, built on demand via ``match-charting-project
eras`` so other analyses — and the web frontend — can join to it.

The result is deterministic: each player's noise estimate is seeded from their name,
so the table doesn't depend on row order.
"""

import zlib
from collections import defaultdict

import numpy as np

from match_charting_project.shots.notation import parse_point, stroke_kind

# Compact, handedness-tolerant style features (the ones likeliest to drift).
FEATURES = ["serve_wide", "serve_t", "ace_rate", "df_rate", "slice_pct", "net_pct",
            "fh_share", "avg_rally_len", "gs_winner_rate", "unforced_rate"]

MIN_ERA = 2000          # an era must clear this many charted points to be usable
MIN_SPAN_YEARS = 8      # a long career must span ≥ this many years (first → last)
MIN_CHARTED_YEARS = 4   # ...with enough distinct years for a real early/late test
NOISE_RATIO = 1.5       # split only if chronological gap > this × random-split noise
R = 200                 # random-split repeats for the noise estimate


def _vec(c: dict) -> np.ndarray:
    pts = max(c["points"], 1)
    s1 = max(c["serve1"], 1)
    sp = max(c["serve_pts"], 1)
    rally = max(c["rally"], 1)
    gs = max(c["fh"] + c["bh"], 1)
    return np.array([
        c["sv4"] / s1, c["sv6"] / s1, c["aces"] / sp, c["dfs"] / sp,
        c["slice"] / rally, c["net"] / rally, c["fh"] / gs,
        c["rlen"] / pts, c["gswin"] / pts, c["unf"] / pts,
    ])


def year_fingerprints(con, gender: str) -> dict:
    """``player -> {years, vec:{y:vec}, cnt:{y:n}, total}`` style vectors per year."""
    acc: dict = defaultdict(lambda: defaultdict(lambda: defaultdict(float)))
    sql = (
        "SELECT m.player1, m.player2, m.year, p.svr, p.first_serve, p.second_serve, "
        "       p.pt_winner "
        "FROM points p JOIN matches m USING (match_id) "
        "WHERE p.svr IN (1,2) AND p.pt_winner IN (1,2) AND m.gender = ? AND m.year IS NOT NULL"
    )
    cur = con.execute(sql, [gender])
    while True:
        batch = cur.fetchmany(100_000)
        if not batch:
            break
        for p1, p2, year, svr, fs, ss, win in batch:
            pt = parse_point(fs, ss, svr, win)
            if not pt.parse_ok or pt.server_won is None:
                continue
            names = {1: p1, 2: p2}
            srv, ret = names[pt.server], names[pt.returner]
            for who in (srv, ret):
                a = acc[who][year]
                a["points"] += 1
                a["rlen"] += pt.rally_len
            acc[srv][year]["serve_pts"] += 1
            if pt.serve_in_play == 1 and pt.shots:
                acc[srv][year]["serve1"] += 1
                acc[srv][year][f"sv{pt.shots[0].direction}"] += 1
            if pt.outcome == "ace":
                acc[srv][year]["aces"] += 1
            elif pt.outcome == "double_fault":
                acc[srv][year]["dfs"] += 1
            elif pt.outcome == "winner" and pt.last_hitter:
                last = pt.shots[-1]
                if stroke_kind(last.letter, last.is_serve) in ("drive", "slice"):
                    acc[names[pt.last_hitter]][year]["gswin"] += 1
            elif pt.outcome == "unforced_error" and pt.last_hitter:
                acc[names[pt.last_hitter]][year]["unf"] += 1
            for s in pt.shots:
                if s.is_serve:
                    continue
                a = acc[names[s.hitter]][year]
                a["rally"] += 1
                kind = stroke_kind(s.letter, False)
                if kind == "slice":
                    a["slice"] += 1
                if kind == "net" or "+" in s.modifiers or "-" in s.modifiers:
                    a["net"] += 1
                if kind in ("drive", "slice"):
                    a["fh" if s.side == "FH" else "bh"] += 1

    out = {}
    for player, years in acc.items():
        ys = sorted(years)
        out[player] = {
            "years": ys,
            "vec": {y: _vec(years[y]) for y in ys},
            "cnt": {y: int(years[y]["points"]) for y in ys},
            "total": int(sum(years[y]["points"] for y in ys)),
        }
    return out


def standardizer(fp: dict, min_yr: int = 300):
    vs = [P["vec"][y] for P in fp.values() for y in P["years"] if P["cnt"][y] >= min_yr]
    M = np.array(vs)
    mu, sd = M.mean(0), M.std(0)
    sd[sd == 0] = 1.0
    return mu, sd


def wz(P: dict, years, mu, sd) -> np.ndarray:
    """Points-weighted standardized style vector over a subset of a player's years."""
    num, den = np.zeros(len(mu)), 0.0
    for y in years:
        num += P["cnt"][y] * (P["vec"][y] - mu) / sd
        den += P["cnt"][y]
    return num / max(den, 1e-9)


def greedy_k(P: dict, k: int):
    """Chronological split into k ~equal-points contiguous eras (year-aligned)."""
    tgt = P["total"] / k
    eras, cur, acc, cut = [], [], 0, tgt
    for y in P["years"]:
        cur.append(y)
        acc += P["cnt"][y]
        if acc >= cut - 1e-9 and len(eras) < k - 1:
            eras.append(cur)
            cur = []
            cut += tgt
    eras.append(cur)
    return [e for e in eras if e]


def era_points(P: dict, years) -> int:
    return int(sum(P["cnt"][y] for y in years))


def chrono_gap(P, mu, sd):
    eras = greedy_k(P, 2)
    if len(eras) != 2:
        return None
    a, b = eras
    if era_points(P, a) < MIN_ERA or era_points(P, b) < MIN_ERA:
        return None
    return float(np.linalg.norm(wz(P, a, mu, sd) - wz(P, b, mu, sd)))


def random_gap(P, mu, sd, seed: int):
    """Median style gap between two *random* points-balanced halves (the noise floor)."""
    rng = np.random.default_rng(seed)
    ys = P["years"]
    gaps = []
    for _ in range(R):
        a, acc = [], 0
        for y in rng.permutation(ys):
            a.append(y)
            acc += P["cnt"][y]
            if acc >= P["total"] / 2:
                break
        b = [y for y in ys if y not in set(a)]
        if era_points(P, a) < MIN_ERA or era_points(P, b) < MIN_ERA:
            continue
        gaps.append(np.linalg.norm(wz(P, a, mu, sd) - wz(P, b, mu, sd)))
    return float(np.median(gaps)) if gaps else None


def evaluate(con, gender: str) -> dict:
    """Per-gender analysis: standardization, candidates, and per-player evolve test.

    ``rows`` is one tuple per long-career candidate: ``(player, dc, dr, ratio, P)``.
    Deterministic — each player's noise estimate is seeded from their name.
    """
    fp = year_fingerprints(con, gender)
    mu, sd = standardizer(fp)
    eligible = {n: P for n, P in fp.items() if P["total"] >= MIN_ERA}
    splittable = {n: P for n, P in eligible.items()
                  if P["total"] >= 2 * MIN_ERA
                  and (P["years"][-1] - P["years"][0]) >= MIN_SPAN_YEARS
                  and len(P["years"]) >= MIN_CHARTED_YEARS}
    rows = []
    for n, P in splittable.items():
        dc = chrono_gap(P, mu, sd)
        dr = random_gap(P, mu, sd, seed=zlib.crc32(n.encode()) & 0xFFFFFFFF)
        if dc is None or dr is None:
            continue
        rows.append((n, dc, dr, dc / dr, P))
    return dict(mu=mu, sd=sd, eligible=eligible, splittable=splittable, rows=rows)


def _era_label(player: str, ys: int, ye: int, multi: bool) -> str:
    return f"{player} ({ys}–{ye})" if multi else player


def compute_player_eras(con):
    """The era mapping for every tracked player (≥MIN_ERA pts): one row per era.

    Evolving long careers (chronological gap > NOISE_RATIO × noise) are split binary
    early/late — the only contrast the test validated; everyone else stays whole.
    """
    import pandas as pd

    out = []
    for gender in ("M", "W"):
        res = evaluate(con, gender)
        evolved = {r[0] for r in res["rows"] if r[3] > NOISE_RATIO}
        for name, P in res["eligible"].items():
            split = name in evolved and name in res["splittable"]
            eras = greedy_k(P, 2) if split else [P["years"]]
            for i, ys in enumerate(eras):
                y0, y1 = min(ys), max(ys)
                out.append({
                    "player": name, "gender": gender, "era": i, "n_eras": len(eras),
                    "year_start": y0, "year_end": y1, "n_points": era_points(P, ys),
                    "evolved": split, "entity": _era_label(name, y0, y1, len(eras) > 1),
                })
    return pd.DataFrame(out).sort_values(["gender", "player", "era"]).reset_index(drop=True)


def build_player_eras() -> int:
    """(Re)create the ``player_eras`` parquet + DuckDB table. Returns row count."""
    import duckdb

    from match_charting_project.paths import DB_PATH, PROCESSED_DIR

    if not DB_PATH.exists():
        raise FileNotFoundError(f"No database at {DB_PATH}. Run: match-charting-project ingest")
    con = duckdb.connect(str(DB_PATH))
    df = compute_player_eras(con)
    out = PROCESSED_DIR / "player_eras.parquet"
    df.to_parquet(out, index=False)
    con.execute("CREATE OR REPLACE TABLE player_eras AS SELECT * FROM read_parquet(?)",
                [str(out)])
    con.close()
    return len(df)
