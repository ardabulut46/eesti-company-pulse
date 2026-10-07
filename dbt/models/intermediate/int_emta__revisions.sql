-- Values that changed between two consecutive releases for the same taxpayer x quarter.
-- One row per key x metric x pair of releases. Empty until at least two releases are stored.
with published as (
    select * from {{ ref('int_emta__quarters_all_releases') }}
    where is_published
),

long as (
    select registry_code, taxpayer_type, tax_year, quarter, release_date, _retrieved_at,
           metric, value
    from published
    unpivot include nulls (value for metric in (state_taxes, labour_taxes, turnover, employees))
),

compared as (
    select
        *,
        lag(release_date) over w as previous_release_date,
        lag(value) over w        as previous_value
    from long
    window w as (partition by registry_code, tax_year, quarter, metric
                 order by release_date, _retrieved_at)
)

select
    registry_code,
    taxpayer_type,
    tax_year,
    quarter,
    metric,
    previous_release_date,
    release_date,
    previous_value,
    value,
    case
        when previous_value is null then 'null_to_value'
        when value is null then 'value_to_null'
        else 'changed'
    end as revision_kind,
    value - previous_value as delta
from compared
where previous_release_date is not null
  and value is distinct from previous_value
