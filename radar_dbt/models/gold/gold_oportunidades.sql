-- GOLD | lista mensal priorizada: só as oportunidades do ICP, na ordem do ranking.
-- É o entregável do produto: o que o escritório abre para decidir quem prospectar primeiro.
select
    f.ranking,
    f.faixa_prioridade,
    f.score,
    f.cnpj_formatado,
    f.razao_social,
    f.nome_fantasia,
    f.municipio,
    f.bairro,
    c.cnae_rotulo                         as cnae_principal,
    c.secao_descricao                     as setor,
    p.porte,
    f.natureza_juridica,
    f.regime_tributario,
    f.capital_social,
    f.matriz_filial,
    f.data_inicio_atividade,
    f.telefone_1                          as telefone,
    f.email,
    f.fl_email_contabilidade,
    f.motivos,
    f.ranking_municipio,
    f.cnpj,
    f.data_referencia,
    f.competencia
from {{ ref('fct_estabelecimentos') }} f
left join {{ ref('dim_cnae') }}  c on c.cnae_cod = f.cnae_cod
left join {{ ref('dim_porte') }} p on p.porte_cod = f.porte_cod
where f.fl_icp
order by f.ranking
