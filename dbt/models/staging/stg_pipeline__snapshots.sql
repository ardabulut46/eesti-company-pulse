-- Snapshot catalogue joined with conversion counts. Grain: source x snapshot.
with manifest as (
    select
        source,
        url,
        split_part(local_path, '/', 3)                 as snapshot_id,
        strptime(retrieved_at_utc, '%Y-%m-%dT%H:%M:%SZ') as retrieved_at,
        case when last_modified_utc <> ''
             then strptime(last_modified_utc, '%Y-%m-%dT%H:%M:%SZ') end as publisher_last_modified_at,
        nullif(cutoff_date, '')::date                  as cutoff_date,
        size_bytes::bigint                             as size_bytes,
        sha256,
        local_path
    from {{ source('pipeline', 'manifest') }}
),

conversions as (
    select
        source,
        snapshot_id,
        sha256,
        rows_total::bigint   as rows_total,
        rows_kept::bigint    as rows_kept,
        rows_dropped::bigint as rows_dropped,
        strptime(converted_at_utc, '%Y-%m-%dT%H:%M:%SZ') as converted_at
    from {{ source('pipeline', 'conversions') }}
)

select
    m.*,
    c.rows_total,
    c.rows_kept,
    c.rows_dropped,
    c.converted_at,
    c.sha256 is not null as is_converted
from manifest m
left join conversions c
    on c.source = m.source and c.snapshot_id = m.snapshot_id and c.sha256 = m.sha256
