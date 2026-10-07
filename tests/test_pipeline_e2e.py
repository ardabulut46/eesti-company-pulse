"""End to end on synthetic data: download (2 days) -> convert -> dbt build -> publish.

Skipped when dbt is not installed (`pip install -e .[dbt]`).
"""

import os
import shutil

import duckdb
import pytest

from pulse import cli
from pulse.config import get_paths

from synthetic_sources import build_data_dir

pytestmark = pytest.mark.skipif(
    shutil.which("dbt") is None
    and not os.path.exists(os.path.join(os.path.dirname(os.sys.executable), "dbt")),
    reason="dbt not installed",
)


@pytest.fixture(scope="module")
def warehouse(tmp_path_factory):
    data = tmp_path_factory.mktemp("e2e") / "data"
    build_data_dir(data)
    env = {"PULSE_DATA_DIR": str(data), "DBT_TARGET_PATH": str(data.parent / "dbt-target")}
    old = {k: os.environ.get(k) for k in env}
    os.environ.update(env)
    try:
        assert cli.main(["build"]) == 0, "dbt build failed on the synthetic fixture"
        yield duckdb.connect(str(get_paths().warehouse), read_only=True), get_paths()
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def one(con, sql):
    return con.execute(sql).fetchone()


def test_identical_second_day_downloads_add_no_snapshots(warehouse):
    con, _ = warehouse
    rows = dict(
        con.execute(
            "select source, count(*) from marts.mart_pipeline_snapshots group by 1"
        ).fetchall()
    )
    # register + EMTA changed between the two days; annual-report files did not
    assert rows == {
        "rik_basic": 2,
        "emta_current": 2,
        "emta_history": 2,
        "rik_reports_general": 1,
        "rik_elements_2024": 1,
        "rik_elements_2025": 1,
    }


def test_scd2_records_liquidation_and_deletion(warehouse):
    con, _ = warehouse
    history = con.execute(
        "select registry_code, version_number, valid_from::varchar, valid_to::varchar, "
        "is_present, status_code from marts.dim_company_history "
        "where registry_code in ('10000002', '10000006') order by 1, 2"
    ).fetchall()
    assert history == [
        ("10000002", 1, "2026-04-11", "2026-07-11", True, "R"),
        ("10000002", 2, "2026-07-11", None, True, "L"),
        ("10000006", 1, "2026-04-11", "2026-07-11", True, "R"),
        ("10000006", 2, "2026-07-11", None, False, None),
    ]


def test_deleted_company_keeps_its_emta_history(warehouse):
    con, _ = warehouse
    n, in_latest = one(
        con,
        """
        select count(*), bool_or(is_in_latest_release)
        from marts.fct_company_quarter where registry_code = '10000006'""",
    )
    assert n > 0 and in_latest is False


def test_revision_is_detected_and_newest_value_used(warehouse):
    con, _ = warehouse
    rev = con.execute("""
        select previous_value, value from intermediate.int_emta__revisions
        where registry_code = '10000001' and metric = 'turnover'""").fetchall()
    # base = 1 * 10 + (2026 - 2022) * 3 = 22 -> Q1 turnover 22 * 1000 + 100, revised by +555
    assert rev == [(22100, 22655)]
    turnover = one(
        con,
        """select turnover from marts.fct_company_quarter
        where registry_code = '10000001' and year_quarter = 20261""",
    )[0]
    assert turnover == rev[0][1]


def test_leading_zero_code_and_null_employees(warehouse):
    con, _ = warehouse
    row = one(
        con,
        """select employees, region_group from marts.fct_company_quarter
        where registry_code = '01234567' and year_quarter = 20252""",
    )
    assert row == (None, "Harju (excl. Tallinn)")


def test_privacy_rows_never_reach_the_warehouse(warehouse):
    con, _ = warehouse
    assert (
        one(
            con,
            """select count(*) from staging.stg_emta__taxpayer_years
        where taxpayer_type in ('Self-employed person', 'Non-resident')""",
        )[0]
        == 0
    )
    assert (
        one(
            con,
            """select count(*) from staging.stg_rik__companies
        where legal_form = 'Füüsilisest isikust ettevõtja'""",
        )[0]
        == 0
    )


def test_element_rules(warehouse):
    con, _ = warehouse
    # 10000003's elements are stored under the filled report id and must still link.
    rev = one(
        con,
        """select revenue from marts.fct_annual_fundamentals
        where registry_code = '10000003' and fiscal_year = 2025""",
    )[0]
    assert rev is not None
    # 10000004 has two different CurrentLiabilities values -> NULL, counted as a conflict.
    cl, n_conf = one(
        con,
        """select current_liabilities, n_conflicting_elements
        from marts.fct_annual_fundamentals
        where registry_code = '10000004' and fiscal_year = 2024""",
    )
    assert cl is None and n_conf == 1


def test_serving_database_is_published(warehouse):
    _, paths = warehouse
    serving = duckdb.connect(str(paths.data / "serving" / "pulse.duckdb"), read_only=True)
    n = serving.execute("select count(*) from marts.mart_sector_region_quarter").fetchone()[0]
    assert n > 0
