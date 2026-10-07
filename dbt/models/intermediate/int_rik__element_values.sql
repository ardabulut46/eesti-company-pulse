-- One value per report x element, resolved from the long element files.
--
-- 1. Only the newest release of each report's elements is used.
-- 2. The `PDF` table is excluded: its rows have no element code and hold two unlabelled values
--    per item (current and previous year, order unknown).
-- 3. The same element can appear several times: repeated in one statement layout, or in several
--    layouts (balance sheet and notes). If every copy has the same value (min = max), that value
--    is used. If copies disagree, value is NULL and resolution = 'conflict'. No copy is preferred.
--
-- min/max instead of count(distinct ...) keeps this aggregate cheap on ~25M rows.
with structured as (
    select *
    from {{ ref('stg_rik__report_elements') }}
    where table_name <> 'PDF'
),

newest_release as (
    select report_id, max(_retrieved_at) as _retrieved_at
    from structured
    group by report_id
)

select
    e.report_id                                  as element_report_id,
    e.element_code,
    any_value(e.element_label)                   as element_label,
    any_value(e.file_fiscal_year)                as file_fiscal_year,
    case when min(e.value) = max(e.value) then min(e.value) end as value,
    case
        when count(*) = 1 then 'single'
        when min(e.value) = max(e.value) then 'identical_copies'
        else 'conflict'
    end                                          as resolution,
    count(*)                                     as n_rows,
    min(e.value)                                 as min_value,
    max(e.value)                                 as max_value,
    min(e.table_name)                            as first_table_name,
    max(e.table_name)                            as last_table_name,
    any_value(e._snapshot_id)                    as _snapshot_id
from structured e
join newest_release n using (report_id, _retrieved_at)
group by e.report_id, e.element_code
