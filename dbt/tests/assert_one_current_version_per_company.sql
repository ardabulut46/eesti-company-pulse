-- SCD2 invariant: every company has exactly one open (valid_to IS NULL) version,
-- and its versions do not overlap or leave gaps.
with versions as (
    select
        registry_code,
        valid_from,
        valid_to,
        is_current,
        lead(valid_from) over (partition by registry_code order by valid_from) as next_valid_from
    from {{ ref('int_rik__company_history') }}
)

select registry_code, 'not exactly one current version' as problem
from versions
group by registry_code
having count(*) filter (where is_current) <> 1

union all

select registry_code, 'gap or overlap between versions' as problem
from versions
where next_valid_from is not null and valid_to is distinct from next_valid_from
