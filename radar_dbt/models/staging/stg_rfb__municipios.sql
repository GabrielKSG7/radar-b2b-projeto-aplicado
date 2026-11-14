-- Tabela de domínio da Receita (municipios): código -> descrição, texto limpo.
select
    {{ limpar_codigo('codigo') }}   as codigo,
    {{ limpar_texto('descricao') }} as descricao
from {{ source('bronze', 'municipios') }}
where competencia = {{ competencia_alvo() }}
