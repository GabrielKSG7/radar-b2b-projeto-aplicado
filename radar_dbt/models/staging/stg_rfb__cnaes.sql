-- Tabela de domínio da Receita (cnaes): código -> descrição, texto limpo.
select
    {{ limpar_codigo('codigo') }}   as codigo,
    {{ limpar_texto('descricao') }} as descricao
from {{ source('bronze', 'cnaes') }}
where competencia = {{ competencia_alvo() }}
