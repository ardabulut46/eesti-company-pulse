-- fct_company_quarter must contain every published Company quarter from int_emta__quarters_latest:
-- the joins that add attributes are all left/asof-left joins and must not add or remove rows.
select
    (select count(*) from {{ ref('int_emta__quarters_latest') }} where taxpayer_type = 'Company') as expected_rows,
    (select count(*) from {{ ref('fct_company_quarter') }}) as actual_rows
where expected_rows <> actual_rows
