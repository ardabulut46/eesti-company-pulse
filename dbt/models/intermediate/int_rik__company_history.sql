-- SCD Type 2 company history built from every stored daily register snapshot.
--
-- One row per company version. A new version starts when any tracked attribute changes, or when
-- a company reappears after being absent. Absence (the company is missing from a snapshot, e.g.
-- deleted from the register) is its own version with is_present = false.
--
-- valid_from / valid_to are OBSERVATION dates: the change happened after the previous snapshot
-- and on or before valid_from. valid_to is exclusive; NULL means "still valid in the newest
-- snapshot". Rebuilt from all snapshots on every run, so it is deterministic and replayable.
with observations as (
    select
        registry_code,
        snapshot_date,
        company_name,
        legal_form,
        legal_form_subtype,
        status_code,
        status_name,
        vat_number,
        ehak_code,
        ehak_name,
        county,
        address,
        -- concat_ws skips NULLs, so NULLs get a marker: otherwise (NULL, 'x') and ('x', NULL)
        -- would hash the same and a change would be missed.
        md5(concat_ws('|', {% for c in ['company_name', 'legal_form', 'legal_form_subtype',
                                        'status_code', 'vat_number', 'ehak_code', 'address'] -%}
            coalesce({{ c }}, '<null>'){{ ', ' if not loop.last }}
        {%- endfor %})) as attribute_hash
    from {{ ref('stg_rik__companies') }}
),

snapshot_calendar as (
    select
        snapshot_date,
        row_number() over (order by snapshot_date)  as snapshot_seq,
        lead(snapshot_date) over (order by snapshot_date) as next_snapshot_date
    from (select distinct snapshot_date from observations)
),

sequenced as (
    select
        o.*,
        c.snapshot_seq,
        c.next_snapshot_date,
        lag(o.attribute_hash) over w as previous_hash,
        lag(c.snapshot_seq) over w   as previous_seq
    from observations o
    join snapshot_calendar c using (snapshot_date)
    window w as (partition by o.registry_code order by o.snapshot_date)
),

islands as (
    select
        *,
        -- Gaps-and-islands: a version starts at the first sighting, after a change, or after a
        -- gap in the snapshot sequence (the company was absent in between).
        sum(case when previous_hash is null
                   or previous_hash <> attribute_hash
                   or previous_seq <> snapshot_seq - 1
                 then 1 else 0 end)
            over (partition by registry_code order by snapshot_date
                  rows between unbounded preceding and current row) as present_version
    from sequenced
),

present_versions as (
    -- arg_max_null, not arg_max: DuckDB's arg_max skips rows whose value is NULL, which would take
    -- the end date (and any attribute that became NULL) from an older row. The unit test
    -- scd2_change_absence_return_and_new caught this.
    select
        registry_code,
        present_version,
        min(snapshot_date)       as valid_from,
        max(snapshot_date)       as last_seen_date,
        -- The version ends at the first snapshot after its last sighting (NULL if none yet).
        arg_max_null(next_snapshot_date, snapshot_date) as ends_at_snapshot,
        arg_max_null(company_name, snapshot_date)       as company_name,
        arg_max_null(legal_form, snapshot_date)         as legal_form,
        arg_max_null(legal_form_subtype, snapshot_date) as legal_form_subtype,
        arg_max_null(status_code, snapshot_date)        as status_code,
        arg_max_null(status_name, snapshot_date)        as status_name,
        arg_max_null(vat_number, snapshot_date)         as vat_number,
        arg_max_null(ehak_code, snapshot_date)          as ehak_code,
        arg_max_null(ehak_name, snapshot_date)          as ehak_name,
        arg_max_null(county, snapshot_date)             as county,
        arg_max_null(address, snapshot_date)            as address,
        count(*)                                   as n_snapshots_observed
    from islands
    group by registry_code, present_version
),

with_next as (
    select
        *,
        lead(valid_from) over (partition by registry_code order by valid_from) as next_valid_from
    from present_versions
),

absent_versions as (
    -- The span between the end of a present version and the next sighting (or open-ended).
    select
        registry_code,
        ends_at_snapshot  as valid_from,
        next_valid_from   as valid_to,
        false             as is_present,
        company_name, legal_form, legal_form_subtype,
        null::varchar as status_code, 'Absent from register snapshot' as status_name,
        null::varchar as vat_number, null::varchar as ehak_code, null::varchar as ehak_name,
        null::varchar as county, null::varchar as address,
        0::bigint as n_snapshots_observed
    from with_next
    where ends_at_snapshot is not null
      and ends_at_snapshot is distinct from next_valid_from
),

all_versions as (
    select
        registry_code,
        valid_from,
        -- Ends at the first snapshot after its last sighting: either the start of the next
        -- version (an attribute changed) or the first snapshot the company was missing from.
        ends_at_snapshot  as valid_to,
        true              as is_present,
        company_name, legal_form, legal_form_subtype, status_code, status_name, vat_number,
        ehak_code, ehak_name, county, address, n_snapshots_observed
    from with_next
    union all
    select * from absent_versions
)

select
    registry_code,
    row_number() over (partition by registry_code order by valid_from) as version_number,
    valid_from,
    valid_to,
    valid_to is null                                                    as is_current,
    is_present,
    company_name,
    legal_form,
    legal_form_subtype,
    status_code,
    status_name,
    vat_number,
    ehak_code,
    ehak_name,
    county,
    address,
    n_snapshots_observed
from all_versions
