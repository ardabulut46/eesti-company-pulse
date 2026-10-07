-- Company x fiscal year: EMTA quarterly totals next to annual-report figures.
-- Only calendar-year reports with all four quarters present in EMTA. The figures measure
-- different things, so ratios are expected to differ from 1:
--   * EMTA turnover = VAT-declared supply incl. reverse-charge purchases, shifted one month
--     (Q1 = Dec-Feb); revenue = accrual-basis sales revenue.
--   * EMTA labour taxes = cash paid in the year; labour expense = accrued gross cost.
--   * EMTA employees = headcount at quarter end (no board members); FTE = full-time equivalent.
with q as (
    select
        registry_code,
        tax_year,
        count(*)                                              as n_quarters,
        case when count(turnover) = 4 then sum(turnover) end         as emta_turnover_4q,
        case when count(labour_taxes) = 4 then sum(labour_taxes) end as emta_labour_taxes_4q,
        case when count(employees) = 4 then avg(employees) end       as emta_avg_employees
    from {{ ref('fct_company_quarter') }}
    group by registry_code, tax_year
),

f as (
    select * from {{ ref('fct_annual_fundamentals') }}
    where is_calendar_year and has_elements
)

select
    f.registry_code,
    f.fiscal_year,
    f.section_code,
    f.region_group,
    f.size_category_selected,
    q.emta_turnover_4q,
    f.revenue                                             as ar_revenue,
    q.emta_turnover_4q / nullif(f.revenue, 0)             as turnover_to_revenue_ratio,
    q.emta_labour_taxes_4q,
    f.labour_expense                                      as ar_labour_expense,
    q.emta_labour_taxes_4q / nullif(f.labour_expense, 0)  as labour_taxes_to_expense_ratio,
    q.emta_avg_employees,
    f.fte_employees                                       as ar_fte_employees,
    q.emta_avg_employees / nullif(f.fte_employees, 0)     as employees_to_fte_ratio
from f
join q
    on q.registry_code = f.registry_code
   and q.tax_year = f.fiscal_year
   and q.n_quarters = 4
