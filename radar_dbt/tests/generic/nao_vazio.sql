{# Falha se o modelo não tiver nenhuma linha (pega um recorte que filtrou tudo por engano). #}
{% test nao_vazio(model) %}
select 1 as vazio
where (select count(*) from {{ model }}) = 0
{% endtest %}
