-- GOLD | dimensão calendário: um dia por linha, da abertura mais antiga do recorte até a data de referência.
-- Dá ao painel o filtro de "mês de abertura" e a marcação da janela de prospecção.
with limites as (
    select min(data_inicio_atividade) as inicio, max(data_referencia) as fim, max(data_referencia) as data_referencia
    from {{ ref('slv_estabelecimentos_ativos') }}
),
dias as (
    select cast(unnest(generate_series(inicio, fim, interval 1 day)) as date) as data, data_referencia
    from limites
)
select
    data,
    year(data)                                                 as ano,
    month(data)                                                as mes,
    strftime(data, '%Y-%m')                                    as ano_mes,
    year(data) * 100 + month(data)                             as ano_mes_num,     -- para ordenar o ano_mes no BI
    ['jan','fev','mar','abr','mai','jun','jul','ago','set','out','nov','dez'][month(data)]
        || '/' || strftime(data, '%y')                         as mes_rotulo,
    quarter(data)                                              as trimestre,
    data > data_referencia - to_months({{ var('janela_abertura_meses') }})
                                                               as fl_janela_prospeccao
from dias
