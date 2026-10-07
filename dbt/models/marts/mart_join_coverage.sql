-- Every EMTA company code (any stored release) and whether it matches the newest register
-- snapshot. Unmatched codes get a reason from the annual-report file, which still lists
-- deleted companies. Grain: registry_code.
with emta as (
    select
        registry_code,
        max(value_release_date)                              as last_release_date,
        max(year_quarter) filter (where has_any_value)       as last_reporting_year_quarter
    from {{ ref('int_emta__quarters_latest') }}
    where taxpayer_type = 'Company'
    group by registry_code
),

latest_register as (
    select distinct registry_code
    from {{ ref('stg_rik__companies') }}
    where snapshot_date = (select max(snapshot_date) from {{ ref('stg_rik__companies') }})
),

report_status as (
    select registry_code, arg_max(company_status_name, fiscal_year) as status_in_report_file
    from {{ ref('int_rik__annual_reports_latest') }}
    group by registry_code
),

history as (
    select registry_code, bool_or(is_present) as ever_seen_in_register
    from {{ ref('int_rik__company_history') }}
    group by registry_code
)

select
    e.registry_code,
    e.last_release_date,
    e.last_reporting_year_quarter,
    l.registry_code is not null                   as is_matched,
    rs.status_in_report_file,
    case
        when l.registry_code is not null then 'matched'
        when h.ever_seen_in_register then 'left register after first snapshot'
        when rs.status_in_report_file = 'Kustutatud' then 'deleted (per annual-report file)'
        when rs.status_in_report_file in ('Likvideerimisel', 'Pankrotis')
            then 'liquidation/bankruptcy (per annual-report file)'
        when rs.status_in_report_file is not null then 'registered per report file, missing from basic data'
        else 'no register or report record'
    end                                           as match_reason
from emta e
left join latest_register l on l.registry_code = e.registry_code
left join report_status rs on rs.registry_code = e.registry_code
left join history h on h.registry_code = e.registry_code
