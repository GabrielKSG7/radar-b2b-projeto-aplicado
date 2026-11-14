"""Radar B2B — confere a amostra do ICP contra uma consulta independente do CNPJ (meta SMART: 90% de acerto).

    python validar_amostra_icp.py

Para cada CNPJ de entregas/amostra_validacao_icp_<competencia>.csv:
  1. consulta o cadastro na BrasilAPI (https://brasilapi.com.br/api/cnpj/v1/<cnpj>); se falhar, tenta minhareceita.org;
  2. reaplica a MESMA regra de ICP do config/recorte_mvp.yml sobre os dados consultados;
  3. compara com a classificação do Radar (Oportunidade x Excluída).

A divergência causada por mudança DEPOIS da data de referência da base (ex.: empresa baixada em novembro)
não é erro da regra: ela é marcada como "atualização posterior" e mostrada à parte.
Saída: entregas/amostra_validacao_icp_<competencia>_conferida.csv (+ .xlsx se o openpyxl estiver instalado).
"""
from __future__ import annotations

import csv
import json
import sys
import time
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

import duckdb
import httpx

from radar.comum import DB_PATH, RAIZ, carregar_recorte, logger

log = logger("validacao")
FONTES = ["https://brasilapi.com.br/api/cnpj/v1/{}", "https://minhareceita.org/{}"]
META = 90.0


CACHE = RAIZ / "entregas" / "_cache_consulta_cnpj.json"


def consultar(cliente: httpx.Client, cnpj: str) -> tuple[dict | None, str]:
    """Tenta cada fonte no máximo 2 vezes, com tempo limite curto, para nunca travar a execução."""
    for url in FONTES:
        for tentativa in range(2):
            try:
                r = cliente.get(url.format(cnpj))
                if r.status_code == 200:
                    return r.json(), url.split("/")[2]
                if r.status_code == 404:
                    break                                   # esta fonte não tem o CNPJ: tenta a próxima
                time.sleep(2 * (tentativa + 1))             # 429/5xx: espera e tenta de novo
            except httpx.HTTPError:
                time.sleep(2 * (tentativa + 1))
    return None, "sem resposta"


def _data(v) -> date | None:
    try:
        return date.fromisoformat(str(v)[:10]) if v else None
    except ValueError:
        return None


def classificar(d: dict, regras: dict, data_ref: date) -> tuple[str, str]:
    """Mesma ordem do funil da Gold: o primeiro critério que reprova explica a exclusão."""
    est = regras["estabelecimento"]
    m = data_ref.month - est["janela_abertura_meses"]               # mesma conta do dbt: data_referencia - N meses
    ano, mes = data_ref.year + (m - 1) // 12, (m - 1) % 12 + 1
    inicio_janela = date(ano, mes, min(data_ref.day, 28))
    abertura = _data(d.get("data_inicio_atividade"))
    natureza = str(d.get("codigo_natureza_juridica") or "")
    cnae = str(d.get("cnae_fiscal") or "").zfill(7)
    if str(d.get("descricao_situacao_cadastral", "")).upper() != "ATIVA":
        return "Excluída", f"situação {d.get('descricao_situacao_cadastral')}"
    if not abertura or abertura <= inicio_janela:
        return "Excluída", "1. Aberta antes da janela"
    if d.get("opcao_pelo_mei") is True:
        return "Excluída", "2. MEI"
    if not any(natureza.startswith(p) for p in est["natureza_juridica_prefixo"]):
        return "Excluída", "3. Natureza não empresarial"
    if cnae[:2] in regras["cnae"]["divisoes_excluidas"]:
        return "Excluída", "4. CNAE fora do público"
    if est.get("somente_matriz", True) and int(d.get("identificador_matriz_filial") or 0) != 1:
        return "Excluída", "5. Filial (contabilidade na matriz)"
    return "Oportunidade", "6. Oportunidade (ICP)"


def mudou_depois(d: dict, data_ref: date) -> bool:
    """A consulta é de hoje; a base é de data_ref. Mudança registrada depois disso explica a divergência."""
    for campo in ("data_situacao_cadastral", "data_opcao_pelo_mei", "data_exclusao_do_mei"):
        dt = _data(d.get(campo))
        if dt and dt > data_ref:
            return True
    return False


def main() -> None:
    regras = carregar_recorte()
    con = duckdb.connect(str(DB_PATH), read_only=True)
    comp, data_ref = con.execute(
        "SELECT max(competencia), max(data_referencia) FROM gold.fct_estabelecimentos").fetchall()[0]
    con.close()
    origem = RAIZ / "entregas" / f"amostra_validacao_icp_{comp}.csv"
    with open(origem, encoding="utf-8-sig", newline="") as f:
        amostra = list(csv.DictReader(f, delimiter=";"))
    log.info("Conferindo %d CNPJs da amostra (base de %s) contra consulta independente", len(amostra), data_ref)

    cache = json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else {}
    saida = []
    with httpx.Client(timeout=httpx.Timeout(8.0, connect=5.0), headers={"User-Agent": "radar-b2b-validacao/1.0"}, follow_redirects=True) as cliente:
        for i, lin in enumerate(amostra, 1):
            cnpj = "".join(ch for ch in lin["CNPJ"] if ch.isalnum())
            if cnpj in cache:                                # já consultado numa execução anterior
                dados, fonte = cache[cnpj]["dados"], cache[cnpj]["fonte"]
            else:
                dados, fonte = consultar(cliente, cnpj)
                if dados is not None:
                    cache[cnpj] = {"dados": dados, "fonte": fonte}
                    CACHE.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
            if dados is None:
                classe, motivo, status = "-", "-", "SEM CONSULTA"
            else:
                classe, motivo = classificar(dados, regras, data_ref)
                if classe == lin["Classificação do Radar"]:
                    status = "S"
                elif mudou_depois(dados, data_ref):
                    status = "ATUALIZAÇÃO POSTERIOR"
                else:
                    status = "N"
            saida.append({**{k: lin[k] for k in ("Nº", "CNPJ", "Razão social", "Município", "Classificação do Radar", "Motivo")},
                          "Classificação pela consulta": classe, "Motivo pela consulta": motivo,
                          "Confere? (S/N)": status, "Fonte da consulta": fonte})
            log.info("%2d/%d %s  Radar=%-12s Consulta=%-12s %s", i, len(amostra), lin["CNPJ"],
                     lin["Classificação do Radar"], classe, status)
            if fonte != "cache":
                time.sleep(0.6)                              # gentileza com a API pública

    destino = RAIZ / "entregas" / f"amostra_validacao_icp_{comp}_conferida.csv"
    with open(destino, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(saida[0]), delimiter=";")
        w.writeheader()
        w.writerows(saida)
    _xlsx(destino.with_suffix(".xlsx"), saida)

    consultados = [s for s in saida if s["Confere? (S/N)"] != "SEM CONSULTA"]
    ok = sum(s["Confere? (S/N)"] == "S" for s in consultados)
    atualiz = sum(s["Confere? (S/N)"] == "ATUALIZAÇÃO POSTERIOR" for s in consultados)
    n = len(consultados)
    acerto = 100 * ok / n if n else 0
    acerto_regra = 100 * ok / (n - atualiz) if n - atualiz else 0
    print("\n" + "=" * 72)
    print(f"  CONFERÊNCIA DA AMOSTRA DO ICP — competência {comp} (base de {data_ref})")
    print("=" * 72)
    print(f"  CNPJs na amostra                              {len(saida):>10}")
    print(f"  Consultados com sucesso                       {n:>10}")
    print(f"  Classificação confere (S)                     {ok:>10}")
    print(f"  Divergem por atualização após {data_ref}      {atualiz:>10}")
    print(f"  Divergem sem explicação (N)                   {n - ok - atualiz:>10}")
    print("-" * 72)
    print(f"  Acerto sobre a amostra consultada             {acerto:9.1f}%   meta {META:.0f}%  "
          f"{'ATINGIDA' if acerto >= META else 'NÃO ATINGIDA'}")
    print(f"  Acerto da regra (sem atualizações posteriores) {acerto_regra:8.1f}%")
    print("=" * 72)
    print(f"  Detalhe: {destino.relative_to(RAIZ)}\n")


def _xlsx(caminho: Path, linhas: list[dict]) -> None:
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill
    except ImportError:
        return
    wb = Workbook()
    ws = wb.active
    ws.title = "Conferência ICP"
    cols = list(linhas[0])
    ws.append(cols)
    for lin in linhas:
        ws.append([lin[c] for c in cols])
    for c in ws[1]:
        c.font, c.fill = Font(bold=True, color="FFFFFF"), PatternFill("solid", fgColor="1F4E5A")
    cores = {"S": "C6EFCE", "N": "FFC7CE", "ATUALIZAÇÃO POSTERIOR": "FFEB9C"}
    col_status = cols.index("Confere? (S/N)") + 1
    for row in ws.iter_rows(min_row=2):
        cel = row[col_status - 1]
        if cel.value in cores:
            cel.fill = PatternFill("solid", fgColor=cores[cel.value])
    for letra, larg in zip("ABCDEFGHIJ", [5, 20, 42, 20, 14, 30, 14, 30, 22, 18]):
        ws.column_dimensions[letra].width = larg
    ws.freeze_panes = "C2"
    try:
        wb.save(caminho)
    except PermissionError:
        log.warning("Feche %s no Excel para regravar.", caminho.name)


if __name__ == "__main__":
    main()
