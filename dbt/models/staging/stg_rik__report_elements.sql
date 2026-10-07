-- One row per element row in the long (EAV) element files, all fiscal-year files unioned.
select
    report_id,
    tabel                                              as table_name,
    elemendi_label                                     as element_label,
    nullif(elemendi_nimetus, '')                       as element_code,
    vaartus                                            as value_text,
    -- Observed: at most one decimal digit, max ~1.7e10. DECIMAL(18,2) is exact for that range.
    cast(vaartus as decimal(18, 2))                    as value,
    cast(right(_source, 4) as integer)                 as file_fiscal_year,

    _cutoff_date                                       as release_cutoff_date,
    _source,
    _snapshot_id,
    _source_row,
    _retrieved_at
from {{ source('lake', 'rik_elements') }}
