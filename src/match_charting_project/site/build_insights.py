"""Build the compact ``insights.duckdb`` the Pages site queries in-browser via DuckDB-WASM.

A small projection of the main DB — one row per charted player — assembled from the
experiment CSVs + the graduated library, keyed by **base player name** (era-split
entities are collapsed to their most recent era = current form). Aggregates only, so it
stays small enough to ship; nothing is committed (it lands under gitignored ``data/``).

Prereq: the experiments have been run so their CSVs exist in ``reports/`` (the CI
insights workflow runs them first). Run: ``match-charting-project site build-insights``.
"""

import re
from datetime import date

import duckdb
import pandas as pd

from match_charting_project.live.players import (
    coverage,
    coverage_by_year,
    normalize,
    tourn_key,
)
from match_charting_project.paths import DB_PATH, PROJECT_ROOT
from match_charting_project.winprob_match import current_strength

REPORTS = PROJECT_ROOT / "reports"
OUT = PROJECT_ROOT / "data" / "insights.duckdb"
_ERA_RE = re.compile(r"^(?P<base>.+) \((?P<y0>\d{4})[–-](?P<y1>\d{4})\)$")
# Only recent slam/1000 identities ship: the site archives completed events going forward,
# never older ones, so their per-match charting status is all the fast path can ever need.
_CHARTED_SINCE = date.today().year - 2


def _base(entity: str) -> "tuple[str, int]":
    m = _ERA_RE.match(str(entity))
    return (m["base"], int(m["y1"])) if m else (str(entity), 0)


def _collapse(df: pd.DataFrame, mean_over: "dict | None" = None) -> pd.DataFrame:
    """Collapse era entities to base names, keeping the latest era per (gender, player).

    Latest-era is right for the things this is mostly used for — an archetype and its
    confidence flag are a claim about how someone plays, and for a split career the
    current answer is the one worth printing.

    It is wrong for a *measurement* the panel prints beside a career-wide denominator.
    ``mean_over`` names columns to average across a player's eras instead, weighted by
    the ``weight`` column, so the figure covers the same matches the coverage band
    above it counts. Rally length needed this: Connors' two eras run 4.90 and 6.16, and
    the panel printed 6.2 from 2,776 points directly beside a charted-history line
    reading 7,309 — under a key claiming the figure covers every charted point the
    player appeared in. Across the 35 split careers the two eras differ by 0.351 on
    average, which is 44% of the tour's whole interquartile spread, and by up to 1.266.
    """
    df = df.copy()
    parsed = [_base(p) for p in df["player"]]
    df["player"] = [b for b, _ in parsed]
    df["_y1"] = [y for _, y in parsed]
    latest = df.sort_values("_y1").groupby(["gender", "player"], as_index=False).last()
    if mean_over:
        for col, weight in mean_over.items():
            w = df[weight].fillna(0.0)
            wsum = w.groupby([df.gender, df.player]).transform("sum")
            # An all-zero-weight player would divide by zero; they keep the latest era,
            # which is what the unweighted path would have given them anyway.
            share = (w / wsum).where(wsum > 0, 0.0)
            avg = (df[col] * share).groupby([df.gender, df.player]).sum()
            avg = avg.where(wsum.groupby([df.gender, df.player]).first() > 0)
            latest[col] = latest.set_index(["gender", "player"]).index.map(avg)
    return latest.drop(columns="_y1")


def _charted_matches(con) -> pd.DataFrame:
    """Recent slam/1000 charted matches, keyed so the fast path can flag per-match charting.

    Names/tournaments are normalized here (via the shared ``players`` helpers) so the join
    in ``build_brackets`` is a plain dict lookup — no fuzzy matching on the hot path.
    """
    rows = con.execute(
        "SELECT match_id, gender, year, tournament, player1, player2, charted_by "
        "FROM matches WHERE is_qualifying = false AND year >= ? "
        "AND tier IN ('Grand Slam', 'Masters / WTA 1000')",
        [_CHARTED_SINCE]).fetchall()
    df = pd.DataFrame(rows, columns=["match_id", "gender", "year", "tournament",
                                     "player1", "player2", "charted_by"])
    df["tourn_key"] = df["tournament"].map(tourn_key)
    df["p1_norm"] = df["player1"].map(normalize)
    df["p2_norm"] = df["player2"].map(normalize)
    return df[["gender", "year", "tourn_key", "p1_norm", "p2_norm", "match_id", "charted_by"]]


def _player_facts(con) -> pd.DataFrame:
    """Handedness and ace rate per ``(gender, player)``, straight from the main DB.

    Both are facts about the player rather than findings about them, so neither comes
    through an experiment: they are read here and shipped beside the rates.

    Hand is the modal value across their charted matches, not the first one seen. A
    handful of rows in the upstream matches CSV are column-shifted (the hand column
    holding a date or a tie name), so anything that isn't R or L is dropped before the
    vote rather than allowed to win one — and a player charted only in those rows comes
    out null, which the panel prints as nothing.

    Ace rate is aces over service points across every charted match, and needs the floor
    because it is the one number here that isn't shrunk toward anything: over a single
    charted match a couple of aces in a short set reads as a 15% ace rate. 200 service
    points is about two matches.
    """
    hands = con.execute(
        "WITH seen AS ("
        "  SELECT gender, player1 AS player, upper(trim(player1_hand)) AS hand FROM matches"
        "  UNION ALL"
        "  SELECT gender, player2, upper(trim(player2_hand)) FROM matches), "
        "voted AS ("
        "  SELECT gender, player, hand,"
        "         row_number() OVER (PARTITION BY gender, player ORDER BY count(*) DESC) rn"
        "  FROM seen WHERE hand IN ('R', 'L') GROUP BY gender, player, hand) "
        "SELECT gender, player, hand FROM voted WHERE rn = 1").fetchall()
    aces = con.execute(
        "SELECT gender, player,"
        "       sum(CAST(aces AS INT)) / CAST(sum(CAST(serve_pts AS INT)) AS DOUBLE) AS ace_rate "
        "FROM stats_overview WHERE set = 'Total' "
        "GROUP BY gender, player HAVING sum(CAST(serve_pts AS INT)) >= 200").fetchall()
    facts = pd.DataFrame(hands, columns=["gender", "player", "hand"])
    return facts.merge(pd.DataFrame(aces, columns=["gender", "player", "ace_rate"]),
                       on=["gender", "player"], how="outer")


def _serve_placement() -> "tuple[pd.DataFrame | None, list]":
    """Per-side serve placement for the panel, plus the gates it has to respect.

    The shipped mix is the recency-weighted one (``serve_tendencies`` step 7: a
    10-match half-life predicts a player's next matches better than their career
    average, because placement drifts), and ``n_eff`` is its effective sample
    size — the number the reliability gate applies to, since a decay weighting
    has no raw denominator. ``reliable`` is that gate already applied.
    """
    path = REPORTS / "serve_tendencies_players.csv"
    if not path.exists():
        return None, []
    df = pd.read_csv(path)
    df = df[(df.serve == "1st") & df.recent_n_eff.notna() & df.recent_wide.notna()]
    # Built column by column rather than renamed: the CSV carries both the recent
    # and the career mix, and renaming one onto the other's name silently ships
    # duplicate columns with the career values winning.
    serve = pd.DataFrame({
        "player": df.player, "gender": df.gender, "side": df.side,
        "wide": df.recent_wide, "t": df.recent_t,
        "n_eff": df.recent_n_eff.astype(int),
        "years": df.recent_years,
        "career_wide": df.wide, "career_t": df.t, "career_n": df.n,
        "reliable": df.reliable.fillna(0).astype(int),
        "drift_ratio": df.drift_ratio,
    })

    # Gates and tour baselines as meta rows, so the site never hardcodes a
    # threshold the experiment owns. meta is numeric key/value, read by prefix.
    rows = []
    mpath = REPORTS / "serve_tendencies_meta.csv"
    if mpath.exists():
        for r in pd.read_csv(mpath).to_dict("records"):
            g = r["gender"]
            for col in ("n80_wide", "n80_t", "rule_param", "recent_matches",
                        "tour_deuce_wide", "tour_deuce_t", "tour_ad_wide", "tour_ad_t"):
                rows.append({"key": f"serve_{col}_{g}", "value": float(r[col])})
    return serve, rows


PATTERN_COLS = ["player", "gender", "family", "state", "response", "state_depth",
                "inc_code", "resp_code", "lift", "count", "n_state", "evidence",
                "win_rate", "tour_win_rate", "field_share", "state_win_rate"]
# Extra columns the return family carries and the rally family has no meaning for.
# The panel draws the serve from them, so they must survive the trip as strings —
# an all-empty rally column would otherwise read back as NaN and print "nan".
PATTERN_SIDE_COLS = ["tier", "serve_side", "serve_dir"]


def _patterns() -> pd.DataFrame:
    """The two pattern families, from the two experiments that own them.

    ``rally`` is court_response's: a player's answer to an incoming ball, sides
    pooled because a mid-rally ball has no side. ``ret`` is serve_plus_one's: the
    server's third ball, with the service court and the serve's direction in the
    state wherever the player's charting funds them.

    serve_plus_one is optional. It is the newer of the two, and a stale checkout or
    a half-run pipeline should ship the panel with court_response's pooled return
    rows rather than with no return section at all.
    """
    # The code columns are read as text, never inferred. They are digits, and a column
    # with any blank in it infers as float — which turns serve direction "6" into "6.0",
    # matches none of the renderer's cases, and silently drops the serve from the drawing.
    codes = {c: str for c in ("inc_code", "resp_code", "serve_dir", "serve_side", "tier")}
    cr = pd.read_csv(REPORTS / "court_response_players.csv", dtype=codes)
    sp_path = REPORTS / "serve_plus_one_players.csv"
    if sp_path.exists():
        ret = pd.read_csv(sp_path, dtype=codes)
        ret = ret[ret.family == "ret"]
        cr = cr[cr.family != "ret"]
    else:
        ret = cr[cr.family == "ret"].copy()
        cr = cr[cr.family != "ret"]
        ret["tier"] = "pooled"
        ret["serve_side"] = ""
        ret["serve_dir"] = ""

    for col in PATTERN_SIDE_COLS:
        cr[col] = ""
    patterns = pd.concat([cr[PATTERN_COLS + PATTERN_SIDE_COLS],
                          ret[PATTERN_COLS + PATTERN_SIDE_COLS]], ignore_index=True)
    for col in ("inc_code", "resp_code", *PATTERN_SIDE_COLS):
        patterns[col] = patterns[col].fillna("").astype(str)
    patterns["state_depth"] = patterns["state_depth"].fillna("")
    return patterns


def build() -> int:
    """(Re)create ``insights.duckdb`` from the DB + experiment CSVs. Returns player count."""
    con = duckdb.connect(str(DB_PATH), read_only=True)
    strength, mu = current_strength(con)
    cov = coverage(con)
    cov_years = pd.DataFrame(coverage_by_year(con),
                             columns=["gender", "player", "year", "matches", "points"])
    charted = _charted_matches(con)
    facts = _player_facts(con)
    con.close()

    summary = pd.DataFrame([
        {"gender": g, "player": p, "serve_rate": round(sv, 4), "return_rate": round(rt, 4),
         "matches_charted": cov.get((g, p), {}).get("matches", 0),
         "points_charted": cov.get((g, p), {}).get("points", 0),
         "year_min": cov.get((g, p), {}).get("year_min"),
         "year_max": cov.get((g, p), {}).get("year_max")}
        for (g, p), (sv, rt) in strength.items()
    ])

    summary = summary.merge(facts, on=["player", "gender"], how="left")

    # The same coverage the summary carries as four numbers, cut by season, for the panel's
    # charted-history chart. Inner-joined to the summary so the table only holds players the
    # site can actually open a panel for — the charting corpus reaches a long tail of players
    # who never appear in a draw, and their year rows would be most of the file.
    years = cov_years.merge(summary[["gender", "player"]], on=["gender", "player"])
    years = years.astype({"year": "int32", "matches": "int32", "points": "int32"})

    # style_confident travels with the archetype, and the panel is required to respect
    # it: style is a continuum, the clustering's silhouette sits near 0.12, and for a
    # third of entities the nearest two archetypes fit about equally well. Those are the
    # ones whose label flipped wholesale when a fifth of a percent of the corpus moved,
    # so shipping the name without the flag would be shipping the unstable half as
    # though it were the stable half.
    # avg_rally_len travels with the archetype because it is the same measurement pass:
    # mean strokes in the points the player appeared in, keyed by the same era entity. It
    # It is the panel's profile-column figure; see the class_relative_wpa note below for why
    # no shot-quality score stands there instead.
    # avg_rally_len is point-weighted across a split career; the archetype and its
    # confidence flag stay latest-era. The two want different things from the same row —
    # see _collapse — and n_points is the weight because it is the denominator the figure
    # was computed over in the first place.
    clusters = _collapse(pd.read_csv(REPORTS / "player_style_clusters.csv")
                         [["player", "gender", "archetype", "style_margin",
                           "style_confident", "avg_rally_len", "n_points"]],
                         mean_over={"avg_rally_len": "n_points"}).drop(columns="n_points")
    summary = summary.merge(clusters, on=["player", "gender"], how="left")

    lang = pd.read_csv(REPORTS / "shot_language_players.csv")[["player", "gender", "bits"]]
    summary = summary.merge(lang, on=["player", "gender"], how="left")

    # Court-state response profiles: the player's stable, hand-normalized answers to a given
    # incoming ball. Preferred over raw signature pairs, which mostly surface generic rally
    # geometry and handedness artifacts — see experiments/court_response.
    #
    # Two experiments feed one table, split by family. The rally family is
    # court_response's. The return family — the server's third ball — comes from
    # serve_plus_one instead, which asks the same question with the service court and
    # the serve's direction in the state, at whatever resolution each player's charting
    # funds. court_response still computes its own ret family for its report; it just
    # does not ship it, since the two would describe one shot two ways on one page.
    patterns = _patterns()

    # Nothing from class_relative_wpa is merged here: no shot-quality figure survives its own
    # validation. WPA telescopes within a point, so avg_wpa_lost is identically (win
    # probability conceded per point) / (strokes per point) and the second factor dominates —
    # it correlates -0.87 (men) / -0.83 (women) with rally length. The class-relative residual
    # is no better: it correlates -0.99 with the score it is taken from and 66% of its variance
    # is still rally length. reports/class_relative_wpa.{csv,md} keep the full record; this
    # file ships what the panel renders.

    # Shot-making triggers (shot_triggers experiment): green lights by aggressive shot
    # frequency lift, traps by how far conversion falls below the player's norm. One book,
    # not separate winner and error books — see experiments/shot_triggers.
    tr = pd.read_csv(REPORTS / "shot_triggers.csv")
    greens = (tr[tr.tag == "green"].sort_values("att_lift", ascending=False)
              .groupby(["player", "gender"]).head(3))
    traps = (tr[tr.tag == "trap"].sort_values("conv_delta")
             .groupby(["player", "gender"]).head(3))
    # ``attempts`` ships alongside ``n`` because they are the denominators of two
    # different numbers on the card and the panel was printing only the first. ``n`` is
    # the strokes played from that lead-up, which is what the frequency is over;
    # ``attempts`` is the aggressive shots among them, which is what the conversion is
    # over — and it is the smaller and more fragile of the two by roughly a factor of
    # three, so a card labelled n=93 was resting its conversion claim on 33 shots.
    triggers = pd.concat([greens, traps])[
        ["player", "gender", "tag", "context", "att_rate", "att_lift",
         "conversion", "conv_delta", "n", "attempts"]]

    # No starred 3-4 shot tier ships. Screened with the opening blinded and every figure
    # read off a fold that had no part in the selection, two of 1,752 three-shot
    # candidates survive, both for retired players who appear in no draw — see
    # experiments/rally_patterns. That experiment still runs weekly and still writes
    # reports/rally_patterns.csv, so this is where the tier would come back if the
    # charting ever funds one for a current player.

    # Opening cues by service court (shot_triggers' openings section). Same currency as
    # the pooled triggers above — a lead-up that shifts the player's aggressive shot
    # frequency — but scored against their own norm *for that shot and that court*, which
    # the pooled table cannot do: a wide serve opens a right-hander's forehand in the
    # deuce court and their backhand in the ad court, so the pooled row averages two
    # different serves and names neither. 310 of the pooled rows above are opening cues
    # shown that way; these are the same shots told properly.
    #
    # This waited until 2026-08-29 for a reason worth recording: the experiment produced
    # this table from the start, but as a raw threshold screen with no multiplicity
    # correction and its figures read off the data that selected them, while the pooled
    # table beside it was FDR-corrected and cross-validated. Shipping it in that state
    # would have put the panel's least-screened numbers next to its most-screened. It is
    # now on the same footing as everything else here.
    openings = pd.DataFrame()
    op_path = REPORTS / "shot_triggers_openings.csv"
    if op_path.exists():
        op = pd.read_csv(op_path)
        if len(op):
            og = (op[op.tag == "green"].sort_values("att_lift", ascending=False)
                  .groupby(["player", "gender"]).head(2))
            ot = (op[op.tag == "trap"].sort_values("conv_delta")
                  .groupby(["player", "gender"]).head(2))
            openings = pd.concat([og, ot])[
                ["player", "gender", "side", "role", "anchor", "context", "tag",
                 "att_rate", "att_lift", "conversion", "conv_delta", "n", "attempts"]]

    # ``sigma`` is not taken. It printed as the profile column's "shot selection" figure and
    # was cut by the test that retired the shot-quality score: it correlates -0.81 (men) /
    # -0.59 (women) with rally length, two thirds of the men's spread is the player's own
    # baseline aggressive shot frequency — which ``trig_att_rate`` below already carries in
    # plain percent — and its leaderboard was a serve-volley leaderboard, with Rafter falling
    # from the top of the tour to below the median once serve and net lead-ups came out. It
    # also carried no direction: it was independent of whether the extra aggression converted,
    # so one number described an adaptive player and a baited one identically.
    tp = pd.read_csv(REPORTS / "shot_triggers_players.csv")[
        ["player", "gender", "att_rate", "conversion", "n_traps"]].rename(
        columns={"att_rate": "trig_att_rate", "conversion": "trig_conversion"})
    summary = summary.merge(tp, on=["player", "gender"], how="left")

    # Serve placement (serve_tendencies experiment). Only the two targets that
    # survived that experiment's checks ship: the body share is partly a charter's
    # opinion (charters disagree about it by ±4-6% on the same players), so it is
    # measured there and deliberately not reported here. Shares are of all charted
    # first serves, so wide + T does not reach 100% — the remainder is the body.
    serve, serve_meta = _serve_placement()
    if serve is not None:
        bp = pd.read_csv(REPORTS / "serve_tendencies_leverage.csv")
        bp = bp[(bp.direction == "wide") & (bp.bucket == "break_pt")][
            ["player", "gender", "delta", "sig", "n"]].rename(
            columns={"delta": "serve_bp_wide_delta", "sig": "serve_bp_sig",
                     "n": "serve_bp_n"})
        summary = summary.merge(bp, on=["player", "gender"], how="left")

    meta = pd.DataFrame([{"key": f"mu_{g}", "value": round(v, 5)} for g, v in mu.items()]
                        + serve_meta)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.unlink(missing_ok=True)     # fresh file: dropped tables must not ship forever
    out = duckdb.connect(str(OUT))
    tables = [("player_summary", summary), ("player_triggers", triggers),
              ("player_patterns", patterns), ("player_openings", openings),
              ("player_years", years), ("meta", meta),
              ("charted_matches", charted)]
    if serve is not None:
        tables.append(("player_serve", serve))
    for name, df in tables:
        out.register(f"_{name}", df)
        out.execute(f"CREATE OR REPLACE TABLE {name} AS SELECT * FROM _{name}")
    out.close()
    return len(summary)
