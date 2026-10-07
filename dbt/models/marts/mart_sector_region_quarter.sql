-- The pulse: sector x county x region x quarter. Every metric is an additive sum, so the table
-- can be rolled up to any level (all sectors, a county, Estonia) by summing, and ratios are
-- computed after rolling up.
--
-- Growth uses a matched panel: *_matched_current / *_matched_previous only include companies
-- with a non-NULL value in both periods, so companies appearing or disappearing from the data do
-- not count as growth. Naive totals are kept alongside for comparison.
with f as (
    select * from {{ ref('fct_company_quarter') }}
),

paired as (
    select
        cur.*,
        yoy.employees    as employees_prev_year,
        yoy.turnover     as turnover_prev_year,
        yoy.labour_taxes as labour_taxes_prev_year,
        qoq.employees    as employees_prev_quarter
    from f cur
    left join f yoy
        on yoy.registry_code = cur.registry_code
       and yoy.tax_year = cur.tax_year - 1
       and yoy.quarter = cur.quarter
    left join f qoq
        on qoq.registry_code = cur.registry_code
       and qoq.year_quarter = case when cur.quarter = 1 then (cur.tax_year - 1) * 10 + 4
                                   else cur.year_quarter - 1 end
)

select
    p.tax_year,
    p.quarter,
    p.year_quarter,
    p.quarter_end_date,
    p.section_code,
    coalesce(s.section_short_name, 'Unknown sector')           as section_name,
    p.region_group,
    coalesce(p.county, 'Unknown')                              as county,

    count(*) filter (where p.has_any_value)                    as n_companies_reporting,
    count(p.employees)                                         as n_companies_with_employee_count,
    count(*) filter (where p.employees > 0)                    as n_employers,
    sum(p.employees)                                           as employees,
    sum(p.turnover)                                            as turnover,
    sum(p.labour_taxes)                                        as labour_taxes,
    sum(p.state_taxes)                                         as state_taxes,
    -- Turnover per employee is only meaningful where both are known and employees > 0.
    sum(p.turnover) filter (where p.employees > 0 and p.turnover is not null)  as turnover_of_employers,
    sum(p.employees) filter (where p.employees > 0 and p.turnover is not null) as employees_of_employers,

    count(*) filter (where p.employees is not null and p.employees_prev_year is not null)
                                                               as n_matched_yoy_employees,
    sum(p.employees) filter (where p.employees_prev_year is not null)  as employees_matched_current_yoy,
    sum(p.employees_prev_year) filter (where p.employees is not null)  as employees_matched_previous_yoy,
    sum(p.turnover) filter (where p.turnover_prev_year is not null)    as turnover_matched_current_yoy,
    sum(p.turnover_prev_year) filter (where p.turnover is not null)    as turnover_matched_previous_yoy,
    sum(p.labour_taxes) filter (where p.labour_taxes_prev_year is not null) as labour_taxes_matched_current_yoy,
    sum(p.labour_taxes_prev_year) filter (where p.labour_taxes is not null) as labour_taxes_matched_previous_yoy,
    sum(p.employees) filter (where p.employees_prev_quarter is not null)    as employees_matched_current_qoq,
    sum(p.employees_prev_quarter) filter (where p.employees is not null)    as employees_matched_previous_qoq,

    count(*) filter (where not p.attributes_are_point_in_time) as n_companies_sector_not_point_in_time
from paired p
left join {{ ref('emtak_sections') }} s on s.section_code = p.section_code
group by all
