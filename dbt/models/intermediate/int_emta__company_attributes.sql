-- Name, sector, and county as published in each EMTA release. EMTA repeats the values current
-- at the release date on every year's row, so they describe the company at the release date,
-- not in the tax year. Keeping one row per release builds a sector/county history.
select distinct
    y.registry_code,
    y.taxpayer_type,
    y.release_date,
    y.taxpayer_name,
    y.activity_section_name,
    s.section_code,
    y.county,
    y.municipality,
    {{ region_group('y.county', 'y.municipality') }} as region_group
from {{ ref('stg_emta__taxpayer_years') }} y
left join {{ ref('emtak_sections') }} s
    on s.section_name_emta = y.activity_section_name
