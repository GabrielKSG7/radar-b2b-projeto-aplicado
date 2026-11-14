{% docs __overview__ %}
# Radar B2B — modelo de dados

Pipeline local (Python + DuckDB + dbt) que transforma os **dados abertos do CNPJ da Receita Federal** numa lista
mensal priorizada de empresas recém-abertas na **microrregião de Varginha (Sul de Minas)**, para prospecção de
escritórios de contabilidade.

| Camada | Onde | O que tem | Sprint |
|---|---|---|---|
| **Bronze** | `bronze.*` (views sobre Parquet) | Dado cru da Receita, tudo texto, particionado por competência | 1 |
| **Staging** | `silver.stg_rfb__*` (views) | Tipagem, limpeza de texto/encoding, um modelo por arquivo da Receita | 2 |
| **Silver** | `silver.slv_*` (tabelas) | Recorte dos 16 municípios, 1 linha por CNPJ, domínios decodificados, flags de negócio | 2 |
| **Gold** | `gold.*` (tabelas) | Estrela (`fct_estabelecimentos` + `dim_*`), regra de ICP, score 0–100, faixa A/B/C, ranking e motivos (`gold_oportunidades`) | 3 |

**Grão da Silver:** um estabelecimento (CNPJ de 14 posições — alfanumérico desde jul/2026).

**Domínios decodificados:** situação cadastral, motivo, CNAE (subclasse + seção A–U), natureza jurídica,
porte e matriz/filial. Os que a Receita não publica em arquivo estão versionados como *seeds* (`dom_*`).

**Qualidade:** testes de unicidade, completude mínima, integridade referencial, formato do CNPJ,
datas não futuras e deduplicação sem perda (`dbt build` roda tudo na ordem do grafo).
{% enddocs %}
