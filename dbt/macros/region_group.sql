{#- Regions used in the pulse marts. Tallinn and Tartu city are separated from their counties
    because the project question compares them with the rest of Estonia. -#}
{% macro region_group(county, municipality) -%}
    case
        when {{ county }} is null then 'Unknown'
        when {{ county }} = 'Harju' and {{ municipality }} = 'Tallinn' then 'Tallinn'
        when {{ county }} = 'Harju' then 'Harju (excl. Tallinn)'
        when {{ county }} = 'Tartu' and {{ municipality }} = 'Tartu linn' then 'Tartu city'
        else 'Rest of Estonia'
    end
{%- endmacro %}
