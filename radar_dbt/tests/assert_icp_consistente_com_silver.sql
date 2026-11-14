-- A Gold não pode perder nem inventar oportunidade: a contagem do ICP tem que bater
-- com a combinação das flags da Silver, e nenhuma oportunidade pode violar uma regra.
with silver as (
    select count(*) as n
    from {{ ref('slv_estabelecimentos_ativos') }}
    where fl_aberto_na_janela and not fl_mei and fl_natureza_empresarial and not fl_cnae_excluido
      {%- if var('somente_matriz') %} and matriz_filial_cod = '1'{% endif %}
),
gold as (
    select count(*) as n,
           count(*) filter (where fl_mei or not fl_natureza_empresarial or fl_cnae_excluido
                                  or not fl_aberto_na_janela
                                  {%- if var('somente_matriz') %} or not fl_matriz{% endif %}) as violacoes
    from {{ ref('fct_estabelecimentos') }}
    where fl_icp
)
select silver.n as icp_silver, gold.n as icp_gold, gold.violacoes
from silver, gold
where silver.n <> gold.n or gold.violacoes > 0
