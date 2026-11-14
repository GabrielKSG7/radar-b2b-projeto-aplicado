-- Empresas (dados da raiz do CNPJ, comuns à matriz e às filiais), tipadas.
select
    upper(trim(cnpj_basico))                                     as cnpj_basico,
    {{ limpar_texto('razao_social') }}                           as razao_social,
    {{ limpar_codigo('natureza_juridica') }}                     as natureza_juridica_cod,
    {{ limpar_codigo('qualificacao_responsavel') }}              as qualificacao_responsavel_cod,
    {{ valor_br('capital_social') }}                             as capital_social,
    lpad({{ limpar_codigo('porte_empresa') }}, 2, '0')           as porte_cod,
    {{ limpar_texto('ente_federativo_responsavel') }}            as ente_federativo_responsavel,
    competencia,
    _arquivo_origem
from {{ source('bronze', 'empresas') }}
where competencia = {{ competencia_alvo() }}
