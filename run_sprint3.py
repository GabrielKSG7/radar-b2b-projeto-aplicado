"""Radar B2B — execução da Sprint 3 (camada Gold: regra de ICP, ranking e entrega para o painel).

    python run_sprint3.py                        # gera a lista do mês (Silver + Gold + testes + exportação)
    python run_sprint3.py --repeticoes 10        # mede a taxa de sucesso e o tempo médio em 10 execuções seguidas
    python run_sprint3.py --somente-gold         # reconstrói só a Gold (rápido, para ajustar pesos do ranking)

Etapas:
  1. dbt build   -> staging + Silver + Gold + todos os testes, na ordem do DAG (é a "geração da lista")
  2. Exportação  -> data/gold/*.parquet (fonte do Power BI) e entregas/oportunidades_<competencia>.csv (Excel)
  3. Amostra     -> entregas/amostra_validacao_icp_<competencia>.csv (conferência manual do ICP na Receita)
  4. Resumo      -> funil do ICP, faixas, top 10, completude dos campos críticos e Objetivo SMART (meta x resultado)

Toda execução é registrada em logs/execucoes.csv (data, modo, status, duração): é daí que sai a taxa de sucesso.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

import duckdb

from radar.comum import DADOS, DB_PATH, DIR_LOGS, RAIZ, carregar_recorte, logger
from run_sprint2 import _show, dbt, resultados_dbt

log = logger("gold")
DIR_GOLD = DADOS / "gold"
DIR_ENTREGAS = RAIZ / "entregas"
HIST_EXEC = DIR_LOGS / "execucoes.csv"
TABELAS_PBI = ["fct_estabelecimentos", "dim_municipio", "dim_cnae", "dim_porte", "dim_calendario", "gold_oportunidades"]
CAMPOS_CRITICOS = {   # Objetivo SMART: meta de 98% de completude
    "cnpj": "CNPJ", "razao_social": "Razão social", "municipio": "Município",
    "cnae_cod": "CNAE principal", "data_inicio_atividade": "Data de início de atividade",
}
META_TEMPO_MIN, META_SUCESSO, META_COMPLETUDE = 15, 95.0, 98.0


def vars_do_yaml(recorte: dict, comp: str) -> dict:
    """config/recorte_mvp.yml -> --vars do dbt (fonte única das regras de recorte, ICP e ranking)."""
    est = recorte["estabelecimento"]
    return {
        "competencia": comp,
        "uf": recorte["regiao"]["uf"],
        "situacao_ativa": est["situacao_cadastral_ativa"],
        "janela_abertura_meses": est["janela_abertura_meses"],
        "natureza_juridica_prefixos": est["natureza_juridica_prefixo"],
        "somente_matriz": est.get("somente_matriz", True),
        "cnae_divisoes_excluidas": list(recorte["cnae"]["divisoes_excluidas"].keys()),
        "ranking": recorte["ranking"],
    }


def registrar_execucao(modo: str, status: str, segundos: float, comp: str) -> None:
    novo = not HIST_EXEC.exists()
    with open(HIST_EXEC, "a", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        if novo:
            w.writerow(["data_hora", "competencia", "modo", "status", "duracao_min"])
        w.writerow([datetime.now().strftime("%Y-%m-%d %H:%M:%S"), comp, modo, status, f"{segundos / 60:.2f}"])


def historico_execucoes() -> tuple[int, int]:
    """(execuções concluídas, total) da geração da lista registradas em logs/execucoes.csv."""
    if not HIST_EXEC.exists():
        return 0, 0
    with open(HIST_EXEC, encoding="utf-8") as f:
        linhas = [r for r in csv.DictReader(f) if r["modo"] == "completo"]
    return sum(r["status"] == "OK" for r in linhas), len(linhas)


def exportar(comp: str) -> dict[str, int]:
    """Gold -> Parquet (Power BI) e lista priorizada -> CSV no padrão do Excel brasileiro (; e vírgula decimal)."""
    DIR_GOLD.mkdir(parents=True, exist_ok=True)
    DIR_ENTREGAS.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(DB_PATH), read_only=True)
    linhas = {}
    for t in TABELAS_PBI:
        destino = (DIR_GOLD / f"{t}.parquet").as_posix()
        con.execute(f"COPY gold.{t} TO '{destino}' (FORMAT parquet, COMPRESSION zstd)").fetchall()
        linhas[t] = con.execute(f"SELECT count(*) FROM gold.{t}").fetchall()[0][0]

    rel = con.sql("""
        SELECT ranking AS "Ranking", faixa_prioridade AS "Faixa", score AS "Score", cnpj_formatado AS "CNPJ",
               razao_social AS "Razão social", nome_fantasia AS "Nome fantasia", municipio AS "Município",
               bairro AS "Bairro", cnae_principal AS "CNAE principal", setor AS "Setor", porte AS "Porte",
               natureza_juridica AS "Natureza jurídica", regime_tributario AS "Regime", capital_social AS "Capital social (R$)",
               data_inicio_atividade AS "Abertura",
               CASE WHEN length(telefone) = 11 THEN '(' || left(telefone, 2) || ') ' || substr(telefone, 3, 5) || '-' || right(telefone, 4)
                    WHEN length(telefone) = 10 THEN '(' || left(telefone, 2) || ') ' || substr(telefone, 3, 4) || '-' || right(telefone, 4)
                    ELSE telefone END AS "Telefone",
               email AS "E-mail",
               CASE WHEN fl_email_contabilidade THEN 'Sim' ELSE 'Não' END AS "E-mail de contabilidade?",
               motivos AS "Por que está nesta posição"
        FROM gold.gold_oportunidades ORDER BY ranking""")
    cols, rows = rel.columns, rel.fetchall()
    _csv_excel(DIR_ENTREGAS / f"oportunidades_{comp}.csv", cols, rows)
    _xlsx(DIR_ENTREGAS / f"oportunidades_{comp}.xlsx", cols, rows, comp)

    # Amostra estratificada para conferir o ICP manualmente na Receita (meta SMART: 90% de acerto).
    # Sorteio por hash do CNPJ: rodar de novo gera a mesma amostra (reprodutível para a banca).
    rel = con.sql("""
        WITH sorteio AS (
            SELECT *, row_number() OVER (PARTITION BY etapa_funil ORDER BY hash(cnpj || 'radar-b2b')) AS ordem
            FROM gold.fct_estabelecimentos
            WHERE etapa_funil <> '1. Aberta antes da janela'    -- quem estava na janela: ICP e excluídos por regra
        )
        SELECT row_number() OVER (ORDER BY fl_icp DESC, etapa_funil, ordem) AS "Nº",
               cnpj_formatado AS "CNPJ", razao_social AS "Razão social", municipio AS "Município",
               CASE WHEN fl_icp THEN 'Oportunidade' ELSE 'Excluída' END AS "Classificação do Radar",
               etapa_funil AS "Motivo", strftime(data_inicio_atividade, '%d/%m/%Y') AS "Abertura",
               natureza_juridica AS "Natureza jurídica", regime_tributario AS "Regime",
               matriz_filial AS "Matriz/Filial", cnae_cod AS "CNAE",
               '' AS "Confere na Receita? (S/N)", '' AS "Observação"
        FROM sorteio
        WHERE ordem <= CASE etapa_funil WHEN '6. Oportunidade (ICP)' THEN 20 WHEN '2. MEI' THEN 4 ELSE 3 END
        ORDER BY 1""")
    _csv_excel(DIR_ENTREGAS / f"amostra_validacao_icp_{comp}.csv", rel.columns, rel.fetchall())
    con.close()
    return linhas


def _csv_excel(caminho: Path, colunas: list[str], linhas: list[tuple]) -> None:
    def fmt(v):
        if v is None:
            return ""
        if isinstance(v, date):
            return v.strftime("%d/%m/%Y")
        if isinstance(v, float) or type(v).__name__ == "Decimal":
            return f"{float(v):.2f}".replace(".", ",")
        return v
    with open(caminho, "w", encoding="utf-8-sig", newline="") as f:     # BOM: o Excel reconhece os acentos
        w = csv.writer(f, delimiter=";")
        w.writerow(colunas)
        w.writerows([[fmt(v) for v in r] for r in linhas])


LARGURAS = {"Ranking": 8, "Faixa": 6, "Score": 7, "CNPJ": 20, "Razão social": 42, "Nome fantasia": 24,
            "Município": 20, "Bairro": 20, "CNAE principal": 45, "Setor": 30, "Porte": 16, "Natureza jurídica": 28,
            "Regime": 16, "Capital social (R$)": 16, "Abertura": 11, "Telefone": 16, "E-mail": 32,
            "E-mail de contabilidade?": 12, "Por que está nesta posição": 120}
CORES_FAIXA = {"A": "C6EFCE", "B": "FFEB9C", "C": "E7E6E6"}


def _xlsx(caminho: Path, colunas: list[str], linhas: list[tuple], comp: str) -> None:
    """Lista priorizada em Excel formatado (para a persona). Pula sem erro se o openpyxl não estiver instalado."""
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Alignment, Font, PatternFill
    except ImportError:
        log.warning("openpyxl não instalado: gerei só o CSV (pip install openpyxl para ter o .xlsx)")
        return
    wb = Workbook()
    ws = wb.active
    ws.title = f"Oportunidades {comp}"
    ws.append(colunas)
    for r in linhas:
        ws.append([float(v) if type(v).__name__ == "Decimal" else v for v in r])
    cab = PatternFill("solid", fgColor="1F4E5A")
    for i, c in enumerate(colunas, start=1):
        cel = ws.cell(row=1, column=i)
        cel.font, cel.fill = Font(bold=True, color="FFFFFF"), cab
        cel.alignment = Alignment(vertical="center", wrap_text=True)
        ws.column_dimensions[cel.column_letter].width = LARGURAS.get(c, 14)
    idx = {c: i + 1 for i, c in enumerate(colunas)}
    for linha in ws.iter_rows(min_row=2):
        faixa = linha[idx["Faixa"] - 1]
        faixa.fill = PatternFill("solid", fgColor=CORES_FAIXA.get(faixa.value, "FFFFFF"))
        faixa.alignment = Alignment(horizontal="center")
        linha[idx["Score"] - 1].number_format = "0.0"
        linha[idx["Capital social (R$)"] - 1].number_format = "#,##0.00"
        linha[idx["Abertura"] - 1].number_format = "dd/mm/yyyy"
    ws.row_dimensions[1].height = 30
    ws.freeze_panes = "E2"            # ranking, faixa, score e CNPJ ficam fixos ao rolar
    ws.auto_filter.ref = ws.dimensions
    wb.save(caminho)


def resumo_gold(comp: str) -> tuple[list[str], dict]:
    con = duckdb.connect(str(DB_PATH), read_only=True)
    out = []
    out += _show(con, "FUNIL DA REGRA DE ICP (ativos do recorte -> oportunidades)", """
        SELECT etapa_funil AS etapa, count(*) AS estabelecimentos,
               round(100.0 * count(*) / sum(count(*)) OVER (), 1) AS pct
        FROM gold.fct_estabelecimentos GROUP BY ALL ORDER BY etapa""")
    out += _show(con, "OPORTUNIDADES POR FAIXA DE PRIORIDADE", """
        SELECT faixa_prioridade AS faixa, count(*) AS oportunidades, min(score) AS score_min, max(score) AS score_max,
               round(avg(score), 1) AS score_medio
        FROM gold.gold_oportunidades GROUP BY ALL ORDER BY faixa""")
    out += _show(con, "OPORTUNIDADES POR MÊS DE ABERTURA", """
        SELECT strftime(data_inicio_atividade, '%Y-%m') AS mes, count(*) AS oportunidades,
               count(*) FILTER (WHERE faixa_prioridade = 'A') AS faixa_a
        FROM gold.gold_oportunidades GROUP BY ALL ORDER BY mes""")
    out += _show(con, "OPORTUNIDADES POR MUNICÍPIO", """
        SELECT m.municipio, count(o.cnpj) AS oportunidades, count(o.cnpj) FILTER (WHERE o.faixa_prioridade = 'A') AS faixa_a
        FROM gold.dim_municipio m LEFT JOIN gold.gold_oportunidades o ON o.municipio = m.municipio
        GROUP BY ALL ORDER BY oportunidades DESC""")
    out += _show(con, "SINAL DE CONTADOR NO CADASTRO (e-mail de escritório contábil)", """
        SELECT faixa_prioridade AS faixa, count(*) AS oportunidades,
               count(*) FILTER (WHERE fl_email_contabilidade) AS com_sinal,
               round(100.0 * count(*) FILTER (WHERE fl_email_contabilidade) / count(*), 1) AS pct_com_sinal
        FROM gold.gold_oportunidades GROUP BY ROLLUP (faixa_prioridade) ORDER BY faixa NULLS LAST""")
    out += _show(con, "ESCRITÓRIOS QUE MAIS APARECEM NAS ABERTURAS DA JANELA (e-mail mascarado)", """
        SELECT left(split_part(email, '@', 1), 3) || '***@' || split_part(email, '@', 2) AS email_escritorio,
               count(*) AS aberturas_no_icp
        FROM gold.gold_oportunidades WHERE fl_email_contabilidade
        GROUP BY email ORDER BY aberturas_no_icp DESC LIMIT 10""")
    out += _show(con, "TOP 10 DO RANKING", """
        SELECT ranking AS pos, score, faixa_prioridade AS f, left(razao_social, 34) AS razao_social, municipio,
               left(motivos, 95) AS motivos
        FROM gold.gold_oportunidades ORDER BY ranking LIMIT 10""")
    sel = "\nUNION ALL ".join(
        f"SELECT '{rot}' AS campo, round(100.0 * count({c}) / count(*), 2) AS completude_pct FROM gold.fct_estabelecimentos"
        for c, rot in CAMPOS_CRITICOS.items())
    out += _show(con, f"COMPLETUDE DOS CAMPOS CRÍTICOS — meta SMART {META_COMPLETUDE:.0f}%", sel)
    ind = dict(zip(
        ["ativos", "oportunidades", "faixa_a", "completude_min", "data_ref", "media_mes", "sinal"],
        con.execute(f"""
            SELECT (SELECT count(*) FROM gold.fct_estabelecimentos),
                   (SELECT count(*) FROM gold.gold_oportunidades),
                   (SELECT count(*) FROM gold.gold_oportunidades WHERE faixa_prioridade = 'A'),
                   (SELECT min(p) FROM ({sel.replace('completude_pct', 'p')})),
                   (SELECT max(data_referencia) FROM gold.fct_estabelecimentos),
                   (SELECT round(avg(n)) FROM (   -- só meses completos: a janela corta o 1º mês e a base corta o último
                        SELECT strftime(data_inicio_atividade, '%Y-%m') AS m, count(*) AS n FROM gold.gold_oportunidades
                        GROUP BY 1 QUALIFY m NOT IN (min(m) OVER (), max(m) OVER ()))),
                   (SELECT count(*) FROM gold.gold_oportunidades WHERE fl_email_contabilidade)
        """).fetchall()[0]))
    con.close()
    return out, ind


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--competencia")
    ap.add_argument("--repeticoes", type=int, default=1, help="execuções seguidas para medir taxa de sucesso e tempo")
    ap.add_argument("--somente-gold", action="store_true", help="reconstrói só a Gold (não conta para a meta SMART)")
    a = ap.parse_args()

    recorte = carregar_recorte()
    con = duckdb.connect(str(DB_PATH), read_only=True)
    comp = a.competencia or con.execute("SELECT max(competencia) FROM bronze.controle_carga WHERE status = 'OK'").fetchall()[0][0]
    con.close()
    vars_ = vars_do_yaml(recorte, comp)
    modo = "somente_gold" if a.somente_gold else "completo"
    selecao = ["--select", "models/gold", "tests/assert_icp_consistente_com_silver.sql",
               "tests/assert_ranking_segue_score.sql"] if a.somente_gold else []
    log.info("Sprint 3 | competência %s | modo %s | %d execução(ões) | ranking: %s",
             comp, modo, a.repeticoes, json.dumps(recorte["ranking"], ensure_ascii=False))

    execucoes: list[tuple[bool, float]] = []
    tempos_build, tempos_export = [], []
    cont, linhas = None, {}
    for i in range(1, a.repeticoes + 1):
        t0 = time.perf_counter()
        rc, t_build = dbt(["build", *selecao], vars_)
        cont = resultados_dbt()
        ok = rc == 0
        if ok:
            t = time.perf_counter()
            linhas = exportar(comp)
            tempos_export.append(time.perf_counter() - t)
        dur = time.perf_counter() - t0
        tempos_build.append(t_build)
        execucoes.append((ok, dur))
        registrar_execucao(modo, "OK" if ok else "FALHA", dur, comp)
        log.info("Execução %d/%d: %s em %.1f min", i, a.repeticoes, "OK" if ok else "FALHA", dur / 60)

    ultima_ok = execucoes[-1][0]
    linhas_gold, ind = resumo_gold(comp) if ultima_ok else ([], {})
    ok_n = sum(ok for ok, _ in execucoes)
    dur_ok = [d for ok, d in execucoes if ok] or [0.0]
    hist_ok, hist_tot = historico_execucoes()
    taxa_hist = 100 * hist_ok / hist_tot if hist_tot else 0.0
    testes_ok = cont[("test", "pass")]
    testes_tot = sum(v for (tipo, _), v in cont.items() if tipo == "test")
    falhas = cont[("test", "fail")] + cont[("test", "error")]
    tempo_lista = max(dur_ok) / 60

    cab = [
        "", "=" * 76,
        f"  RADAR B2B — RESUMO DA SPRINT 3 (Gold) — competência {comp}",
        "=" * 76,
        f"  {'Modo':<44} {modo:>28}",
        f"  {'Execuções nesta rodada (OK/total)':<44} {f'{ok_n}/{len(execucoes)}':>28}",
        f"  {'dbt build — tempo médio':<44} {sum(tempos_build) / len(tempos_build) / 60:24.1f} min",
        f"  {'Exportação Parquet + CSV — tempo médio':<44} {(sum(tempos_export) / len(tempos_export) if tempos_export else 0) / 60:24.1f} min",
        f"  {'Geração da lista — pior tempo':<44} {tempo_lista:24.1f} min",
        f"  {'Modelos criados':<44} {cont[('model', 'success')]:>28}",
        f"  {'Testes dbt aprovados':<44} {f'{testes_ok}/{testes_tot}':>28}",
        f"  {'Testes com falha':<44} {falhas:>28}",
    ]
    if ind:
        cab += [
            f"  {'Estabelecimentos ativos (fato)':<44} {ind['ativos']:>28,}",
            f"  {'Oportunidades no ICP (lista)':<44} {ind['oportunidades']:>28,}",
            f"  {'  dessas, faixa A':<44} {ind['faixa_a']:>28,}",
            f"  {'  média por mês completo de abertura':<44} {int(ind['media_mes'] or 0):>28,}",
            f"  {'  com e-mail de escritório contábil':<44} {ind['sinal']:>28,}",
            f"  {'Data de referência da base':<44} {str(ind['data_ref']):>28}",
        ]
    cab += ["-" * 76, "  OBJETIVO SMART — META x RESULTADO", "-" * 76]
    if not a.somente_gold:
        cab += [
            f"  {'Geração da lista < 15 min':<44} {f'{tempo_lista:.1f} min':>16}  {'ATINGIDA' if tempo_lista < META_TEMPO_MIN else 'NÃO ATINGIDA':>10}",
            f"  {'Execuções com sucesso >= 95% (histórico)':<44} {f'{taxa_hist:.1f}% ({hist_ok}/{hist_tot})':>16}  {'ATINGIDA' if taxa_hist >= META_SUCESSO else 'NÃO ATINGIDA':>10}",
        ]
    if ind:
        comp_min = ind["completude_min"]
        cab += [f"  {'Completude dos campos críticos >= 98%':<44} {f'{comp_min:.2f}% (mín.)':>16}  {'ATINGIDA' if comp_min >= META_COMPLETUDE else 'NÃO ATINGIDA':>10}"]
    cab += [f"  {'Acerto do ICP >= 90% (amostra manual)':<44} {'conferir':>16}  {'entregas/amostra_validacao_icp_' + comp + '.csv'}"]
    cab += ["=" * 76, ""]
    if linhas:
        cab += ["  ARQUIVOS GERADOS", *[f"    data/gold/{t}.parquet  ({n:,} linhas)" for t, n in linhas.items()],
                f"    entregas/oportunidades_{comp}.csv (+ .xlsx)", f"    entregas/amostra_validacao_icp_{comp}.csv", ""]

    texto = "\n".join(cab + linhas_gold)
    print("\n".join(cab))
    destino = DIR_LOGS / f"resumo_sprint3_{comp}_{time.strftime('%Y%m%d_%H%M')}.txt"
    destino.write_text(texto, encoding="utf-8")
    log.info("Resumo gravado em %s", destino.relative_to(RAIZ))
    sys.exit(0 if ultima_ok else 1)


if __name__ == "__main__":
    main()
