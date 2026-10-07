"""Copy the marts into a separate, read-only serving database for the app.

DuckDB allows one writer OR many readers per file. If the app read the warehouse directly, an
open app would block `dbt build`. Instead the app reads data/serving/pulse.duckdb, which is
replaced atomically (write a new file, then rename) after a successful build.
"""

from __future__ import annotations

import os

import duckdb

from pulse.config import Paths

SCHEMAS = ("marts", "reference")


def serving_path(paths: Paths):
    return paths.data / "serving" / "pulse.duckdb"


def publish(paths: Paths) -> dict[str, int]:
    target = serving_path(paths)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".duckdb.tmp")
    tmp.unlink(missing_ok=True)

    con = duckdb.connect(str(tmp))
    con.execute(f"ATTACH '{paths.warehouse}' AS wh (READ_ONLY)")
    counts = {}
    for schema in SCHEMAS:
        con.execute(f"CREATE SCHEMA {schema}")
        tables = con.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_catalog = 'wh' AND table_schema = ? ORDER BY table_name",
            [schema],
        ).fetchall()
        for (table,) in tables:
            con.execute(f'CREATE TABLE {schema}."{table}" AS SELECT * FROM wh.{schema}."{table}"')
            counts[f"{schema}.{table}"] = con.execute(
                f'SELECT count(*) FROM {schema}."{table}"'
            ).fetchone()[0]
    con.execute("DETACH wh")
    con.close()
    os.replace(tmp, target)
    return counts
