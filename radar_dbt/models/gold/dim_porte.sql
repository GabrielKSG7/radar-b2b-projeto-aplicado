-- GOLD | dimensão porte, com ordem de exibição (do maior para o menor) para o painel.
select
    codigo                                   as porte_cod,
    descricao                                as porte,
    case codigo when '05' then 1 when '03' then 2 when '01' then 3 else 4 end as ordem
from {{ ref('dom_porte_empresa') }}
