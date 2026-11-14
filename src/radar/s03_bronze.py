"""Etapa 3 — Conversão CSV -> Parquet particionado (camada Bronze).

Regras da Bronze: dado CRU, sem filtro e sem tipagem (tudo VARCHAR), só com colunas técnicas
de linhagem (_arquivo_origem, _carregado_em). A tipagem fica para a Silver (Sprint 2).
Atenção: desde jul/2026 o CNPJ pode ser alfanumérico — por isso cnpj_basico nunca vira número.

Saída: data/bronze/<tabela>/competencia=AAAA-MM/<NomeDoZip>.parquet  (particionamento Hive)
Controle: data/bronze/_controle_carga.csv  (linhas no arquivo de origem x linhas no Parquet)
"""
from __future__ import annotations

import argparse
import csv
import re
import time
from datetime import datetime
from pathlib import Path

import duckdb

from radar.comum import (CONTROLE_CSV, DADOS, DIR_BRONZE, DIR_RAW, LAYOUTS, fmt_bytes, ja_carregado, ler_controle,
                         logger, tabela_do_zip)

log = logger("bronze")
CAMPOS_CONTROLE = ["competencia", "tabela", "arquivo_zip", "arquivo_origem", "bytes_origem", "linhas_fisicas",
                   "linhas_origem", "quebras_em_campo", "linhas_parquet", "status", "encoding_lido", "leitura",
                   "segundos", "carregado_em"]
C1 = re.compile(r"[\x80-\x9f]")
# Tentativas de leitura, da mais rápida para a mais tolerante.
# null_padding + leitor paralelo não aceita quebra de linha dentro de campo entre aspas (existe no Estabelecimentos0).
TENTATIVAS = [
    {"null_padding": "false", "parallel": "true"},
    {"null_padding": "true", "parallel": "false"},
]


def contar_registros(arq: Path) -> tuple[int, int]:
    """Contagem independente do DuckDB, feita em Python sobre os bytes do arquivo.
    Retorna (linhas físicas, registros). Um registro só termina numa quebra de linha FORA das aspas;
    a diferença entre os dois números são campos com quebra de linha dentro (ex.: endereço digitado com Enter)."""
    fisicas = registros = 0
    dentro_aspas = False
    resto = b""
    with open(arq, "rb") as f:
        while bloco := f.read(16 * 1024 * 1024):
            partes = (resto + bloco).split(b"\n")
            resto = partes.pop()
            fisicas += len(partes)
            for parte in partes:
                if parte.count(b'"') & 1:
                    dentro_aspas = not dentro_aspas
                if not dentro_aspas:
                    registros += 1
    if resto.strip():
        fisicas += 1
        if resto.count(b'"') & 1:
            dentro_aspas = not dentro_aspas
        if not dentro_aspas:
            registros += 1
    return fisicas, registros


def _transcodificar(arq: Path) -> Path:
    """Plano B: alguns arquivos grandes trazem bytes de controle (0x80-0x9F) que o leitor latin-1
    do DuckDB recusa. Converte para UTF-8 trocando esses bytes por espaço."""
    tmp = DADOS / "tmp" / (arq.name + ".utf8.csv")
    tmp.parent.mkdir(parents=True, exist_ok=True)
    with open(arq, encoding="latin-1", newline="") as src, open(tmp, "w", encoding="utf-8", newline="") as dst:
        while bloco := src.read(8 * 1024 * 1024):
            dst.write(C1.sub(" ", bloco))
    return tmp


def _copy_sql(origem: Path, destino: Path, tabela: str, encoding: str, arquivo_origem: str, opcoes: dict) -> str:
    colunas = ", ".join(f"'{c}': 'VARCHAR'" for c in LAYOUTS[tabela])
    return f"""
        COPY (
            SELECT *, '{arquivo_origem}' AS _arquivo_origem, now() AS _carregado_em
            FROM read_csv('{origem.as_posix()}', delim=';', quote='"', escape='"', header=false,
                          encoding='{encoding}', columns={{{colunas}}}, null_padding={opcoes["null_padding"]},
                          strict_mode=false, parallel={opcoes["parallel"]})
        ) TO '{destino.as_posix()}' (FORMAT parquet, COMPRESSION zstd)
    """


def _ler(con, origem: Path, destino: Path, tabela: str, encoding: str, nome: str) -> str:
    """Tenta as estratégias de leitura em ordem. Erro de encoding sobe na hora (tratado por quem chama)."""
    ultimo_erro = None
    for opcoes in TENTATIVAS:
        try:
            con.execute(_copy_sql(origem, destino, tabela, encoding, nome, opcoes))
            return "paralela" if opcoes["parallel"] == "true" else "sequencial"
        except duckdb.Error as e:
            if "encoded" in str(e):
                raise
            ultimo_erro = e
            log.warning("%s: leitura %s falhou (%s). Tentando modo mais tolerante...",
                        nome, opcoes, str(e).splitlines()[0][:80])
    raise ultimo_erro


def converter_arquivo(con: duckdb.DuckDBPyConnection, arq: Path, comp: str) -> dict:
    zip_stem = arq.parent.name
    tabela = tabela_do_zip(zip_stem)
    destino = DIR_BRONZE / tabela / f"competencia={comp}" / f"{zip_stem}.parquet"
    destino.parent.mkdir(parents=True, exist_ok=True)
    t = time.perf_counter()

    encoding, tmp = "latin-1", None
    try:
        leitura = _ler(con, arq, destino, tabela, "latin-1", arq.name)
    except duckdb.Error as e:
        log.warning("%s: leitura latin-1 falhou (%s). Aplicando transcodificação para UTF-8...",
                    arq.name, str(e).splitlines()[0][:90])
        tmp = _transcodificar(arq)
        encoding = "utf-8 (transcodificado)"
        leitura = _ler(con, tmp, destino, tabela, "utf-8", arq.name)
    finally:
        if tmp and tmp.exists():
            tmp.unlink()

    linhas_parquet = con.execute(f"SELECT count(*) FROM read_parquet('{destino.as_posix()}')").fetchone()[0]
    fisicas, registros = contar_registros(arq)
    status = "OK" if registros == linhas_parquet else "DIVERGENTE"
    seg = time.perf_counter() - t
    log.info("%-18s %-20s %12s registros origem | %12s linhas parquet | %-10s | %6.1fs",
             tabela, zip_stem, f"{registros:,}", f"{linhas_parquet:,}", status, seg)
    if fisicas != registros:
        log.info("%-18s %-20s %d registro(s) com quebra de linha dentro do campo (tratados corretamente)",
                 tabela, zip_stem, fisicas - registros)
    return {
        "competencia": comp, "tabela": tabela, "arquivo_zip": f"{zip_stem}.zip", "arquivo_origem": arq.name,
        "bytes_origem": arq.stat().st_size, "linhas_fisicas": fisicas, "linhas_origem": registros,
        "quebras_em_campo": fisicas - registros, "linhas_parquet": linhas_parquet, "status": status,
        "encoding_lido": encoding, "leitura": leitura, "segundos": round(seg, 1),
        "carregado_em": datetime.now().isoformat(timespec="seconds"),
    }


def _gravar_controle(novas: list[dict]) -> None:
    """Upsert no CSV de controle: reprocessar a mesma competência substitui as linhas (idempotência)."""
    chaves = {(r["competencia"], r["arquivo_zip"]) for r in novas}
    antigas = [r for r in ler_controle() if (r["competencia"], r["arquivo_zip"]) not in chaves]
    CONTROLE_CSV.parent.mkdir(parents=True, exist_ok=True)
    with open(CONTROLE_CSV, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CAMPOS_CONTROLE, extrasaction="ignore", restval="")
        w.writeheader()
        w.writerows(antigas + novas)


def executar(competencia: str | None = None, apagar_csv: bool = False, reprocessar: bool = False) -> list[dict]:
    comps = sorted(p.name for p in DIR_RAW.iterdir() if p.is_dir()) if DIR_RAW.exists() else []
    if not comps:
        raise SystemExit("Nada em data/raw. Rode a etapa 2 (extração) antes.")
    comp = competencia or comps[-1]
    arquivos = sorted(p for p in (DIR_RAW / comp).glob("*/*") if p.is_file())
    log.info("Convertendo %d arquivo(s) da competência %s (%s)", len(arquivos), comp,
             fmt_bytes(sum(a.stat().st_size for a in arquivos)))
    (DADOS / "tmp").mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    con.execute(f"SET temp_directory='{(DADOS / 'tmp').as_posix()}'; SET preserve_insertion_order=false;")
    t0 = time.perf_counter()
    resultados = []
    for arq in arquivos:
        if not reprocessar and ja_carregado(comp, f"{arq.parent.name}.zip"):
            log.info("%-18s %-20s já carregado e validado — pulando (use --reprocessar para refazer)",
                     tabela_do_zip(arq.parent.name), arq.parent.name)
            if apagar_csv:
                arq.unlink()
            continue
        r = converter_arquivo(con, arq, comp)
        resultados.append(r)
        _gravar_controle([r])          # grava a cada arquivo: se cair no meio, o que já foi feito não se perde
        if apagar_csv and r["status"] == "OK":
            arq.unlink()
    con.close()
    controle = [r for r in ler_controle() if r["competencia"] == comp]
    ok = sum(r["status"] == "OK" for r in controle)
    log.info("Bronze concluída em %.1f min | %d processado(s) agora | %d/%d arquivos OK na competência | %s linhas",
             (time.perf_counter() - t0) / 60, len(resultados), ok, len(controle),
             f"{sum(int(r['linhas_parquet']) for r in controle):,}")
    return resultados


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--competencia")
    ap.add_argument("--apagar-csv", action="store_true", help="apaga o CSV extraído após conversão OK (economiza disco)")
    ap.add_argument("--reprocessar", action="store_true", help="refaz arquivos já carregados e validados")
    a = ap.parse_args()
    executar(a.competencia, a.apagar_csv, a.reprocessar)
