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


def _coverage(months: int) -> None:
    from match_charting_project.analysis import coverage
    from match_charting_project.paths import PROJECT_ROOT
    from match_charting_project.viz import coverage_report

    con = coverage.connect(read_only=True)
    summary = coverage.summary(con)
    figs = coverage_report.render_all(con, months=months)

    lines = ["# Coverage summary", ""]
    lines.append(f"- Matches: **{summary['matches']:,}** "
                 f"({summary['men']:,} men / {summary['women']:,} women)")
    lines.append(f"- Points: **{summary['points']:,}**")
    lines.append(f"- Distinct tournaments: **{summary['tournaments']}**")
    lines.append(f"- Date span: **{summary['earliest']} -> {summary['latest']}**")
    lines.append(f"- Tier-classified (not Other/Unknown): "
                 f"**{summary['pct_tier_classified']}%**")
    lines.append("")
    lines.append("## Figures")
    for f in figs:
        lines.append(f"- ![{f}]({'../' + f})")
    (PROJECT_ROOT / "reports" / "coverage_summary.md").write_text("\n".join(lines))
    con.close()

    for k, v in summary.items():
        print(f"  {k:<22} {v}")
    print("  figures:")
    for f in figs:
        print(f"    - {f}")
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

    cv = sub.add_parser("coverage", help="render coverage figures + summary")
    cv.add_argument("--months", type=int, default=36,
                    help="window for the recent-activity chart")

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
        _coverage(args.months)
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
