"""Etapa 4 — Carga da Bronze no DuckDB e validação da contagem de registros.

Cria data/radar.duckdb com:
  bronze.<tabela>          -> views sobre os Parquet (não duplica dado em disco)
  bronze.controle_carga    -> linhas no arquivo de origem x linhas no Parquet, por arquivo
  bronze.recorte_municipios-> municípios do recorte resolvidos para o código da Receita
E imprime o relatório de validação (usado como evidência da Sprint 1).
"""
from __future__ import annotations

import argparse
import csv

import duckdb

from radar.comum import CONTROLE_CSV, DB_PATH, DIR_BRONZE, RAIZ, carregar_recorte, logger

log = logger("duckdb")


def _imprimir(titulo: str, rel: duckdb.DuckDBPyRelation) -> None:
    print(f"\n=== {titulo} ===")
    rel.show(max_width=200)


def executar(competencia: str | None = None) -> dict:
    con = duckdb.connect(str(DB_PATH))
    con.execute("CREATE SCHEMA IF NOT EXISTS bronze")

    tabelas = sorted(p.name for p in DIR_BRONZE.iterdir() if p.is_dir())
    for t in tabelas:
        glob = (DIR_BRONZE / t).resolve().as_posix() + "/*/*.parquet"   # caminho absoluto: o dbt roda de outra pasta
        con.execute(f"CREATE OR REPLACE VIEW bronze.{t} AS SELECT * FROM read_parquet('{glob}', hive_partitioning=true, hive_types={{'competencia': 'VARCHAR'}})")
    con.execute(f"""CREATE OR REPLACE TABLE bronze.controle_carga AS
                    SELECT * FROM read_csv('{CONTROLE_CSV.as_posix()}', header=true, types={{'competencia': 'VARCHAR', 'tabela': 'VARCHAR'}})""")
    comp = competencia or con.execute("SELECT max(competencia) FROM bronze.controle_carga").fetchone()[0]
    log.info("Banco %s atualizado: %d views na camada bronze | competência %s", DB_PATH.name, len(tabelas), comp)

    # 1) Validação arquivo a arquivo (gerada na conversão)
    por_tabela = con.sql(f"""
        SELECT tabela,
               count(*)                                   AS arquivos,
               sum(linhas_origem)                         AS linhas_origem,
               sum(linhas_parquet)                        AS linhas_parquet,
               sum(linhas_origem) - sum(linhas_parquet)   AS diferenca,
               count(*) FILTER (WHERE status <> 'OK')     AS arquivos_divergentes
        FROM bronze.controle_carga WHERE competencia = '{comp}'
        GROUP BY tabela ORDER BY linhas_parquet DESC""")
    _imprimir(f"VALIDAÇÃO DA CARGA BRONZE — competência {comp}", por_tabela)

    # 2) Consistência: o que o DuckDB enxerga pelas views bate com o controle?
    partes = [f"SELECT '{t}' AS tabela, count(*) AS linhas_view FROM bronze.{t} WHERE competencia = '{comp}'" for t in tabelas]
    consist = con.sql(f"""
        WITH v AS ({' UNION ALL '.join(partes)})
        SELECT v.tabela, v.linhas_view, c.linhas_parquet,
               CASE WHEN v.linhas_view = c.linhas_parquet THEN 'OK' ELSE 'DIVERGENTE' END AS status
        FROM v JOIN (SELECT tabela, sum(linhas_parquet) linhas_parquet FROM bronze.controle_carga
                     WHERE competencia = '{comp}' GROUP BY 1) c USING (tabela)
        ORDER BY v.linhas_view DESC""")
    _imprimir("CONSISTÊNCIA VIEWS DUCKDB x CONTROLE", consist)

    # 3) Recorte do MVP resolvido para os códigos da Receita
    recorte = carregar_recorte()
    nomes = recorte["regiao"]["municipios"]
    rows, faltando = [], list(nomes)
    if {"estabelecimentos", "municipios"} <= set(tabelas):
        uf = recorte["regiao"]["uf"]
        lista = ", ".join(f"'{n}'" for n in nomes)
        # A tabela Municipios da Receita não tem UF e há nomes repetidos entre estados (ex.: BOA ESPERANCA).
        # Por isso só concorrem códigos que aparecem em estabelecimentos da UF do recorte.
        # A grafia da Receita também varia (ex.: SAO TOME x SAO THOME): casamento aproximado com nota mínima 0,92.
        con.execute(f"""CREATE OR REPLACE TABLE bronze.recorte_municipios AS
            WITH codigos_uf AS (
                SELECT DISTINCT municipio AS codigo
                FROM bronze.estabelecimentos WHERE competencia = '{comp}' AND uf = '{uf}'),
            candidatos AS (
                SELECT m.codigo, m.descricao, upper(strip_accents(trim(m.descricao))) AS nome_norm
                FROM bronze.municipios m JOIN codigos_uf USING (codigo)
                WHERE m.competencia = '{comp}'),
            alvo AS (SELECT unnest([{lista}]) AS nome_recorte),
            pares AS (
                SELECT a.nome_recorte, c.codigo, c.descricao,
                       round(jaro_winkler_similarity(a.nome_recorte, c.nome_norm), 3) AS similaridade
                FROM alvo a CROSS JOIN candidatos c
                QUALIFY row_number() OVER (PARTITION BY a.nome_recorte ORDER BY similaridade DESC) = 1)
            SELECT codigo AS codigo_municipio_receita, descricao AS municipio, nome_recorte, similaridade,
                   CASE WHEN similaridade = 1 THEN 'exato' ELSE 'aproximado' END AS tipo_match
            FROM pares WHERE similaridade >= 0.92
            ORDER BY municipio""")
        rows = con.execute("SELECT * FROM bronze.recorte_municipios").fetchall()
        achados = {r[2] for r in rows}
        faltando = [n for n in nomes if n not in achados]
        with open(RAIZ / "config" / "recorte_resolvido.csv", "w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(["codigo_municipio_receita", "municipio", "nome_recorte", "similaridade", "tipo_match"])
            w.writerows(rows)
        _imprimir(f"RECORTE DO MVP — {len(rows)}/{len(nomes)} municípios de {uf} encontrados",
                  con.sql("SELECT * FROM bronze.recorte_municipios"))
        if faltando:
            log.warning("Municípios do recorte NÃO encontrados (conferir grafia na Receita): %s", faltando)

    # 4) Tamanho da oportunidade dentro do recorte (prévia do que a Silver vai filtrar)
    if {"estabelecimentos", "municipios"} <= set(tabelas):
        uf = recorte["regiao"]["uf"]
        ativa = recorte["estabelecimento"]["situacao_cadastral_ativa"]
        previa = con.sql(f"""
            SELECT r.municipio,
                   count(*)                                                    AS estabelecimentos_total,
                   count(*) FILTER (WHERE e.situacao_cadastral = '{ativa}')    AS ativos
            FROM bronze.estabelecimentos e
            JOIN bronze.recorte_municipios r ON e.municipio = r.codigo_municipio_receita
            WHERE e.competencia = '{comp}' AND e.uf = '{uf}'
            GROUP BY 1 ORDER BY ativos DESC""")
        _imprimir("PRÉVIA — ESTABELECIMENTOS NO RECORTE (dado bruto, antes da Silver)", previa)

    totais = con.execute(f"""SELECT count(*), sum(linhas_parquet), count(*) FILTER (WHERE status <> 'OK'), sum(bytes_origem)
                             FROM bronze.controle_carga WHERE competencia = '{comp}'""").fetchone()
    con.close()
    log.info("Validação: %d arquivos | %s linhas | %d divergência(s)", totais[0], f"{int(totais[1]):,}", totais[2])
    return {"competencia": comp, "arquivos": totais[0], "linhas": int(totais[1]), "divergentes": totais[2], "bytes_origem": int(totais[3]),
            "municipios_recorte": len(rows), "municipios_faltando": faltando}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--competencia")
    executar(ap.parse_args().competencia)
