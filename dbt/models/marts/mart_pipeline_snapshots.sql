-- Snapshot catalogue for the app: what was downloaded, when, and how many rows were kept.
select * from {{ ref('stg_pipeline__snapshots') }}
