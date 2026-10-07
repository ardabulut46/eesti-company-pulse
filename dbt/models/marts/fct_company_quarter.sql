-- Company x published quarter: EMTA values plus point-in-time sector, region, and register
-- attributes. Scope: EMTA taxpayer type 'Company'.
with quarters as (
    select * from {{ ref('int_emta__quarters_latest') }}
    where taxpayer_type = 'Company'
),

attributes as (
    select * from {{ ref('int_emta__company_attributes') }}
    where taxpayer_type = 'Company'
),

register as (
    select * from {{ ref('int_rik__company_history') }}
),

register_first as (
    select * from register where version_number = 1
),

register_now as (
    select registry_code, is_present from register where is_current
),

with_attributes as (
    -- ASOF join: the first release published after the quarter ended. That is the release that
    -- first published the quarter, if we stored it; otherwise the earliest later release we have.
    select
        q.*,
        a.release_date            as attributes_release_date,
        a.taxpayer_name           as company_name,
        a.section_code,
        a.activity_section_name,
        a.county,
        a.municipality,
        a.region_group
    from quarters q
    asof left join attributes a
        on a.registry_code = q.registry_code
       and a.release_date > q.quarter_end_date
),

with_register as (
    -- ASOF join: the register version valid at quarter end (latest valid_from <= quarter end).
    select
        w.*,
        r.version_number          as register_version_number,
        r.valid_to                as register_valid_to,
        r.is_present              as register_is_present,
        r.legal_form              as register_legal_form,
        r.status_code             as register_status_code
    from with_attributes w
    asof left join register r
        on r.registry_code = w.registry_code
       and r.valid_from <= w.quarter_end_date
)

select
    w.registry_code,
    w.tax_year,
    w.quarter,
    w.year_quarter,
    w.quarter_end_date,
    w.state_taxes,
    w.labour_taxes,
    w.turnover,
    w.employees,
    w.has_any_value,
    w.value_release_date,
    w.is_in_latest_release,
    w.n_releases_seen,

    w.company_name,
    coalesce(w.section_code, '?')                             as section_code,
    w.activity_section_name,
    w.county,
    w.municipality,
    coalesce(w.region_group, 'Unknown')                       as region_group,
    w.attributes_release_date,
    date_diff('day', w.quarter_end_date, w.attributes_release_date) as attributes_lag_days,
    date_diff('day', w.quarter_end_date, w.attributes_release_date)
        <= {{ var('point_in_time_max_lag_days') }}            as attributes_are_point_in_time,

    -- Register attributes as of quarter end when our snapshots reach back that far; otherwise
    -- the earliest version we have, flagged. Never silently presented as point-in-time.
    case
        when w.register_version_number is not null
             and (w.register_valid_to is null or w.register_valid_to > w.quarter_end_date)
            then 'as_of_quarter_end'
        when f.registry_code is not null then 'earliest_known_version'
        else 'not_in_register_snapshots'
    end                                                       as register_attributes_basis,
    coalesce(w.register_legal_form, f.legal_form)             as legal_form,
    case when w.register_version_number is not null then w.register_status_code
         else f.status_code end                               as register_status_code,
    coalesce(n.is_present, false)                             as is_in_register_now
from with_register w
left join register_first f on f.registry_code = w.registry_code
left join register_now n on n.registry_code = w.registry_code
