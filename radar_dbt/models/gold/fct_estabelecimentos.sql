{#-
  GOLD | fato de estabelecimentos ativos do recorte (grão: 1 CNPJ ativo).
  É aqui que a regra de ICP vira filtro e que cada oportunidade recebe score, faixa e ranking.
  Pesos e faixas vêm de config/recorte_mvp.yml (seção "ranking"), repassados pelo run_sprint3.py.
-#}
{%- set r = var('ranking') -%}
{%- set w = r['pesos'] -%}
{%- set sc = r['sinal_contador'] -%}
{%- set ep = r['estrutura_patrimonial'] -%}
{%- set sx = r['setores_complexos'] -%}
{%- set ri = r['regime_incerto'] -%}

-- Quantas empresas sem relação entre si (raízes de CNPJ diferentes) usam o mesmo e-mail no recorte.
-- Na abertura, o cadastro costuma levar o e-mail do escritório contábil que fez o registro.
with uso_email as (
    select email, count(distinct cnpj_basico) as empresas_mesmo_email
    from {{ ref('slv_estabelecimentos_ativos') }}
    where email is not null
    group by email
),

base as (
    select
        a.*,
        date_diff('day', a.data_inicio_atividade, a.data_referencia)                       as dias_desde_abertura,
        date_diff('day', a.data_referencia - to_months({{ var('janela_abertura_meses') }}),
                  a.data_referencia)                                                        as dias_janela,
        case when a.fl_mei then 'MEI'
             when a.opcao_simples then 'Simples Nacional'
             else 'Fora do Simples' end                                                     as regime_tributario,
        -- REGRA DE ICP, na mesma ordem do funil: o primeiro critério que reprova explica a exclusão
        case when not a.fl_aberto_na_janela     then '1. Aberta antes da janela'
             when a.fl_mei                      then '2. MEI'
             when not a.fl_natureza_empresarial then '3. Natureza não empresarial'
             when a.fl_cnae_excluido            then '4. CNAE fora do público'
             {%- if var('somente_matriz') %}
             when a.matriz_filial_cod <> '1'    then '5. Filial (contabilidade na matriz)'
             {%- endif %}
             else '6. Oportunidade (ICP)' end                                               as etapa_funil,
        a.natureza_juridica_cod <> '2135'                                                   as fl_sociedade,
        coalesce(u.empresas_mesmo_email, 0)                                                 as empresas_mesmo_email,
        coalesce(regexp_matches(a.email, '{{ sc["palavras"] | join("|") }}')
                 or u.empresas_mesmo_email >= {{ sc['min_empresas_mesmo_email'] }}, false)  as fl_email_contabilidade,
        (   {%- for c in ep['cnae_prefixos'] %} starts_with(a.cnae_principal_cod, '{{ c }}') or{% endfor %}
            {%- for t in ep['termos_razao_social'] %} contains(a.razao_social, '{{ t }}'){% if not loop.last %} or{% endif %}{% endfor %}
        )                                                                                   as fl_estrutura_patrimonial,
        ({%- for c in sx['cnae_prefixos'] %} starts_with(a.cnae_principal_cod, '{{ c }}'){% if not loop.last %} or{% endif %}{% endfor %})
                                                                                            as fl_setor_complexo
    from {{ ref('slv_estabelecimentos_ativos') }} a
    left join uso_email u on u.email = a.email
),

pontos as (
    select
        *,
        etapa_funil = '6. Oportunidade (ICP)'                                               as fl_icp,
        round({{ w['recencia'] }} * greatest(0, 1 - dias_desde_abertura / dias_janela::double), 1) as pts_recencia,
        case when opcao_simples then {{ r['pontos_simples'] }}
             -- recém-aberta, capital baixo e setor comum: "fora do Simples" pode ser só a opção ainda não processada
             when dias_desde_abertura < {{ ri['dias_max'] }} and coalesce(capital_social, 0) < {{ ri['capital_ate'] }}
                  and not fl_setor_complexo then {{ r['pontos_simples'] }}
             else {{ w['regime'] }} end                                                     as pts_regime,
        dias_desde_abertura < {{ ri['dias_max'] }} and coalesce(capital_social, 0) < {{ ri['capital_ate'] }}
            and not fl_setor_complexo and not coalesce(opcao_simples, false)                as fl_regime_incerto,
        case when fl_setor_complexo then {{ sx['bonus'] }} else 0 end                       as pts_setor,
        case when fl_estrutura_patrimonial then {{ ep['penalidade'] }} else 0 end           as pts_penalidade_estrutura,
        case porte_cod when '05' then {{ w['porte'] }}
                       when '03' then {{ (w['porte'] * 2 / 3) | round | int }}
                       when '01' then {{ (w['porte'] / 3) | round | int }}
                       else 0 end                                                           as pts_porte,
        case
            {%- for minimo, pts in r['faixas_capital'] %}
            when capital_social >= {{ minimo }} then {{ pts }}
            {%- endfor %}
            else 0 end                                                                      as pts_capital,
        case when fl_sociedade then {{ w['sociedade'] }} else 0 end                         as pts_sociedade,
        case when qtd_cnaes_secundarios >= 3 then {{ w['complexidade'] }} else 0 end        as pts_complexidade,
        case when email is not null and telefone_1 is not null then {{ w['contato'] }}
             when email is not null or telefone_1 is not null then {{ w['contato'] / 2 }}
             else 0 end                                                                     as pts_contato,
        case when fl_email_contabilidade then {{ sc['penalidade'] }} else 0 end             as pts_penalidade_contador
    from base
),

score as (
    select
        *,
        case when fl_icp then
            round(least(100, greatest(0, pts_recencia + pts_regime + pts_porte + pts_capital + pts_sociedade
                              + pts_complexidade + pts_contato + pts_setor
                              - pts_penalidade_contador - pts_penalidade_estrutura)), 1)
        end                                                                                 as score
    from pontos
)

select
    -- chaves (estrela)
    cnpj,
    municipio_cod,
    cnae_principal_cod                                                     as cnae_cod,
    porte_cod,
    data_inicio_atividade,

    -- identificação e contato (para a lista de prospecção)
    cnpj_formatado,
    razao_social,
    nome_fantasia,
    municipio,
    bairro,
    telefone_1,
    email,

    -- atributos do perfil
    natureza_juridica,
    matriz_filial,
    regime_tributario,
    capital_social,
    qtd_cnaes_secundarios,
    dias_desde_abertura,
    meses_desde_abertura,
    strftime(data_inicio_atividade, '%Y-%m')                               as ano_mes_abertura,

    -- regra de ICP
    fl_aberto_na_janela,
    fl_mei,
    fl_natureza_empresarial,
    fl_cnae_excluido,
    matriz_filial_cod = '1'                                                as fl_matriz,
    fl_sociedade,
    fl_email_contabilidade,
    empresas_mesmo_email,
    fl_estrutura_patrimonial,
    fl_setor_complexo,
    fl_regime_incerto,
    fl_icp,
    etapa_funil,

    -- priorização (só para oportunidades do ICP)
    case when fl_icp then pts_recencia end                                 as pts_recencia,
    case when fl_icp then pts_regime end                                   as pts_regime,
    case when fl_icp then pts_porte end                                    as pts_porte,
    case when fl_icp then pts_capital end                                  as pts_capital,
    case when fl_icp then pts_sociedade end                                as pts_sociedade,
    case when fl_icp then pts_complexidade end                             as pts_complexidade,
    case when fl_icp then pts_contato end                                  as pts_contato,
    case when fl_icp then pts_penalidade_contador end                      as pts_penalidade_contador,
    case when fl_icp then pts_setor end                                    as pts_setor,
    case when fl_icp then pts_penalidade_estrutura end                     as pts_penalidade_estrutura,
    score,
    case when score >= {{ r['faixas_prioridade']['A'] }} then 'A'
         when score >= {{ r['faixas_prioridade']['B'] }} then 'B'
         when score is not null then 'C' end                               as faixa_prioridade,
    case when fl_icp then row_number() over (
        partition by fl_icp order by score desc, data_inicio_atividade desc, cnpj) end      as ranking,
    case when fl_icp then row_number() over (
        partition by fl_icp, municipio_cod order by score desc, data_inicio_atividade desc, cnpj) end
                                                                           as ranking_municipio,
    -- o "porquê" do score, em linguagem de escritório
    case when fl_icp then concat_ws(' · ',
        case when dias_desde_abertura = 0 then 'aberta no dia da base'
             when dias_desde_abertura < 31 then 'aberta há ' || dias_desde_abertura || ' dias'
             else 'aberta há ' || meses_desde_abertura || (case when meses_desde_abertura = 1 then ' mês' else ' meses' end) end,
        case when fl_regime_incerto then 'fora do simples (recém-aberta: regime ainda incerto)' else lower(regime_tributario) end,
        'porte ' || lower(coalesce(porte, 'não informado')),
        case when capital_social >= 1000000 then 'capital R$ ' || replace(cast(round(capital_social / 1000000, 1) as varchar), '.', ',') || ' mi'
             when capital_social >= 1000    then 'capital R$ ' || cast(round(capital_social / 1000) as bigint) || ' mil'
             else 'capital abaixo de R$ 1 mil' end,
        case when fl_sociedade then 'sociedade' else 'empresário individual' end,
        case qtd_cnaes_secundarios when 0 then 'sem CNAE secundário' when 1 then '1 CNAE secundário'
             else qtd_cnaes_secundarios || ' CNAEs secundários' end,
        case when pts_contato = {{ w['contato'] }} then 'contato completo'
             when pts_contato > 0 then 'contato parcial' else 'sem contato' end,
        case when fl_setor_complexo then 'setor de rotina fiscal pesada' end,
        case when fl_estrutura_patrimonial then 'ATENÇÃO: holding/participação/SPE (pouca rotina contábil)' end,
        case when fl_email_contabilidade then 'ATENÇÃO: e-mail de escritório contábil no cadastro' end
    ) end                                                                  as motivos,

    -- linhagem
    data_referencia,
    competencia
from score
