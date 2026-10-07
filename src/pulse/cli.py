"""Command line entry point: `pulse <command>`.

Every command is safe to rerun. Orchestrators (Airflow) call these commands and nothing else,
so a failed task can always be rerun by hand with the same command.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

from pulse import convert, freshness, publish, snapshots, sources
from pulse.config import REPO_ROOT, get_paths

# Installed (non-editable) packages cannot find dbt/ next to the source, so Docker sets this.
DBT_DIR = Path(os.environ.get("PULSE_DBT_DIR", REPO_ROOT / "dbt"))


def _families(values: list[str] | None) -> set[str] | None:
    if not values:
        return None
    unknown = set(values) - set(sources.FAMILIES)
    if unknown:
        raise SystemExit(
            f"unknown family {sorted(unknown)}; choose from {sorted(sources.FAMILIES)}"
        )
    return set(values)


def cmd_discover(args) -> int:
    for r in sources.discover(_families(args.family), _years(args.years)):
        print(f"{r.source:24} {str(r.cutoff_date or ''):10} {r.url}")
    return 0


def _years(values: list[int] | None) -> set[int] | None:
    return set(values) if values else None


def cmd_download(args) -> int:
    paths = get_paths()
    failed = 0
    for r in sources.discover(_families(args.family), _years(args.years)):
        try:
            result, snap = snapshots.fetch(r, paths)
        except Exception as exc:  # report every source, then fail the command
            failed += 1
            print(f"{r.source:24} FAILED {exc}", file=sys.stderr)
            continue
        detail = f"{snap.local_path} ({snap.size_bytes:,} bytes)" if snap else ""
        print(f"{r.source:24} {result:9} {detail}")
    return 1 if failed else 0


def cmd_convert(args) -> int:
    paths = get_paths()
    rows = convert.convert_all(paths, set(args.source) if args.source else None, force=args.force)
    for row in rows:
        print(
            f"{row['source']:24} {row['snapshot_id']:12} kept {int(row['rows_kept']):>10,}"
            f"  dropped {int(row['rows_dropped']):>8,}"
        )
    if not rows:
        print("nothing to convert")
    return 0


def cmd_verify(args) -> int:
    problems = snapshots.verify(get_paths())
    for p in problems:
        print(p, file=sys.stderr)
    print("all snapshots verified" if not problems else f"{len(problems)} problem(s)")
    return 1 if problems else 0


def dbt(*dbt_args: str) -> int:
    paths = get_paths()
    env = {
        **os.environ,
        "PULSE_DATA_DIR": str(paths.data),
        "DBT_PROFILES_DIR": str(DBT_DIR),
        # Keep each data directory's dbt artifacts apart (tests use their own).
        "DBT_TARGET_PATH": os.environ.get("DBT_TARGET_PATH", str(DBT_DIR / "target")),
    }
    paths.warehouse.parent.mkdir(parents=True, exist_ok=True)
    exe = os.path.join(os.path.dirname(sys.executable), "dbt")
    return subprocess.call([exe if os.path.exists(exe) else "dbt", *dbt_args], cwd=DBT_DIR, env=env)


def cmd_dbt(args) -> int:
    return dbt(*args.dbt_args)


def cmd_build(args) -> int:
    rc = dbt("build", *(["--full-refresh"] if args.full_refresh else []))
    return rc or cmd_publish(args)


def cmd_publish(args) -> int:
    counts = publish.publish(get_paths())
    print(f"published {len(counts)} tables to {publish.serving_path(get_paths())}")
    return 0


def cmd_run(args) -> int:
    """Download -> convert -> dbt build. What a scheduled run does."""
    rc = cmd_download(args)
    if rc and not args.keep_going:
        return rc
    cmd_convert(argparse.Namespace(source=None, force=False))
    return cmd_build(argparse.Namespace(full_refresh=False)) or rc


def cmd_rebuild(args) -> int:
    """Backfill: replay every raw snapshot into the lake and rebuild all models from scratch."""
    cmd_verify(args)
    cmd_convert(argparse.Namespace(source=None, force=True))
    return cmd_build(argparse.Namespace(full_refresh=True))


def cmd_freshness(args) -> int:
    results = freshness.check(get_paths())
    worst = "ok"
    for f in results:
        print(
            f"{f.source:24} {f.status:5} checked {f.check_age_days!s:>6} d ago, "
            f"content {f.content_age_days!s:>6} d old (warn>{f.warn_days}, error>{f.error_days})"
        )
        if f.status == "error" or (f.status == "warn" and worst == "ok"):
            worst = f.status
    return 1 if worst == "error" else 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="pulse", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    def with_scope(sp):
        sp.add_argument(
            "--family",
            action="append",
            help="rik_basic, emta, rik_reports_general, rik_elements (repeatable; default all)",
        )
        sp.add_argument("--years", type=int, nargs="*", help="annual-report element years")
        return sp

    with_scope(sub.add_parser("discover", help="resolve current download URLs")).set_defaults(
        fn=cmd_discover
    )
    with_scope(sub.add_parser("download", help="download new snapshots")).set_defaults(
        fn=cmd_download
    )
    c = sub.add_parser("convert", help="raw snapshots -> Parquet")
    c.add_argument("--source", action="append")
    c.add_argument("--force", action="store_true", help="reconvert even if already done")
    c.set_defaults(fn=cmd_convert)
    sub.add_parser("verify", help="re-hash stored snapshots").set_defaults(fn=cmd_verify)
    d = sub.add_parser("dbt", help="run dbt with project paths, e.g. `pulse dbt test`")
    d.add_argument("dbt_args", nargs=argparse.REMAINDER)
    d.set_defaults(fn=cmd_dbt)
    b = sub.add_parser("build", help="dbt build")
    b.add_argument("--full-refresh", action="store_true")
    b.set_defaults(fn=cmd_build)
    r = with_scope(sub.add_parser("run", help="download + convert + build"))
    r.add_argument("--keep-going", action="store_true", help="build even if a download failed")
    r.set_defaults(fn=cmd_run)
    sub.add_parser("rebuild", help="replay all raw snapshots and rebuild").set_defaults(
        fn=cmd_rebuild
    )
    sub.add_parser("publish", help="copy marts to the serving database").set_defaults(
        fn=cmd_publish
    )
    sub.add_parser("freshness", help="check source freshness").set_defaults(fn=cmd_freshness)

    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
