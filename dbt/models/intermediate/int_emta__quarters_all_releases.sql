-- Wide -> long: one row per taxpayer x quarter x EMTA release.
-- INCLUDE NULLS matters: DuckDB's default UNPIVOT drops a quarter if ANY of its four values is
-- NULL: on the 2026-09-24 data it keeps 989,432 of 3,584,848 rows (72% silently lost).
-- A row-count test (4 rows per staging row) guards this.
with years as (
    select * from {{ ref('stg_emta__taxpayer_years') }}
),

long as (
    select *
    from years
    unpivot include nulls (
        (state_taxes, labour_taxes, turnover, employees)
        for quarter in (
            (state_taxes_q1, labour_taxes_q1, turnover_q1, employees_q1) as '1',
            (state_taxes_q2, labour_taxes_q2, turnover_q2, employees_q2) as '2',
            (state_taxes_q3, labour_taxes_q3, turnover_q3, employees_q3) as '3',
            (state_taxes_q4, labour_taxes_q4, turnover_q4, employees_q4) as '4'
        )
    )
)

select
    registry_code,
    taxpayer_type,
    tax_year,
    cast(quarter as integer)                          as quarter,
    tax_year * 10 + cast(quarter as integer)          as year_quarter,
    {{ quarter_end('tax_year', 'cast(quarter as integer)') }} as quarter_end_date,
    release_date,
    -- EMTA publishes a quarter on the 10th of the following month. A quarter that has not ended
    -- before the release date is not published yet; its values must all be NULL (tested).
    {{ quarter_end('tax_year', 'cast(quarter as integer)') }} < release_date as is_published,
    state_taxes,
    labour_taxes,
    turnover,
    employees,
    coalesce(state_taxes, labour_taxes, turnover, employees) is not null as has_any_value,
    _source,
    _snapshot_id,
    _source_row,
    _retrieved_at
from long
