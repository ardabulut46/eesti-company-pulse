"""DAG integrity. Runs only where Airflow is installed (the `airflow` CI job)."""

from pathlib import Path

import pytest

pytest.importorskip("airflow")

from airflow.dag_processing.dagbag import DagBag  # noqa: E402

DAGS = Path(__file__).parents[1] / "orchestration" / "airflow" / "dags"


@pytest.fixture(scope="module")
def dagbag():
    return DagBag(dag_folder=str(DAGS))


def test_no_import_errors(dagbag):
    assert dagbag.import_errors == {}


def test_expected_dags(dagbag):
    assert set(dagbag.dag_ids) == {
        "pulse_register_daily",
        "pulse_annual_reports_monthly",
        "pulse_emta_quarterly",
        "pulse_rebuild",
    }


def test_scheduled_dags_do_not_catch_up_and_writers_share_one_pool(dagbag):
    for dag_id in dagbag.dag_ids:
        dag = dagbag.get_dag(dag_id)
        assert dag.catchup is False
        assert dag.max_active_runs == 1
        for task in dag.tasks:
            writes_warehouse = "build" in task.bash_command or "rebuild" in task.bash_command
            if writes_warehouse:
                assert task.pool == "duckdb_writer", f"{dag_id}.{task.task_id}"


def test_task_order(dagbag):
    dag = dagbag.get_dag("pulse_register_daily")
    order = [t.task_id for t in dag.topological_sort()]
    assert order == [
        "download",
        "verify_snapshots",
        "convert",
        "dbt_build_and_publish",
        "freshness",
    ]
