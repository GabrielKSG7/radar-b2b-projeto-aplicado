{# Falha para cada linha cujo valor (não nulo) esteja fora do intervalo [minimo, maximo]. #}
{% test entre(model, column_name, minimo, maximo) %}
select {{ column_name }}
from {{ model }}
where {{ column_name }} is not null
  and ({{ column_name }} < {{ minimo }} or {{ column_name }} > {{ maximo }})
{% endtest %}
