"""Command-line entry point: download, build, ingest, coverage, validate, info."""

import argparse

from match_charting_project.paths import DB_PATH


def _info() -> None:
    import duckdb

    if not DB_PATH.exists():
        print("No database yet. Run: match-charting-project ingest")
        return
    con = duckdb.connect(str(DB_PATH), read_only=True)
    print(f"Database: {DB_PATH}\n")
    for (table,) in con.execute("SHOW TABLES").fetchall():
        n = con.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
        cols = len(con.execute(f'DESCRIBE "{table}"').fetchall())
        print(f"  {table:<20} {n:>10,} rows  x {cols:>2} cols")
    con.close()


def _shots() -> None:
    from match_charting_project.shots import build as shots_build

    n = shots_build.build_parsed_points()
    print(f"  points_parsed: {n:,} rows -> table points_parsed")


def _eras() -> None:
    from match_charting_project.analysis import career_eras

    n = career_eras.build_player_eras()
    print(f"  player_eras: {n:,} era rows -> table player_eras")


def _live() -> None:
    from match_charting_project.analysis.coverage import connect
    from match_charting_project.live import brackets, espn, players

    tours = espn.current_tournaments()
    if not tours:
        print("No current Grand Slam / 1000 singles draws found.")
        return
    con = connect(read_only=True)
    universe = players.player_universe(con)
    con.close()
    for t in tours:
        rds = brackets.rounds(t)
        names = {s.name for m in t.matches for s in (m.a, m.b) if s.name}
        charted = sum(1 for n in names if players.match_player(n, t.gender, universe))
        print(f"\n{t.name} — {t.gender} ({t.tier}, best-of-{t.best_of}): "
              f"{len(t.matches)} matches, {len(rds)} rounds; "
              f"{charted}/{len(names)} players charted")
        for r in rds:
            print(f"  {r['label']:<18} {len(r['matches']):>3} matches")


def _ingest(what: str, force: bool, provenance: bool) -> None:
    from match_charting_project.ingest import build as build_mod
    from match_charting_project.ingest import download as download_mod
    from match_charting_project.ingest import manifest as manifest_mod

    download_mod.download(what, force=force)
    if provenance:
        try:
            mf = manifest_mod.capture_source_manifest(what)
            print(f"  manifest: {len(mf)} source files -> source_manifest.parquet")
        except Exception as exc:  # best-effort; never block the build
            print(f"  manifest: skipped ({exc})")
    matches, points = build_mod.build_frames(what)
    max_date = matches["date"].max()
    manifest_mod.record_ingestion_run(len(matches), len(points), max_date)
    tables = build_mod.build_duckdb()
    print(f"  duckdb  : {len(tables)} tables -> {DB_PATH}")


_GENDER_LABEL = {"M": "Men", "W": "Women"}
_SECTIONS = [
    ("slam", "Grand Slam coverage (charted / 127-match draw, since {slam_since})"),
    ("masters", "Masters 1000 coverage (charted / 15 R16-onward matches, since {m_since})"),
]


def _coverage() -> None:
    from match_charting_project.analysis import coverage
    from match_charting_project.paths import PROJECT_ROOT
    from match_charting_project.viz import coverage_report

    con = coverage.connect(read_only=True)
    summary = coverage.summary(con)
    slam = coverage.slam_coverage(con)
    slam_rounds = coverage.slam_round_completion(con)
    masters = coverage.masters_coverage(con)
    masters_rounds = coverage.masters_round_completion(con)
    figs = coverage_report.render_all(con)
    con.close()

    def _headline(cov, rounds, draw, first_round, last_round, gender):
        c = cov[cov["gender"] == gender]
        best = c.loc[c["coverage_pct"].idxmax()]
        rp = rounds[rounds["gender"] == gender].set_index("round")["completion_pct"]
        return best, float(rp.get(first_round)), float(rp.get(last_round))

    lines = ["# Coverage summary", ""]
    lines.append("## Dataset totals")
    lines.append(f"- Matches: **{summary['matches']:,}** "
                 f"({summary['men']:,} men / {summary['women']:,} women)")
    lines.append(f"- Points: **{summary['points']:,}**")
    lines.append(f"- Distinct tournaments: **{summary['tournaments']}**")
    lines.append(f"- Date span: **{summary['earliest']} -> {summary['latest']}**")
    lines.append(f"- Tier-classified (not Other/Unknown): "
                 f"**{summary['pct_tier_classified']}%**")
    lines.append("")
    lines.append("## True coverage highlights (charted vs. played)")
    print("  -- coverage highlights --")
    for g in ("M", "W"):
        label = _GENDER_LABEL[g]
        s_best, s_open, s_final = _headline(slam, slam_rounds, 127, "R128", "F", g)
        m_best, m_open, m_final = _headline(masters, masters_rounds, 15, "R16", "F", g)
        lines.append(f"- **{label} slams** — best draw {s_best['slam']} "
                     f"{int(s_best['year'])} at **{s_best['coverage_pct']:.0f}%** "
                     f"({int(s_best['charted'])}/127); finals {s_final:.0f}% vs "
                     f"R128 {s_open:.0f}%.")
        lines.append(f"- **{label} Masters 1000** — best draw {m_best['event']} "
                     f"{int(m_best['year'])} at **{m_best['coverage_pct']:.0f}%** "
                     f"({int(m_best['charted'])}/15); finals {m_final:.0f}% vs "
                     f"R16 {m_open:.0f}%.")
        print(f"  {label:<6} slam best {s_best['coverage_pct']:>3.0f}%  "
              f"F/R128 {s_final:.0f}/{s_open:.0f}   |   "
              f"masters best {m_best['coverage_pct']:>3.0f}%  "
              f"F/R16 {m_final:.0f}/{m_open:.0f}")
    lines.append("")

    by_section = {key: {g: [] for g in ("M", "W")} for key, _ in _SECTIONS}
    for section, gender, path in figs:
        by_section[section][gender].append(path)
    for key, heading in _SECTIONS:
        heading = heading.format(slam_since=coverage.SLAM_SINCE, m_since=coverage.MASTERS_SINCE)
        lines.append(f"## {heading}")
        for g in ("M", "W"):
            lines.append(f"### {_GENDER_LABEL[g]}")
            for path in by_section[key][g]:
                lines.append(f"- ![{path}]({'../' + path})")
        lines.append("")
    (PROJECT_ROOT / "reports" / "coverage_summary.md").write_text("\n".join(lines))

    print(f"  figures  : {len(figs)} written")
    print("  summary  -> reports/coverage_summary.md")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="match-charting-project",
        description="Ingest & analyze the Tennis Match Charting Project dataset.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    dl = sub.add_parser("download", help="download raw CSVs into data/raw")
    dl.add_argument("--what", choices=["core", "all"], default="core")
    dl.add_argument("--force", action="store_true", help="re-download cached files")

    bd = sub.add_parser("build", help="build parquet + duckdb from data/raw")
    bd.add_argument("--stats", choices=["core", "all"], default="core")

    ig = sub.add_parser("ingest", help="download + provenance + build (one shot)")
    ig.add_argument("--what", choices=["core", "all"], default="core")
    ig.add_argument("--force", action="store_true")
    ig.add_argument("--no-provenance", action="store_true",
                    help="skip GitHub freshness lookups (offline)")

    sub.add_parser("coverage", help="render coverage figures + summary")

    sub.add_parser("shots", help="decode point notation into the points_parsed table")
    sub.add_parser("eras", help="build the optional player_eras table (split evolving careers)")
    sub.add_parser("live", help="fetch current tournament brackets from ESPN (smoke test)")
    site = sub.add_parser("site", help="build site data artifacts")
    site.add_argument("what", choices=["build-insights", "build-brackets"])
    sub.add_parser("validate", help="print the data-quality report")
    sub.add_parser("info", help="summarize the duckdb database")

    args = parser.parse_args(argv)

    if args.cmd == "download":
        from match_charting_project.ingest import download as download_mod
        download_mod.download(args.what, force=args.force)
    elif args.cmd == "build":
        from match_charting_project.ingest import build as build_mod
        build_mod.build(args.stats)
    elif args.cmd == "ingest":
        _ingest(args.what, args.force, provenance=not args.no_provenance)
    elif args.cmd == "coverage":
        _coverage()
    elif args.cmd == "shots":
        _shots()
    elif args.cmd == "eras":
        _eras()
    elif args.cmd == "live":
        _live()
    elif args.cmd == "site":
        if args.what == "build-insights":
            from match_charting_project.site import build_insights
            n = build_insights.build()
            print(f"  insights.duckdb: {n:,} players -> data/insights.duckdb")
        else:
            from match_charting_project.site import build_brackets
            n = build_brackets.build()
            print(f"  brackets.json: {n} tournaments -> docs/data/ (+ insights.duckdb copy)")
    elif args.cmd == "validate":
        _validate()
    elif args.cmd == "info":
        _info()


def _validate() -> None:
    from match_charting_project.paths import PROJECT_ROOT

    report = PROJECT_ROOT / "reports" / "data_quality.md"
    if report.exists():
        print(report.read_text())
    else:
        print("No report yet. Run: match-charting-project build")


if __name__ == "__main__":
    main()
