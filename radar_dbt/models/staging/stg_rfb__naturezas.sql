-- Tabela de domínio da Receita (naturezas): código -> descrição, texto limpo.
select
    {{ limpar_codigo('codigo') }}   as codigo,
    {{ limpar_texto('descricao') }} as descricao
from {{ source('bronze', 'naturezas') }}
where competencia = {{ competencia_alvo() }}
