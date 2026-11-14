-- GOLD | dimensão CNAE: subclasse -> divisão -> seção (hierarquia para o drill do painel).
-- Montada a partir da Silver: só os CNAEs que existem no recorte, já decodificados.
select distinct
    cnae_principal_cod                       as cnae_cod,
    cnae_principal                           as cnae,
    cnae_principal_cod || ' - ' || cnae_principal as cnae_rotulo,
    cnae_divisao                             as divisao,
    cnae_secao                               as secao,
    cnae_secao_descricao                     as secao_descricao,
    cnae_secao || ' - ' || cnae_secao_descricao as secao_rotulo
from {{ ref('slv_estabelecimentos_ativos') }}
