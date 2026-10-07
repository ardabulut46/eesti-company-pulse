import csv
import io
import zipfile
from datetime import UTC, datetime

import duckdb

from pulse import convert, snapshots
from pulse.sources import Resolved

from synthetic_sources import Server, emta, rik_basic


def _download(paths, tmp_path, source, filename, payload):
    served = tmp_path / "served"
    served.mkdir(exist_ok=True)
    (served / filename).write_bytes(payload)
    with Server(served) as srv:
        _, snap = snapshots.fetch(
            Resolved(source, f"{srv.base_url}/{filename}"),
            paths,
            now=datetime(2026, 9, 24, tzinfo=UTC),
        )
    return snap


def test_register_codes_stay_text_and_self_employed_are_dropped(paths, tmp_path):
    snap = _download(paths, tmp_path, "rik_basic", "basic.csv.zip", rik_basic(1))
    row = convert.convert_snapshot(paths, snap)
    assert row["rows_dropped"] == 1  # the FIE row
    assert row["rows_total"] == row["rows_kept"] + row["rows_dropped"]

    pq = paths.data / row["parquet_path"]
    con = duckdb.connect()
    codes = {r[0] for r in con.execute(f"select ariregistri_kood from '{pq}'").fetchall()}
    assert "01234567" in codes, "leading zero must survive"
    forms = {r[0] for r in con.execute(f"select ettevotja_oiguslik_vorm from '{pq}'").fetchall()}
    assert "Füüsilisest isikust ettevõtja" not in forms
    ehak = con.execute(f"select distinct asukoha_ehak_kood from '{pq}' order by 1").fetchall()
    assert ("0596",) in ehak
    types = dict(con.execute(f"describe select * from '{pq}'").fetchall()[i][:2] for i in range(3))
    assert types["ariregistri_kood"] == "VARCHAR"


def test_lineage_columns_point_back_to_the_raw_row(paths, tmp_path):
    payload = emta(1, history=False)
    snap = _download(paths, tmp_path, "emta_current", "emta.csv", payload)
    row = convert.convert_snapshot(paths, snap)
    assert row["rows_dropped"] == 2  # self-employed + non-resident

    raw_rows = list(csv.reader(io.StringIO(payload.decode("utf-8"))))[1:]
    con = duckdb.connect()
    for source_row, code, snapshot_id, sha in con.execute(
        f'select _source_row, "Registry code", _snapshot_id, _sha256 '
        f"from '{paths.data / row['parquet_path']}'"
    ).fetchall():
        assert raw_rows[source_row - 1][1] == code
        assert snapshot_id == "2026-09-24"
        assert sha == snap.sha256


def test_conversion_is_idempotent_and_force_replaces_the_log_row(paths, tmp_path):
    _download(paths, tmp_path, "rik_basic", "basic.csv.zip", rik_basic(1))
    first = convert.convert_all(paths)
    assert len(first) == 1
    assert convert.convert_all(paths) == []  # nothing to do
    again = convert.convert_all(paths, force=True)
    assert len(again) == 1
    with paths.conversions.open() as fh:
        assert len(list(csv.DictReader(fh))) == 1
    assert (paths.data / first[0]["parquet_path"]).exists()


def test_zip_with_several_files_is_rejected(paths, tmp_path):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("a.csv", "x\n1\n")
        z.writestr("b.csv", "x\n2\n")
    snap = _download(paths, tmp_path, "rik_basic", "two.csv.zip", buf.getvalue())
    try:
        convert.convert_snapshot(paths, snap)
    except ValueError as exc:
        assert "exactly one file" in str(exc)
    else:
        raise AssertionError("expected ValueError")
