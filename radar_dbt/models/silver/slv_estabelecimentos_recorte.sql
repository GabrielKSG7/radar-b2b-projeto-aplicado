-- SILVER: todos os estabelecimentos dos 16 municípios do recorte (qualquer situação cadastral),
-- um registro por CNPJ, enriquecidos com a empresa, o Simples/MEI e os domínios decodificados.
-- As regras de ICP (MEI, natureza, janela, CNAE) viram FLAGS aqui e são aplicadas como filtro na Gold (Sprint 3).

with recorte as (
    select codigo_municipio_receita as municipio_cod, municipio
    from {{ source('bronze', 'recorte_municipios') }}
),

estabelecimentos as (
    select e.*, r.municipio
    from {{ ref('stg_rfb__estabelecimentos') }} e
    join recorte r using (municipio_cod)
    where e.uf = '{{ var("uf") }}'      -- código de município da Receita se repete entre UFs
),

-- DEDUPLICAÇÃO 1: um registro por CNPJ completo. Em caso de repetição, fica o de situação mais recente.
estabelecimentos_dedup as (
    select *,
           count(*) over (partition by cnpj) as ocorrencias_na_origem
    from estabelecimentos
    qualify row_number() over (
        partition by cnpj
        order by data_situacao_cadastral desc nulls last, _arquivo_origem desc
    ) = 1
),

-- DEDUPLICAÇÃO 2: empresa e Simples são por raiz (cnpj_basico). Primeiro filtra só as raízes do recorte
-- (semi-join, evita varrer 70 milhões de linhas numa janela) e depois garante uma linha por raiz,
-- para o JOIN não multiplicar estabelecimentos.
empresas as (
    select *
    from {{ ref('stg_rfb__empresas') }}
    where cnpj_basico in (select cnpj_basico from estabelecimentos_dedup)
    qualify row_number() over (partition by cnpj_basico order by capital_social desc nulls last) = 1
),

simples as (
    select *
    from {{ ref('stg_rfb__simples') }}
    where cnpj_basico in (select cnpj_basico from estabelecimentos_dedup)
    qualify row_number() over (partition by cnpj_basico order by data_opcao_simples desc nulls last) = 1
),

-- Data de referência da base = abertura mais recente registrada (a Receita não publica a data de extração).
referencia as (
    select max(data_inicio_atividade) as data_referencia
    from estabelecimentos_dedup
    where data_inicio_atividade <= current_date
),

final as (
    select
        -- identificação
        e.cnpj,
        e.cnpj_basico,
        substr(e.cnpj, 1, 2) || '.' || substr(e.cnpj, 3, 3) || '.' || substr(e.cnpj, 6, 3) || '/'
            || substr(e.cnpj, 9, 4) || '-' || substr(e.cnpj, 13, 2)        as cnpj_formatado,
        e.matriz_filial_cod,
        mf.descricao                                                       as matriz_filial,
        emp.razao_social,
        e.nome_fantasia,

        -- situação cadastral (código + descrição)
        e.situacao_cadastral_cod,
        sit.descricao                                                      as situacao_cadastral,
        e.data_situacao_cadastral,
        e.motivo_situacao_cod,
        mot.descricao                                                      as motivo_situacao,

        -- atividade econômica (CNAE decodificado + hierarquia seção/divisão)
        e.data_inicio_atividade,
        date_diff('month', e.data_inicio_atividade, ref.data_referencia)  as meses_desde_abertura,
        e.cnae_principal_cod,
        cnae.descricao                                                     as cnae_principal,
        substr(e.cnae_principal_cod, 1, 2)                                 as cnae_divisao,
        sec.secao                                                          as cnae_secao,
        sec.descricao_secao                                                as cnae_secao_descricao,
        e.cnaes_secundarios,
        len(e.cnaes_secundarios)                                           as qtd_cnaes_secundarios,

        -- empresa
        emp.natureza_juridica_cod,
        nat.descricao                                                      as natureza_juridica,
        emp.porte_cod,
        porte.descricao                                                    as porte,
        emp.capital_social,
        s.opcao_simples,
        s.data_opcao_simples,
        s.opcao_mei,

        -- localização e contato
        e.uf,
        e.municipio_cod,
        e.municipio,
        e.bairro,
        concat_ws(' ', e.tipo_logradouro, e.logradouro)                    as logradouro,
        e.numero,
        e.complemento,
        e.cep,
        e.telefone_1,
        e.telefone_2,
        e.email,

        -- FLAGS de negócio (insumo da regra de ICP na Gold)
        e.situacao_cadastral_cod = '{{ var("situacao_ativa") }}'          as fl_ativo,
        coalesce(s.opcao_mei, false)                                       as fl_mei,  -- 'S' = optante atual do MEI
        (
            {%- for p in var('natureza_juridica_prefixos') %}
            starts_with(emp.natureza_juridica_cod, '{{ p }}'){% if not loop.last %} or{% endif %}
            {%- endfor %}
        )                                                                  as fl_natureza_empresarial,
        substr(e.cnae_principal_cod, 1, 2) in (
            {%- for d in var('cnae_divisoes_excluidas') %}'{{ d }}'{% if not loop.last %}, {% endif %}{% endfor -%}
        )                                                                  as fl_cnae_excluido,
        e.data_inicio_atividade > ref.data_referencia
            - to_months({{ var('janela_abertura_meses') }})               as fl_aberto_na_janela,

        -- linhagem e qualidade
        ref.data_referencia,
        e.ocorrencias_na_origem,
        e.competencia,
        e._arquivo_origem
    from estabelecimentos_dedup e
    cross join referencia ref
    left join empresas emp                                   on emp.cnpj_basico = e.cnpj_basico
    left join simples s                                      on s.cnpj_basico = e.cnpj_basico
    left join {{ ref('stg_rfb__cnaes') }} cnae               on cnae.codigo = e.cnae_principal_cod
    left join {{ ref('stg_rfb__naturezas') }} nat            on nat.codigo = emp.natureza_juridica_cod
    left join {{ ref('stg_rfb__motivos') }} mot              on mot.codigo = e.motivo_situacao_cod
    left join {{ ref('dom_situacao_cadastral') }} sit        on sit.codigo = e.situacao_cadastral_cod
    left join {{ ref('dom_porte_empresa') }} porte           on porte.codigo = emp.porte_cod
    left join {{ ref('dom_matriz_filial') }} mf              on mf.codigo = e.matriz_filial_cod
    left join {{ ref('dom_cnae_secao') }} sec                on sec.divisao = substr(e.cnae_principal_cod, 1, 2)
)

select * from final
