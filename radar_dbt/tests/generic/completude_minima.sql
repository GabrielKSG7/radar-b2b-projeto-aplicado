{#
  Teste de COMPLETUDE: falha se o percentual de valores preenchidos da coluna
  ficar abaixo do mínimo aceitável. Retorna uma linha (= falha) com o percentual medido.
  Uso no YAML:
      - completude_minima:
          arguments:
            minimo: 0.99
#}
{% test completude_minima(model, column_name, minimo=1.0) %}
with medida as (
    select count(*) as total,
           count({{ column_name }}) as preenchidos,
           count({{ column_name }}) / nullif(count(*), 0)::double as completude
    from {{ model }}
)
select * from medida
where total > 0 and completude < {{ minimo }}
{% endtest %}
