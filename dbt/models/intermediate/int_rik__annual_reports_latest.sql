-- One row per company x fiscal year: the report row from the newest monthly release in which it
-- appears ("latest appearance" rule). Each release holds exactly one report per company x
-- year (tested in staging), so no report-level deduplication is needed.
select
    *,
    count(*) over (partition by registry_code, fiscal_year) as n_releases_seen
from {{ ref('stg_rik__annual_reports') }}
qualify row_number() over (
    partition by registry_code, fiscal_year
    order by _retrieved_at desc
) = 1
