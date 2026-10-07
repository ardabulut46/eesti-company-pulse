-- Company x fiscal year fundamentals from annual reports: EAV elements pivoted to columns.
-- Scope: business legal forms (OÜ, AS, UÜ, TÜH, TÜ, FIL, SE, SCE, EMÜ).
-- Base element names are the entity's own (unconsolidated) figures, the same level as EMTA.
-- Units: euros as filed. Sign: expenses in the income statement are filed as negative numbers
-- (observed, e.g. EmployeeExpense); LaborExpense from the labour-cost note is positive.
{% set elements = {
    'Revenue': 'revenue',
    'TotalProfitLoss': 'operating_profit',
    'TotalProfitLossBeforeTax': 'profit_before_tax',
    'TotalAnnualPeriodProfitLoss': 'net_profit',
    'LaborExpense': 'labour_expense',
    'EmployeeExpense': 'employee_expense_income_statement',
    'AverageNumberOfEmployeesInFullTimeEquivalentUnits': 'fte_employees',
    'DepreciationAndImpairmentLossReversal': 'depreciation',
    'Assets': 'total_assets',
    'CurrentAssets': 'current_assets',
    'NonCurrentAssets': 'non_current_assets',
    'CashAndCashEquivalents': 'cash',
    'Equity': 'equity',
    'IssuedCapital': 'issued_capital',
    'CurrentLiabilities': 'current_liabilities',
    'NonCurrentLiabilities': 'non_current_liabilities',
} %}

with reports as (
    select * from {{ ref('int_rik__annual_reports_latest') }}
    where legal_form_short in ('OÜ', 'AS', 'UÜ', 'TÜH', 'TÜ', 'FIL', 'SE', 'SCE', 'EMÜ')
),

element_values as (
    select element_report_id, element_code, value
    from {{ ref('int_rik__element_values') }}
    where element_code in ({% for code in elements %}'{{ code }}'{{ ',' if not loop.last }}{% endfor %})
),

wide as (
    -- EAV -> wide. One value per report x element is guaranteed upstream, so any_value is exact.
    pivot element_values
    on element_code in ({% for code in elements %}'{{ code }}'{{ ',' if not loop.last }}{% endfor %})
    using any_value(value)
    group by element_report_id
),

quality as (
    select
        element_report_id,
        count(*) filter (where resolution = 'conflict')  as n_conflicting_elements,
        count(*)                                         as n_elements
    from {{ ref('int_rik__element_values') }}
    group by element_report_id
),

attributes as (
    select * from {{ ref('int_emta__company_attributes') }}
)

select
    r.registry_code,
    r.fiscal_year,
    r.report_id,
    r.element_report_id,
    r.legal_form_short,
    r.period_start,
    r.period_end,
    r.period_start = make_date(r.fiscal_year, 1, 1)
        and r.period_end = make_date(r.fiscal_year, 12, 31)  as is_calendar_year,
    r.submitted_date,
    r.is_consolidated,
    r.is_audited,
    r.size_category_selected,
    r.company_status_name,
    {% for code, col in elements.items() -%}
    w."{{ code }}"                                          as {{ col }},
    {% endfor -%}
    coalesce(q.n_elements, 0)                               as n_elements,
    coalesce(q.n_conflicting_elements, 0)                   as n_conflicting_elements,
    q.element_report_id is not null                         as has_elements,
    -- Sector from the first EMTA release after the fiscal year ended (NULL if the company is not
    -- in any stored EMTA release, e.g. never paid taxes or had turnover).
    coalesce(a.section_code, '?')                           as section_code,
    coalesce(a.region_group, 'Unknown')                     as region_group,
    a.release_date                                          as attributes_release_date
from reports r
left join wide w on w.element_report_id = r.element_report_id
left join quality q on q.element_report_id = r.element_report_id
asof left join attributes a
    on a.registry_code = r.registry_code
   and a.release_date > r.period_end
