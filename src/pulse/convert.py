"""Raw snapshot -> Parquet ("lake"), one Parquet file per snapshot.

- Every column stays VARCHAR. Typing happens in dbt staging, where each cast is visible and tested.
  (DuckDB would otherwise auto-detect registry codes as BIGINT and EHAK codes lose leading zeros.)
- Lineage columns are added: _source, _snapshot_id, _sha256, _retrieved_at, _cutoff_date,
  _source_row (1-based data-row number in the raw CSV).
- Privacy/scope filter (sources.FAMILIES[..].fmt.keep_predicate) runs here, the earliest stage
  after raw. Dropped rows are counted in lake/conversions.csv, never stored.
- Idempotent: a snapshot already converted with the same sha256 and converter version is skipped.
"""

from __future__ import annotations

import csv
import shutil
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import duckdb

from pulse.config import Paths
from pulse.snapshots import Snapshot, read_manifest
from pulse.sources import family_of

CONVERTER_VERSION = "1"
CONVERSION_FIELDS = [
    "source",
    "snapshot_id",
    "sha256",
    "converter_version",
    "rows_total",
    "rows_kept",
    "rows_dropped",
    "parquet_path",
    "converted_at_utc",
]


def _conversions(paths: Paths) -> list[dict]:
    if not paths.conversions.exists():
        return []
    with paths.conversions.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def parquet_path(paths: Paths, snap: Snapshot) -> Path:
    return paths.lake / snap.source / snap.snapshot_id / "data.parquet"


def _extract_csv(raw: Path, workdir: Path) -> Path:
    if raw.suffix.lower() != ".zip":
        return raw
    with zipfile.ZipFile(raw) as z:
        members = [n for n in z.namelist() if not n.endswith("/")]
        if len(members) != 1:
            raise ValueError(f"{raw}: expected exactly one file in zip, found {members}")
        return Path(z.extract(members[0], workdir))


def _sql_str(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


def convert_snapshot(paths: Paths, snap: Snapshot, force: bool = False) -> dict | None:
    """Convert one snapshot. Returns the conversion log row, or None if skipped."""
    out = parquet_path(paths, snap)
    done = any(
        c["source"] == snap.source
        and c["snapshot_id"] == snap.snapshot_id
        and c["sha256"] == snap.sha256
        and c["converter_version"] == CONVERTER_VERSION
        for c in _conversions(paths)
    )
    if done and out.exists() and not force:
        return None

    fmt = family_of(snap.source).fmt
    workdir = paths.tmp / f"convert-{snap.source}-{snap.snapshot_id}"
    shutil.rmtree(workdir, ignore_errors=True)
    workdir.mkdir(parents=True)
    try:
        csv_path = _extract_csv(paths.data / snap.local_path, workdir)
        con = duckdb.connect()
        con.execute(
            f"""
            CREATE TABLE src AS
            SELECT *, row_number() OVER () AS _source_row
            FROM read_csv({_sql_str(str(csv_path))}, delim={_sql_str(fmt.delim)}, header=true,
                          quote='"', escape='"', all_varchar=true, strict_mode=true)
            """
        )
        total = con.execute("SELECT count(*) FROM src").fetchone()[0]
        keep = fmt.keep_predicate or "true"
        cutoff = f"DATE {_sql_str(snap.cutoff_date)}" if snap.cutoff_date else "NULL::DATE"
        tmp_out = workdir / "data.parquet"
        con.execute(
            f"""
            COPY (
                SELECT *,
                    {_sql_str(snap.source)} AS _source,
                    {_sql_str(snap.snapshot_id)} AS _snapshot_id,
                    {_sql_str(snap.sha256)} AS _sha256,
                    TIMESTAMP {_sql_str(snap.retrieved_at_utc.replace("T", " ").rstrip("Z"))}
                        AS _retrieved_at,
                    {cutoff} AS _cutoff_date
                FROM src WHERE {keep}
                ORDER BY _source_row
            ) TO {_sql_str(str(tmp_out))} (FORMAT parquet, COMPRESSION zstd)
            """
        )
        kept = con.execute(
            f"SELECT count(*) FROM read_parquet({_sql_str(str(tmp_out))})"
        ).fetchone()[0]
        con.close()
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(tmp_out, out)  # atomic within one filesystem: readers never see half a file
    finally:
        shutil.rmtree(workdir, ignore_errors=True)

    row = dict(
        source=snap.source,
        snapshot_id=snap.snapshot_id,
        sha256=snap.sha256,
        converter_version=CONVERTER_VERSION,
        rows_total=total,
        rows_kept=kept,
        rows_dropped=total - kept,
        parquet_path=str(out.relative_to(paths.data)),
        converted_at_utc=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    _write_conversion(paths, row)
    return row


def _write_conversion(paths: Paths, row: dict) -> None:
    """Keep one log row per (source, snapshot_id): a forced reconversion replaces the old row."""
    rows = [
        c
        for c in _conversions(paths)
        if not (c["source"] == row["source"] and c["snapshot_id"] == row["snapshot_id"])
    ]
    rows.append(row)
    paths.conversions.parent.mkdir(parents=True, exist_ok=True)
    tmp = paths.conversions.with_suffix(".tmp")
    with tmp.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=CONVERSION_FIELDS, lineterminator="\n")
        w.writeheader()
        w.writerows(sorted(rows, key=lambda r: (r["source"], r["snapshot_id"])))
    tmp.replace(paths.conversions)


def convert_all(paths: Paths, sources: set[str] | None = None, force: bool = False) -> list[dict]:
    done = []
    for snap in read_manifest(paths):
        if sources and snap.source not in sources:
            continue
        row = convert_snapshot(paths, snap, force=force)
        if row:
            done.append(row)
    return done
