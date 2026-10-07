-- The wide -> long unpivot must produce exactly four rows per staging row (no silent drops).
select
    (select count(*) from {{ ref('stg_emta__taxpayer_years') }}) * 4 as expected_rows,
    (select count(*) from {{ ref('int_emta__quarters_all_releases') }}) as actual_rows
where expected_rows <> actual_rows
