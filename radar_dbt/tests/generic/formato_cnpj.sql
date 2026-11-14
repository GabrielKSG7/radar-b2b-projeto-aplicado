{#
  Teste de FORMATO do CNPJ completo (14 posições).
  Desde jul/2026 a raiz e a ordem podem ter letras (CNPJ alfanumérico); os 2 dígitos verificadores continuam numéricos.
#}
{% test formato_cnpj(model, column_name) %}
select {{ column_name }}
from {{ model }}
where {{ column_name }} is not null
  and not regexp_full_match({{ column_name }}, '[0-9A-Z]{12}[0-9]{2}')
{% endtest %}
