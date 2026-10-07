"""Airflow DAGs for Eesti Company Pulse.

Airflow only schedules; every task is one `pulse` CLI command, so any task can be rerun by hand
with exactly the same command. All commands are idempotent:

- download: unchanged content adds nothing (hash check), a truncated file is never stored.
- convert:  skips snapshots already converted.
- build:    dbt rebuilds tables from all snapshots, then atomically replaces the serving DB.

Schedules follow the publishers:
- register basic data: daily
- annual-report files: monthly (RIK regenerates them around the 3rd); checked daily on days 3-10
- EMTA: 10th of the month after each quarter; checked daily on days 10-16 of Jan/Apr/Jul/Oct

`catchup=False`: a missed day cannot be downloaded later (sources overwrite their files), so
there is nothing to catch up. "Backfill" here means replaying stored raw snapshots, which the
manually triggered `pulse_rebuild` DAG does.

DuckDB allows one writer: every task that writes the warehouse uses the `duckdb_writer` pool
(1 slot), so DAGs never build at the same time.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

from airflow.providers.standard.operators.bash import BashOperator
from airflow.sdk import DAG

PULSE = os.environ.get("PULSE_BIN", "pulse")
ALERTS = Path(os.environ.get("PULSE_DATA_DIR", "/opt/pulse/data")) / "alerts.log"
WRITER_POOL = "duckdb_writer"


def _log(kind: str, context) -> None:
    """Append one line per event to data/alerts.log. Swap for Slack/email in production."""
    ti = context["task_instance"]
    ALERTS.parent.mkdir(parents=True, exist_ok=True)
    with ALERTS.open("a", encoding="utf-8") as fh:
        fh.write(
            f"{datetime.now(UTC):%Y-%m-%dT%H:%M:%SZ} {kind} {ti.dag_id}.{ti.task_id} "
            f"try={ti.try_number} run={context['run_id']} error={context.get('exception')!r}\n"
        )


def alert(context) -> None:
    """Final failure (retries exhausted)."""
    _log("FAILED", context)


def retrying(context) -> None:
    _log("RETRY", context)


DEFAULT_ARGS = {
    "owner": "pulse",
    "retries": 3,
    "retry_delay": timedelta(minutes=10),
    "retry_exponential_backoff": True,
    "max_retry_delay": timedelta(hours=2),
    "execution_timeout": timedelta(hours=1),
    "on_failure_callback": alert,
    "on_retry_callback": retrying,
}


def pipeline_dag(dag_id: str, schedule: str, families: list[str], doc: str) -> DAG:
    scope = " ".join(f"--family {f}" for f in families)
    with DAG(
        dag_id=dag_id,
        schedule=schedule,
        start_date=datetime(2026, 9, 24),
        catchup=False,
        max_active_runs=1,
        default_args=DEFAULT_ARGS,
        tags=["pulse"],
        doc_md=doc,
    ) as dag:
        download = BashOperator(task_id="download", bash_command=f"{PULSE} download {scope}")
        verify = BashOperator(task_id="verify_snapshots", bash_command=f"{PULSE} verify")
        convert = BashOperator(task_id="convert", bash_command=f"{PULSE} convert")
        build = BashOperator(
            task_id="dbt_build_and_publish",
            bash_command=f"{PULSE} build",
            pool=WRITER_POOL,
        )
        freshness = BashOperator(
            task_id="freshness",
            bash_command=f"{PULSE} freshness",
            retries=0,  # a stale source is not fixed by retrying; alert instead
        )
        download >> verify >> convert >> build >> freshness
    return dag


register_daily = pipeline_dag(
    "pulse_register_daily",
    "0 10 * * *",
    ["rik_basic"],
    "Daily register snapshot. Each changed file becomes a new snapshot -> SCD2 history.",
)

annual_reports_monthly = pipeline_dag(
    "pulse_annual_reports_monthly",
    "0 11 3-10 * *",
    ["rik_reports_general", "rik_elements"],
    "Monthly annual-report files (new cut-off date in the file name).",
)

emta_quarterly = pipeline_dag(
    "pulse_emta_quarterly",
    "0 12 10-16 1,4,7,10 *",
    ["emta"],
    "EMTA quarterly release. Checked daily in the publication window; unchanged = no-op.",
)

with DAG(
    dag_id="pulse_rebuild",
    schedule=None,
    start_date=datetime(2026, 9, 24),
    catchup=False,
    max_active_runs=1,
    default_args={**DEFAULT_ARGS, "retries": 0},
    tags=["pulse", "manual"],
    doc_md="Backfill: re-hash all raw snapshots, reconvert them, and rebuild every model.",
) as rebuild:
    BashOperator(task_id="rebuild", bash_command=f"{PULSE} rebuild", pool=WRITER_POOL)
