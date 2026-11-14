"""Radar B2B — execução da Sprint 2 (camada Silver).

    python run_sprint2.py                        # competência mais recente carregada na Bronze
    python run_sprint2.py --competencia 2026-10
    python run_sprint2.py --sem-docs             # pula o dbt docs generate

Etapas:
  1. Perfil de qualidade da Bronze no recorte (o "antes": sujeiras que a Silver precisa tratar)
  2. dbt build  -> seeds de domínio + modelos stg_/slv_ + todos os testes, na ordem do DAG
  3. dbt docs generate -> documentação e linhagem do modelo de dados
  4. Resumo: funil Bronze -> Silver, completude, decodificação dos domínios e resultado dos testes
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

import duckdb

from radar.comum import DB_PATH, DIR_LOGS, RAIZ, carregar_recorte, logger

log = logger("silver")
PROJ_DBT = RAIZ / "radar_dbt"
CAMPOS_TEXTO = ["nome_fantasia", "logradouro", "numero", "complemento", "bairro", "correio_eletronico"]
CAMPOS_DATA = ["data_situacao_cadastral", "data_inicio_atividade"]


def _show(con, titulo: str, sql: str) -> list[str]:
    """Imprime a consulta como tabela e devolve as linhas em texto para o resumo."""
    print(f"\n=== {titulo} ===")
    rel = con.sql(sql)
    rel.show(max_width=200)
    cols, rows = rel.columns, rel.fetchall()
    larg = [max(len(str(c)), *(len(f"{r[i]:,}" if isinstance(r[i], int) else str(r[i])) for r in rows)) for i, c in enumerate(cols)]
    fmt = lambda v: f"{v:,}" if isinstance(v, int) else str(v)
    out = [f"  {titulo}", "  " + "  ".join(str(c).ljust(larg[i]) for i, c in enumerate(cols))]
    out += ["  " + "  ".join(fmt(v).rjust(larg[i]) if isinstance(v, (int, float)) else fmt(v).ljust(larg[i])
                             for i, v in enumerate(r)) for r in rows]
    return out + [""]


def perfil_bronze(comp: str, uf: str) -> tuple[list[str], dict]:
    """Mede, no dado CRU do recorte, os problemas que a Silver trata. É a evidência do 'antes'."""
    con = duckdb.connect(str(DB_PATH), read_only=True)
    sujo = " OR ".join(f"regexp_matches({c}, '[\\x00-\\x1F\\x7F-\\x9F]|\\s{{2,}}|^\\s|\\s$')" for c in CAMPOS_TEXTO)
    datas_inv = " OR ".join(f"({c} IS NOT NULL AND trim({c}) <> '' AND try_strptime({c}, '%Y%m%d') IS NULL)" for c in CAMPOS_DATA)
    con.execute(f"""CREATE TEMP TABLE bruto AS
        SELECT e.* FROM bronze.estabelecimentos e
        JOIN bronze.recorte_municipios r ON e.municipio = r.codigo_municipio_receita
        WHERE e.competencia = '{comp}' AND e.uf = '{uf}'""")
    linhas = _show(con, f"PERFIL DA BRONZE NO RECORTE (antes da Silver) — competência {comp}", f"""
        SELECT count(*)                                                        AS registros_brutos,
               count(*) - count(DISTINCT cnpj_basico || cnpj_ordem || cnpj_dv) AS cnpj_repetidos,
               count(*) FILTER (WHERE {sujo})                                  AS texto_com_sujeira,
               count(*) FILTER (WHERE {datas_inv})                             AS datas_invalidas,
               count(*) FILTER (WHERE correio_eletronico <> lower(correio_eletronico)) AS email_maiusculo,
               count(DISTINCT situacao_cadastral)                              AS codigos_situacao
        FROM bruto""")
    r = con.execute("SELECT count(*), count(*) - count(DISTINCT cnpj_basico || cnpj_ordem || cnpj_dv) FROM bruto").fetchone()
    brasil = con.execute(f"SELECT sum(linhas_parquet) FROM bronze.controle_carga WHERE competencia = '{comp}' AND tabela = 'estabelecimentos'").fetchone()[0]
    mg = con.execute(f"SELECT count(*) FROM bronze.estabelecimentos WHERE competencia = '{comp}' AND uf = '{uf}'").fetchone()[0]
    con.close()
    return linhas, {"brasil": int(brasil or 0), "uf": mg, "recorte_bruto": r[0], "repetidos": r[1]}


def dbt(args: list[str], vars_: dict) -> tuple[int, float]:
    exe = shutil.which("dbt") or str(Path(sys.executable).parent / "dbt")
    env = {**os.environ, "RADAR_DB_PATH": str(DB_PATH)}
    t = time.perf_counter()
    r = subprocess.run([exe, *args, "--profiles-dir", ".", "--vars", json.dumps(vars_)], cwd=PROJ_DBT, env=env)
    return r.returncode, time.perf_counter() - t


def resultados_dbt() -> Counter:
    arq = PROJ_DBT / "target" / "run_results.json"
    cont: Counter = Counter()
    for r in json.loads(arq.read_text(encoding="utf-8"))["results"]:
        tipo = r["unique_id"].split(".")[0]                  # seed | model | test
        cont[(tipo, r["status"])] += 1
    return cont


def resumo_silver(comp: str, funil: dict) -> list[str]:
    con = duckdb.connect(str(DB_PATH), read_only=True)
    out = []
    out += _show(con, "FUNIL BRONZE -> SILVER", f"""
        SELECT * FROM (VALUES
            (1, 'Estabelecimentos no Brasil (Bronze)',              {funil['brasil']}),
            (2, 'Na UF do recorte',                                  {funil['uf']}),
            (3, 'Nos 16 municípios do recorte (bruto)',              {funil['recorte_bruto']}),
            (4, 'Após deduplicação (1 por CNPJ)',                   (SELECT count(*) FROM silver.slv_estabelecimentos_recorte)),
            (5, 'Ativos (silver.slv_estabelecimentos_ativos)',      (SELECT count(*) FROM silver.slv_estabelecimentos_ativos))
        ) t(etapa, descricao, registros) ORDER BY etapa""")
    out += _show(con, "SITUAÇÃO CADASTRAL DECODIFICADA (recorte)", """
        SELECT situacao_cadastral_cod AS codigo, situacao_cadastral AS descricao, count(*) AS estabelecimentos,
               round(100.0 * count(*) / sum(count(*)) OVER (), 1) AS pct
        FROM silver.slv_estabelecimentos_recorte GROUP BY ALL ORDER BY estabelecimentos DESC""")
    out += _show(con, "AMOSTRA DA SILVER — CÓDIGOS DA RECEITA x DOMÍNIOS DECODIFICADOS", """
        SELECT cnpj_formatado, situacao_cadastral_cod AS sit, situacao_cadastral, cnae_principal_cod AS cnae,
               left(cnae_principal, 40) AS cnae_principal, cnae_secao AS sec, natureza_juridica_cod AS nat,
               left(natureza_juridica, 30) AS natureza_juridica, porte_cod AS porte, porte AS porte_desc,
               municipio, data_inicio_atividade AS abertura
        FROM silver.slv_estabelecimentos_ativos
        ORDER BY data_inicio_atividade DESC NULLS LAST, cnpj LIMIT 8""")
    campos = ["razao_social", "cnae_principal", "cnae_secao", "natureza_juridica", "porte", "data_inicio_atividade",
              "municipio", "telefone_1", "email"]
    sel = ",\n".join(f"SELECT '{c}' AS campo, round(100.0 * count({c}) / count(*), 2) AS completude_pct FROM silver.slv_estabelecimentos_ativos"
                     for c in campos).replace(",\nSELECT", "\nUNION ALL SELECT")
    out += _show(con, "COMPLETUDE DOS CAMPOS CRÍTICOS (ativos)", sel)
    out += _show(con, "LIMPEZA — TEXTO COM SUJEIRA DEPOIS DA SILVER (esperado: 0)", """
        SELECT count(*) FILTER (WHERE regexp_matches(concat_ws('|', nome_fantasia, logradouro, numero, complemento, bairro, email),
                                                     '[\\x00-\\x1F\\x7F-\\x9F]|\\s{2,}|^\\s|\\s$')) AS texto_com_sujeira,
               count(*) FILTER (WHERE email <> lower(email))                                            AS email_maiusculo,
               count(*) FILTER (WHERE ocorrencias_na_origem > 1)                                        AS cnpj_deduplicados
        FROM silver.slv_estabelecimentos_recorte""")
    out += _show(con, "PRÉVIA PARA A GOLD — ATIVOS POR SEÇÃO CNAE (top 8)", """
        SELECT cnae_secao AS secao, cnae_secao_descricao AS setor, count(*) AS ativos,
               count(*) FILTER (WHERE fl_aberto_na_janela) AS abertos_na_janela
        FROM silver.slv_estabelecimentos_ativos GROUP BY ALL ORDER BY ativos DESC LIMIT 8""")
    out += _show(con, "PRÉVIA PARA A GOLD — FLAGS DA REGRA DE ICP (ativos)", """
        SELECT count(*) AS ativos,
               count(*) FILTER (WHERE fl_aberto_na_janela) AS abertos_na_janela,
               count(*) FILTER (WHERE fl_mei) AS mei,
               count(*) FILTER (WHERE NOT fl_natureza_empresarial) AS natureza_nao_empresarial,
               count(*) FILTER (WHERE fl_cnae_excluido) AS cnae_excluido,
               count(*) FILTER (WHERE fl_aberto_na_janela AND NOT fl_mei AND fl_natureza_empresarial AND NOT fl_cnae_excluido)
                   AS candidatos_icp,
               min(data_referencia) AS data_referencia
        FROM silver.slv_estabelecimentos_ativos""")
    con.close()
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--competencia")
    ap.add_argument("--sem-docs", action="store_true")
    a = ap.parse_args()

    recorte = carregar_recorte()
    con = duckdb.connect(str(DB_PATH), read_only=True)
    comp = a.competencia or con.execute("SELECT max(competencia) FROM bronze.controle_carga WHERE status = 'OK'").fetchone()[0]
    con.close()
    uf = recorte["regiao"]["uf"]
    vars_ = {   # config/recorte_mvp.yml -> dbt (fonte única das regras)
        "competencia": comp,
        "uf": uf,
        "situacao_ativa": recorte["estabelecimento"]["situacao_cadastral_ativa"],
        "janela_abertura_meses": recorte["estabelecimento"]["janela_abertura_meses"],
        "natureza_juridica_prefixos": recorte["estabelecimento"]["natureza_juridica_prefixo"],
        "cnae_divisoes_excluidas": list(recorte["cnae"]["divisoes_excluidas"].keys()),
    }
    log.info("Sprint 2 | competência %s | regras: %s", comp, vars_)

    tempos: dict[str, float] = {}
    t0 = time.perf_counter()
    t = time.perf_counter()
    perfil, funil = perfil_bronze(comp, uf)
    tempos["1. Perfil da Bronze (antes)"] = time.perf_counter() - t

    rc, tempos["2. dbt build (seeds+modelos+testes)"] = dbt(["build"], vars_)
    cont = resultados_dbt()
    if rc != 0:
        log.error("dbt build terminou com falha — veja o log acima. Resumo parcial: %s", dict(cont))

    docs = "não gerada"
    if not a.sem_docs:
        rc_docs, tempos["3. dbt docs generate"] = dbt(["docs", "generate"], vars_)
        docs = "gerada (dbt docs serve)" if rc_docs == 0 else "FALHOU"

    linhas_silver = resumo_silver(comp, funil) if rc == 0 else []
    total = time.perf_counter() - t0
    testes_ok = cont[("test", "pass")]
    testes_tot = sum(v for (tipo, _), v in cont.items() if tipo == "test")
    removidos = funil["repetidos"]
    falhas, avisos = cont[("test", "fail")] + cont[("test", "error")], cont[("test", "warn")]
    cab = [
        "", "=" * 72,
        f"  RADAR B2B — RESUMO DA SPRINT 2 (Silver) — competência {comp}",
        "=" * 72,
        *[f"  {k:<40} {v / 60:8.1f} min" for k, v in tempos.items()],
        "-" * 72,
        f"  {'Tempo total':<40} {total / 60:8.1f} min",
        f"  {'Seeds de domínio carregados':<40} {cont[('seed', 'success')]:>12}",
        f"  {'Modelos criados (stg_ + slv_)':<40} {cont[('model', 'success')]:>12}",
        f"  {'Testes dbt aprovados':<40} {f'{testes_ok}/{testes_tot}':>12}",
        f"  {'Testes com falha / aviso':<40} {f'{falhas} / {avisos}':>12}",
        f"  {'CNPJ repetidos removidos':<40} {removidos:>12,}",
        f"  {'Documentação do modelo':<40} {docs:>24}",
        "=" * 72, "",
    ]
    texto = "\n".join(cab + perfil + linhas_silver)
    print("\n".join(cab))
    carimbo = time.strftime("%Y%m%d_%H%M")
    destino = DIR_LOGS / f"resumo_sprint2_{comp}_{carimbo}.txt"
    destino.write_text(texto, encoding="utf-8")
    log.info("Resumo gravado em %s", destino.relative_to(RAIZ))
    sys.exit(rc)


if __name__ == "__main__":
    main()
