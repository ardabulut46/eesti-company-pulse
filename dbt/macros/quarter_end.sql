{% macro quarter_end(year, quarter) -%}
    (make_date({{ year }}, {{ quarter }} * 3, 1) + interval 1 month - interval 1 day)::date
{%- endmacro %}
