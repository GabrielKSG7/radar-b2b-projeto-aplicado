-- SILVER: estabelecimentos ATIVOS do recorte — a base limpa que a Gold (Sprint 3) vai priorizar.
select *
from {{ ref('slv_estabelecimentos_recorte') }}
where fl_ativo
