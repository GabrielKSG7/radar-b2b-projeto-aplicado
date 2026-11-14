{# Teste de CONSISTÊNCIA: nenhuma data pode estar no futuro. #}
{% test data_nao_futura(model, column_name) %}
select {{ column_name }}
from {{ model }}
where {{ column_name }} > current_date
{% endtest %}
