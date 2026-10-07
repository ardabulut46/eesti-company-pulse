-- One row per legal entity x register snapshot (daily basic data).
-- Self-employed persons (FIE) were removed when the snapshot was converted to Parquet.
select
    ariregistri_kood                                   as registry_code,
    nullif(trim(nimi), '')                             as company_name,
    ettevotja_oiguslik_vorm                            as legal_form,
    nullif(ettevotja_oigusliku_vormi_alaliik, '')      as legal_form_subtype,
    nullif(kmkr_nr, '')                                as vat_number,
    ettevotja_staatus                                  as status_code,
    ettevotja_staatus_tekstina                         as status_name,
    strptime(ettevotja_esmakande_kpv, '%d.%m.%Y')::date as first_entry_date,
    nullif(asukoha_ehak_kood, '')                      as ehak_code,
    nullif(asukoha_ehak_tekstina, '')                  as ehak_name,
    -- "Pirita linnaosa, Tallinn, Harju maakond" -> "Harju"
    nullif(regexp_extract(asukoha_ehak_tekstina, '([^,]+) maakond\s*$', 1), '') as county,
    nullif(indeks_ettevotja_aadressis, '')             as postal_code,
    nullif(ads_normaliseeritud_taisaadress, '')        as address,

    cast(left(_snapshot_id, 10) as date)               as snapshot_date,
    _snapshot_id,
    _source_row,
    _retrieved_at
from {{ source('lake', 'rik_basic') }}
