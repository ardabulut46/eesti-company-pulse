-- One row per legal entity seen in the register snapshots or as an EMTA 'Company'.
-- Current attributes; the full history is in dim_company_history.
with register_current as (
    select * from {{ ref('int_rik__company_history') }} where is_current
),

register_first as (
    select registry_code, min(valid_from) as first_seen_in_register_snapshot
    from {{ ref('int_rik__company_history') }}
    group by registry_code
),

register_versions as (
    select registry_code, count(*) as n_register_versions
    from {{ ref('int_rik__company_history') }}
    group by registry_code
),

emta_latest as (
    select *
    from {{ ref('int_emta__company_attributes') }}
    where taxpayer_type = 'Company'
    qualify row_number() over (partition by registry_code order by release_date desc) = 1
),

keys as (
    select registry_code from register_current
    union
    select registry_code from emta_latest
)

select
    k.registry_code,
    coalesce(r.company_name, e.taxpayer_name)          as company_name,
    r.legal_form,
    r.status_code,
    r.status_name,
    coalesce(r.is_present, false)                      as is_in_register_now,
    r.ehak_code,
    r.ehak_name,
    r.county                                           as register_county,
    e.section_code,
    e.activity_section_name,
    e.county                                           as emta_county,
    e.municipality                                     as emta_municipality,
    coalesce(e.region_group, 'Unknown')                as region_group,
    e.release_date                                     as emta_last_release_date,
    e.registry_code is not null                        as is_emta_company,
    f.first_seen_in_register_snapshot,
    coalesce(v.n_register_versions, 0)                 as n_register_versions
from keys k
left join register_current r on r.registry_code = k.registry_code
left join emta_latest e on e.registry_code = k.registry_code
left join register_first f on f.registry_code = k.registry_code
left join register_versions v on v.registry_code = k.registry_code
