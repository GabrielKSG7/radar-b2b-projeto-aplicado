"""Radar B2B — compara o ranking antes e depois de um ajuste de regra (evidência da revisão do cartão 5).

    python comparar_ranking.py --antes     # 1) fotografa o ranking ATUAL (regra antiga)
    python run_sprint3.py                  # 2) reconstrói a Gold com a regra nova do config/recorte_mvp.yml
    python comparar_ranking.py             # 3) compara a foto com o ranking novo
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

import duckdb

from radar.comum import DADOS, DB_PATH

FOTO = (DADOS / "gold" / "_ranking_antes.parquet").as_posix()
ESTRUTURA = "(cnae_cod LIKE '6462%' OR cnae_cod LIKE '6463%' OR razao_social LIKE '% SPE%' OR razao_social LIKE '%PROPOSITO ESPECIFICO%')"
SETOR = "(cnae_cod LIKE '4731%' OR cnae_cod LIKE '1081%' OR cnae_cod LIKE '86%' OR cnae_cod LIKE '4930%')"


def main() -> None:
    con = duckdb.connect(str(DB_PATH), read_only=True)
    if "--antes" in sys.argv:
        con.execute(f"""COPY (SELECT cnpj, score, faixa_prioridade, ranking FROM gold.fct_estabelecimentos WHERE fl_icp)
                        TO '{FOTO}' (FORMAT parquet)""").fetchall()
        print(f"Ranking atual fotografado em {FOTO}. Agora rode: python run_sprint3.py")
        return
    d = f"""(SELECT f.*, a.faixa_prioridade AS faixa_antes, a.ranking AS ranking_antes, a.score AS score_antes
             FROM gold.fct_estabelecimentos f JOIN read_parquet('{FOTO}') a USING (cnpj) WHERE f.fl_icp)"""
    print("\n=== REVISÃO DO RANKING (cartão 5) — ANTES x DEPOIS, mesma base de outubro ===")
    con.sql(f"""
        SELECT 'antes' AS regra, count(*) FILTER (WHERE faixa_antes = 'A') AS faixa_a,
               count(*) FILTER (WHERE faixa_antes = 'A' AND {ESTRUTURA}) AS holding_spe_na_a,
               count(*) FILTER (WHERE ranking_antes <= 10 AND {ESTRUTURA}) AS holding_spe_top10,
               count(*) FILTER (WHERE ranking_antes <= 50 AND {ESTRUTURA}) AS holding_spe_top50,
               count(*) FILTER (WHERE faixa_antes = 'A' AND {SETOR}) AS setor_complexo_na_a
        FROM {d}
        UNION ALL
        SELECT 'depois', count(*) FILTER (WHERE faixa_prioridade = 'A'),
               count(*) FILTER (WHERE faixa_prioridade = 'A' AND {ESTRUTURA}),
               count(*) FILTER (WHERE ranking <= 10 AND {ESTRUTURA}),
               count(*) FILTER (WHERE ranking <= 50 AND {ESTRUTURA}),
               count(*) FILTER (WHERE faixa_prioridade = 'A' AND {SETOR})
        FROM {d}""").show()
    print("=== MIGRAÇÃO ENTRE FAIXAS ===")
    con.sql(f"SELECT faixa_antes, faixa_prioridade AS faixa_depois, count(*) AS empresas FROM {d} GROUP BY ALL ORDER BY 1, 2").show()
    print("=== TOP 10: ANTES -> DEPOIS ===")
    con.sql(f"""SELECT ranking_antes AS pos_antes, ranking AS pos_depois, score_antes, score AS score_depois,
                       faixa_prioridade AS faixa, left(razao_social, 42) AS razao_social
                FROM {d} WHERE ranking_antes <= 10 OR ranking <= 10 ORDER BY least(ranking_antes, ranking), ranking""").show(max_rows=30)
    con.close()


if __name__ == "__main__":
    main()
