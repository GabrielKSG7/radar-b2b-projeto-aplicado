-- Estabelecimentos (matriz e filiais) da competência alvo, tipados e com texto limpo.
-- Ainda é o Brasil inteiro: o recorte do MVP é aplicado em slv_estabelecimentos_recorte.
with origem as (
    select * from {{ source('bronze', 'estabelecimentos') }}
    where competencia = {{ competencia_alvo() }}
)

select
    -- chave: CNPJ alfanumérico desde jul/2026 -> continua texto, nunca número
    upper(trim(cnpj_basico)) || upper(trim(cnpj_ordem)) || trim(cnpj_dv)    as cnpj,
    upper(trim(cnpj_basico))                                                as cnpj_basico,
    upper(trim(cnpj_ordem))                                                 as cnpj_ordem,
    trim(cnpj_dv)                                                           as cnpj_dv,
    {{ limpar_codigo('identificador_matriz_filial') }}                      as matriz_filial_cod,
    {{ limpar_texto('nome_fantasia') }}                                     as nome_fantasia,

    -- situação cadastral
    lpad({{ limpar_codigo('situacao_cadastral') }}, 2, '0')                 as situacao_cadastral_cod,
    {{ data_receita('data_situacao_cadastral') }}                           as data_situacao_cadastral,
    lpad({{ limpar_codigo('motivo_situacao_cadastral') }}, 2, '0')          as motivo_situacao_cod,
    {{ limpar_texto('situacao_especial') }}                                 as situacao_especial,
    {{ data_receita('data_situacao_especial') }}                            as data_situacao_especial,

    -- atividade
    {{ data_receita('data_inicio_atividade') }}                             as data_inicio_atividade,
    {{ limpar_codigo('cnae_fiscal_principal') }}                            as cnae_principal_cod,
    -- lista "6201501,6202300" -> array; vazio -> lista vazia
    list_filter(
        list_transform(string_split(coalesce(cnae_fiscal_secundaria, ''), ','), lambda x: trim(x)),
        lambda x: x <> ''
    )                                                                       as cnaes_secundarios,

    -- endereço
    {{ limpar_texto('tipo_logradouro') }}                                   as tipo_logradouro,
    {{ limpar_texto('logradouro') }}                                        as logradouro,
    {{ limpar_texto('numero') }}                                            as numero,
    {{ limpar_texto('complemento') }}                                       as complemento,
    {{ limpar_texto('bairro') }}                                            as bairro,
    {{ limpar_codigo('cep') }}                                              as cep,
    upper(trim(uf))                                                         as uf,
    {{ limpar_codigo('municipio') }}                                        as municipio_cod,
    {{ limpar_codigo('pais') }}                                             as pais_cod,
    {{ limpar_texto('nome_cidade_exterior') }}                              as nome_cidade_exterior,

    -- contato (DDD + número; e-mail sempre minúsculo)
    nullif(coalesce({{ limpar_codigo('ddd_1') }}, '') || coalesce({{ limpar_codigo('telefone_1') }}, ''), '') as telefone_1,
    nullif(coalesce({{ limpar_codigo('ddd_2') }}, '') || coalesce({{ limpar_codigo('telefone_2') }}, ''), '') as telefone_2,
    lower({{ limpar_texto('correio_eletronico') }})                         as email,

    -- linhagem
    competencia,
    _arquivo_origem,
    _carregado_em
from origem
