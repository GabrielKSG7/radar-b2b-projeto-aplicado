-- Opção pelo Simples Nacional e pelo MEI. Só aparecem CNPJs que já optaram algum dia.
select
    upper(trim(cnpj_basico))                    as cnpj_basico,
    {{ flag_sn('opcao_simples') }}              as opcao_simples,
    {{ data_receita('data_opcao_simples') }}    as data_opcao_simples,
    {{ data_receita('data_exclusao_simples') }} as data_exclusao_simples,
    {{ flag_sn('opcao_mei') }}                  as opcao_mei,
    {{ data_receita('data_opcao_mei') }}        as data_opcao_mei,
    {{ data_receita('data_exclusao_mei') }}     as data_exclusao_mei,
    competencia
from {{ source('bronze', 'simples') }}
where competencia = {{ competencia_alvo() }}
