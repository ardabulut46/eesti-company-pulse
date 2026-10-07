-- SCD Type 2 register history, exposed for marts and the app (see int_rik__company_history).
select * from {{ ref('int_rik__company_history') }}
