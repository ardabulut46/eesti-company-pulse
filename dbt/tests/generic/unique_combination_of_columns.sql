{#- Fails with the duplicated key values. Declares the grain of a model. -#}
{% test unique_combination_of_columns(model, combination_of_columns) %}
select {{ combination_of_columns | join(', ') }}, count(*) as n_rows
from {{ model }}
group by all
having count(*) > 1
{% endtest %}
