-- How much EMTA changes already-published quarters between releases.
-- Empty until two EMTA releases are stored (the first comparison is possible after 2026-10-10).
select
    previous_release_date,
    release_date,
    tax_year,
    quarter,
    metric,
    revision_kind,
    count(*)            as n_revisions,
    sum(delta)          as net_delta,
    sum(abs(delta))     as gross_delta
from {{ ref('int_emta__revisions') }}
where taxpayer_type = 'Company'
group by all
