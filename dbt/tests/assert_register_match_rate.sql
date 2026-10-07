-- Join health: of the EMTA companies that reported anything in the newest published quarter,
-- at least var('min_register_match_rate') must match the newest register snapshot.
-- (Older EMTA years contain many companies deleted since, so they are not a health signal.)
-- A sudden drop means a broken join key or a bad snapshot.
with newest as (
    select *
    from {{ ref('mart_join_coverage') }}
    where last_reporting_year_quarter = (
        select max(last_reporting_year_quarter) from {{ ref('mart_join_coverage') }}
    )
)

select
    count(*) filter (where is_matched)::double / count(*) as match_rate
from newest
having count(*) filter (where is_matched)::double / count(*) < {{ var('min_register_match_rate') }}
