{#
  Macros de limpeza da camada Silver.
  A Bronze guarda o texto exatamente como veio da Receita (tudo VARCHAR). Aqui ele é padronizado.
#}

{# Texto livre: remove caracteres de controle (TAB, CR, LF dentro do campo, C1 restante),
   colapsa espaços repetidos, apara as pontas e transforma vazio em NULL. #}
{% macro limpar_texto(coluna) -%}
    nullif(trim(regexp_replace(regexp_replace({{ coluna }}, '[\x00-\x1F\x7F-\x9F]', ' ', 'g'), '\s+', ' ', 'g')), '')
{%- endmacro %}

{# Código numérico de domínio: só dígitos, sem espaços; vazio vira NULL. #}
{% macro limpar_codigo(coluna) -%}
    nullif(regexp_replace({{ coluna }}, '[^0-9A-Za-z]', '', 'g'), '')
{%- endmacro %}

{# Datas da Receita vêm como AAAAMMDD; "0", "00000000" e datas impossíveis viram NULL. #}
{% macro data_receita(coluna) -%}
    try_strptime(nullif(nullif(trim({{ coluna }}), ''), '00000000'), '%Y%m%d')::date
{%- endmacro %}

{# Valor monetário no padrão brasileiro ("1.234,56" ou "1234,56") -> DECIMAL(18,2). #}
{% macro valor_br(coluna) -%}
    try_cast(replace(replace(trim({{ coluna }}), '.', ''), ',', '.') as decimal(18, 2))
{%- endmacro %}

{# Flag S/N da Receita -> boolean (vazio = NULL, ou seja, "nunca optou / sem registro"). #}
{% macro flag_sn(coluna) -%}
    case upper(trim({{ coluna }})) when 'S' then true when 'N' then false end
{%- endmacro %}

{# Competência alvo: a informada em --vars ou a mais recente carregada com sucesso. #}
{% macro competencia_alvo() -%}
    {%- if var('competencia') -%}
        '{{ var("competencia") }}'
    {%- else -%}
        (select max(competencia) from {{ source('bronze', 'controle_carga') }} where status = 'OK')
    {%- endif -%}
{%- endmacro %}
