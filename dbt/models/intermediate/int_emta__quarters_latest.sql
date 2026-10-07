-- One row per taxpayer x published quarter: the value from the most recent release in which
-- that key appears ("latest appearance" rule).
-- EMTA removes deleted legal persons from new releases. Because we keep every release, a
-- deleted company keeps its history here; is_in_latest_release = false marks it.
with published as (
    select * from {{ ref('int_emta__quarters_all_releases') }}
    where is_published
),

ranked as (
    select
        *,
        count(*) over (partition by registry_code, tax_year, quarter) as n_releases_seen,
        max(release_date) over (partition by tax_year)                as latest_release_for_year
    from published
    qualify row_number() over (
        partition by registry_code, tax_year, quarter
        order by release_date desc, _retrieved_at desc
    ) = 1
)

select
    registry_code,
    taxpayer_type,
    tax_year,
    quarter,
    year_quarter,
    quarter_end_date,
    state_taxes,
    labour_taxes,
    turnover,
    employees,
    has_any_value,
    release_date                                  as value_release_date,
    release_date = latest_release_for_year        as is_in_latest_release,
    n_releases_seen,
    _snapshot_id,
    _source,
    _source_row
from ranked
