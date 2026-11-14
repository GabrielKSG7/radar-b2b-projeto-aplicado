-- O ranking tem que respeitar o score: nenhuma oportunidade pode ficar atrás de outra com score menor.
select atual.ranking, atual.score, proxima.ranking as ranking_seguinte, proxima.score as score_seguinte
from {{ ref('gold_oportunidades') }} atual
join {{ ref('gold_oportunidades') }} proxima on proxima.ranking = atual.ranking + 1
where proxima.score > atual.score
