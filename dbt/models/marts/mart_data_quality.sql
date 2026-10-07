-- Every rule that removes, nulls, or flags data, with the count it affected in this build.
-- Nothing is dropped silently: if a rule touches rows, it shows up here (and in the app).
with conv as (
    select * from {{ ref('stg_pipeline__snapshots') }}
),

quarters as (
    select * from {{ ref('int_emta__quarters_all_releases') }}
),

latest as (
    select * from {{ ref('int_emta__quarters_latest') }} where taxpayer_type = 'Company'
),

elements as (
    select * from {{ ref('int_rik__element_values') }}
),

links as (
    select * from {{ ref('int_rik__report_link_coverage') }}
),

coverage as (
    select * from {{ ref('mart_join_coverage') }}
)

select 'ingestion' as area, 'Rows removed at conversion (self-employed, non-residents: privacy/scope)' as rule,
       sum(rows_dropped) as affected, sum(rows_total) as out_of, 'removed' as action
from conv
where source in ('rik_basic', 'emta_current', 'emta_history')
union all
select 'emta', 'Quarter not yet published at release date (all values NULL)',
       count(*) filter (where not is_published), count(*), 'excluded'
from quarters
union all
select 'emta', 'Published company-quarter with no value at all',
       count(*) filter (where not has_any_value), count(*), 'kept, counted as not reporting'
from latest
union all
select 'emta', 'Published company-quarter with NULL employee count',
       count(*) filter (where employees is null), count(*), 'kept as NULL (not zero)'
from latest
union all
select 'emta', 'Negative turnover (VAT-return corrections)',
       count(*) filter (where turnover < 0), count(turnover), 'kept'
from latest
union all
select 'emta', 'Company-quarter missing from the newest release (company deleted since)',
       count(*) filter (where not is_in_latest_release), count(*), 'kept from older snapshot'
from latest
union all
select 'emta', 'Revised values between releases',
       (select count(*) from {{ ref('int_emta__revisions') }}), count(*), 'newest release used'
from latest
union all
select 'annual_reports', 'Element rows in the PDF table (unlabelled current/previous year pairs)',
       sum(n_pdf_rows), sum(n_element_rows), 'excluded'
from links
union all
select 'annual_reports', 'Report x element with identical duplicate copies',
       count(*) filter (where resolution = 'identical_copies'), count(*), 'collapsed to one value'
from elements
union all
select 'annual_reports', 'Report x element with conflicting copies',
       count(*) filter (where resolution = 'conflict'), count(*), 'value set to NULL'
from elements
union all
select 'annual_reports', 'Reports with no element rows',
       count(*) filter (where link_status = 'report_without_elements'), count(*) filter (where report_id is not null), 'kept, fundamentals NULL'
from links
union all
select 'annual_reports', 'Reports whose only elements are in the PDF table',
       count(*) filter (where link_status = 'pdf_elements_only'), count(*) filter (where report_id is not null), 'kept, fundamentals NULL'
from links
union all
select 'annual_reports', 'Element report ids with no report row',
       count(*) filter (where link_status = 'elements_without_report'), count(*), 'not joinable, reported only'
from links
union all
select 'join', 'EMTA companies not in the newest register snapshot',
       count(*) filter (where not is_matched), count(*), 'kept, reason in mart_join_coverage'
from coverage
