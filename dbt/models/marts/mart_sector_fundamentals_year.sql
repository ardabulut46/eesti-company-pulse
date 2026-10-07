-- Sector x fiscal year summary of annual-report fundamentals. Medians describe the typical
-- company; sums describe the sector. Only reports with at least one structured element count.
with f as (
    select * from {{ ref('fct_annual_fundamentals') }}
    where has_elements
)

select
    f.fiscal_year,
    f.section_code,
    coalesce(s.section_short_name, 'Unknown sector')              as section_name,
    count(*)                                                      as n_reports,
    count(f.revenue)                                              as n_with_revenue,
    sum(f.revenue)                                                as revenue_total,
    median(f.revenue) filter (where f.revenue > 0)                as revenue_median,
    sum(f.fte_employees)                                          as fte_total,
    median(f.fte_employees) filter (where f.fte_employees > 0)    as fte_median,
    sum(f.labour_expense)                                         as labour_expense_total,
    sum(f.revenue) filter (where f.fte_employees > 0)
        / nullif(sum(f.fte_employees) filter (where f.fte_employees > 0 and f.revenue is not null), 0)
                                                                  as revenue_per_fte,
    sum(f.labour_expense) filter (where f.revenue > 0)
        / nullif(sum(f.revenue) filter (where f.revenue > 0 and f.labour_expense is not null), 0)
                                                                  as labour_expense_share_of_revenue,
    median(f.net_profit / f.revenue) filter (where f.revenue > 0) as net_margin_median,
    avg(case when f.net_profit < 0 then 1.0 when f.net_profit >= 0 then 0.0 end)
                                                                  as share_loss_making,
    median(f.equity / f.total_assets) filter (where f.total_assets > 0) as equity_ratio_median
from f
left join {{ ref('emtak_sections') }} s on s.section_code = f.section_code
group by all
