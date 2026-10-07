-- How element rows connect to reports. Grain: element_report_id.
-- Reports whose elements are missing, and element rows that belong to no known report, are
-- reported here instead of disappearing in an inner join.
with reports as (
    select element_report_id, report_id, registry_code, fiscal_year
    from {{ ref('int_rik__annual_reports_latest') }}
),

element_reports as (
    select report_id as element_report_id, any_value(file_fiscal_year) as file_fiscal_year,
           count(*) as n_element_rows,
           count(*) filter (where table_name = 'PDF') as n_pdf_rows
    from {{ ref('stg_rik__report_elements') }}
    group by report_id
)

select
    coalesce(r.element_report_id, e.element_report_id) as element_report_id,
    r.report_id,
    r.registry_code,
    coalesce(r.fiscal_year, e.file_fiscal_year)        as fiscal_year,
    coalesce(e.n_element_rows, 0)                      as n_element_rows,
    coalesce(e.n_pdf_rows, 0)                          as n_pdf_rows,
    case
        when r.element_report_id is null then 'elements_without_report'
        when e.element_report_id is null then 'report_without_elements'
        when e.n_element_rows = e.n_pdf_rows then 'pdf_elements_only'
        else 'linked'
    end                                                as link_status
from reports r
full outer join element_reports e on e.element_report_id = r.element_report_id
