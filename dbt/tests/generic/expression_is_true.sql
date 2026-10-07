{#- Fails with every row where the expression is not true (NULL counts as a failure).
    Limit the rows checked with the built-in `config: {where: ...}`. -#}
{% test expression_is_true(model, expression, column_name=None) %}
select *
from {{ model }}
where not coalesce(({{ expression }}), false)
{% endtest %}
