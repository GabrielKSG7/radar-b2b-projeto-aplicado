-- GOLD | dimensão município: os 16 municípios do recorte, mesmo os que não tiverem oportunidade no mês.
select
    codigo_municipio_receita                 as municipio_cod,
    municipio,                                -- nome como a Receita grava (sem acento)
    nome_recorte,                             -- nome como foi escrito no YAML do recorte
    '{{ var("uf") }}'                         as uf,
    municipio = 'VARGINHA'                    as fl_polo                -- sede dos escritórios da persona
from {{ source('bronze', 'recorte_municipios') }}
