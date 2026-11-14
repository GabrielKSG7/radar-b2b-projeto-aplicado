-- A deduplicação só pode remover REPETIÇÕES: cada CNPJ distinto do recorte na staging
-- precisa existir exatamente uma vez na Silver. Retorna os CNPJs perdidos (0 linhas = passou).
with origem as (
    select distinct e.cnpj
    from {{ ref('stg_rfb__estabelecimentos') }} e
    join {{ source('bronze', 'recorte_municipios') }} r on e.municipio_cod = r.codigo_municipio_receita
    where e.uf = '{{ var("uf") }}'
)
select o.cnpj
from origem o
anti join {{ ref('slv_estabelecimentos_recorte') }} s using (cnpj)
