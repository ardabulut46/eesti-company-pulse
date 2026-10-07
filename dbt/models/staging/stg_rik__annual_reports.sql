-- One row per annual report x monthly release (snapshot).
select
    report_id,
    nullif(taidetud_aruanne_report_id, '')             as filled_report_id,
    -- Elements are stored under the "filled" (täidetud) report id when one exists: for 2024,
    -- 492 of 493 reports with this reference have their elements only under the referenced id.
    coalesce(nullif(taidetud_aruanne_report_id, ''), report_id) as element_report_id,
    registrikood                                       as registry_code,
    "õiguslik vorm"                                    as legal_form_short,
    staatus                                            as company_status_name,
    cast(aruandeaasta as integer)                      as fiscal_year,
    "kas konsolideeritud?" = 'Jah'                     as is_consolidated,
    strptime(period_start, '%d.%m.%Y')::date           as period_start,
    strptime(period_end, '%d.%m.%Y')::date             as period_end,
    strptime(esitatud_kpv, '%d.%m.%Y')::date           as submitted_date,
    "kas auditeeritud?" = 'Jah'                        as is_audited,
    nullif("valitud aruanne kategooria", '')           as size_category_selected,
    nullif("minimaalne kategooria andmete alusel", '') as size_category_minimum,
    nullif("auditi töövõtu liik", '')                  as audit_engagement_type,
    nullif("audiitori otsuse tüüp", '')                as auditor_opinion_type,

    _cutoff_date                                       as release_cutoff_date,
    _snapshot_id,
    _source_row,
    _retrieved_at
from {{ source('lake', 'rik_reports_general') }}
