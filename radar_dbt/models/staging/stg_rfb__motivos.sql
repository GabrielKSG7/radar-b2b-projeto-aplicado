-- Tabela de domínio da Receita (motivos): código -> descrição, texto limpo.
select
    {{ limpar_codigo('codigo') }}   as codigo,
    {{ limpar_texto('descricao') }} as descricao
from {{ source('bronze', 'motivos') }}
where competencia = {{ competencia_alvo() }}
