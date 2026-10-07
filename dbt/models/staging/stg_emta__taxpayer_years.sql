-- One row per taxpayer x tax year x EMTA release (snapshot). Wide: quarters are columns.
-- Casts are strict: a value that is not an integer fails the build instead of becoming NULL.
with source as (
    select * from {{ source('lake', 'emta_current') }}
    union all by name
    select * from {{ source('lake', 'emta_history') }}
)

select
    "Registry code"                                    as registry_code,
    "Type"                                             as taxpayer_type,
    nullif(trim("Name"), '')                           as taxpayer_name,
    nullif(trim("Activity"), '')                       as activity_section_name,
    nullif(trim("County"), '')                         as county_raw,
    -- "Harju ( Tallinn )" -> county "Harju", municipality "Tallinn"
    nullif(trim(regexp_extract("County", '^([^(]+)\(', 1)), '')             as county,
    nullif(trim(regexp_extract("County", '\(\s*([^)]+?)\s*\)\s*$', 1)), '')  as municipality,
    cast("Year" as integer)                            as tax_year,
    strptime("Data date", '%d.%m.%Y')::date            as release_date,

    cast("State taxes I qtr" as bigint)                as state_taxes_q1,
    cast("State taxes II qtr" as bigint)               as state_taxes_q2,
    cast("State taxes III qtr" as bigint)              as state_taxes_q3,
    cast("State taxes IV qtr" as bigint)               as state_taxes_q4,
    cast("Labour taxes and payments I qtr" as bigint)  as labour_taxes_q1,
    cast("Labour taxes and payments II qtr" as bigint) as labour_taxes_q2,
    cast("Labour taxes and payments III qtr" as bigint) as labour_taxes_q3,
    cast("Labour taxes and payments IV qtr" as bigint) as labour_taxes_q4,
    cast("Turnover I qtr" as bigint)                   as turnover_q1,
    cast("Turnover II qtr" as bigint)                  as turnover_q2,
    cast("Turnover III qtr" as bigint)                 as turnover_q3,
    cast("Turnover IV qtr" as bigint)                  as turnover_q4,
    cast("Number of employees I qtr" as integer)       as employees_q1,
    cast("Number of employees II qtr" as integer)      as employees_q2,
    cast("Number of employees III qtr" as integer)     as employees_q3,
    cast("Number of employees IV qtr" as integer)      as employees_q4,

    _source,
    _snapshot_id,
    _source_row,
    _retrieved_at
from source
