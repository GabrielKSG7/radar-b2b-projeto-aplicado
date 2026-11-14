"""Radar B2B — execução ponta a ponta da Sprint 1 (camada Bronze).

    python run_sprint1.py                          # competência mais recente da Receita
    python run_sprint1.py --competencia 2026-10
    python run_sprint1.py --pular-download         # reaproveita os .zip já baixados
    python run_sprint1.py --somente Cnaes,Municipios  # teste de conexão (arquivos de poucos KB)
    python run_sprint1.py --apagar-csv             # apaga os CSV extraídos após conversão OK (economiza ~20 GB)
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from radar import s01_download, s02_extrair, s03_bronze, s04_duckdb
from radar.comum import DB_PATH, DIR_BRONZE, DIR_LOGS, RAIZ, fmt_bytes, logger

log = logger("pipeline")


def etapa(nome: str, func, tempos: dict, *args, **kwargs):
    log.info(">>> %s", nome)
    t = time.perf_counter()
    r = func(*args, **kwargs)
    tempos[nome] = time.perf_counter() - t
    return r


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--competencia", default=None)
    ap.add_argument("--pular-download", action="store_true")
    ap.add_argument("--apagar-csv", action="store_true")
    ap.add_argument("--sem-dbt", action="store_true")
    ap.add_argument("--reprocessar", action="store_true", help="refaz arquivos que já estão carregados e validados")
    ap.add_argument("--somente", help="teste de conexão: baixa só estes arquivos, ex.: Cnaes,Municipios")
    a = ap.parse_args()

    tempos: dict[str, float] = {}
    t0 = time.perf_counter()
    comp = a.competencia
    if not a.pular_download:
        comp = etapa("1. Download", s01_download.executar, tempos, a.competencia or "latest",
                     a.somente.split(",") if a.somente else None)["competencia"]
    etapa("2. Descompactação", s02_extrair.executar, tempos, comp, a.reprocessar)
    etapa("3. CSV -> Parquet (Bronze)", s03_bronze.executar, tempos, comp, a.apagar_csv, a.reprocessar)
    val = etapa("4. Carga DuckDB + validação", s04_duckdb.executar, tempos, comp)

    dbt_status = "não executado"
    if not a.sem_dbt and shutil.which("dbt"):
        t = time.perf_counter()
        proj = RAIZ / "radar_dbt"
        env = {**os.environ, "RADAR_DB_PATH": str(DB_PATH)}
        r = subprocess.run(["dbt", "test", "--profiles-dir", "."], cwd=proj, env=env)
        tempos["5. dbt test (fontes Bronze)"] = time.perf_counter() - t
        dbt_status = "PASS" if r.returncode == 0 else "FALHOU"

    total = time.perf_counter() - t0
    comp = val["competencia"]
    bytes_parquet = sum(p.stat().st_size for p in DIR_BRONZE.glob(f"*/competencia={comp}/*.parquet"))
    reducao = (1 - bytes_parquet / val["bytes_origem"]) * 100 if val["bytes_origem"] else 0
    linhas = [
        "",
        "=" * 64,
        f"  RADAR B2B — RESUMO DA SPRINT 1 (Bronze) — competência {val['competencia']}",
        "=" * 64,
        *[f"  {k:<34} {v / 60:8.1f} min" for k, v in tempos.items()],
        "-" * 64,
        f"  {'Tempo total ponta a ponta':<34} {total / 60:8.1f} min",
        f"  {'Arquivos carregados':<34} {val['arquivos']:>12}",
        f"  {'Linhas na camada Bronze':<34} {val['linhas']:>12,}",
        f"  {'Arquivos com divergência':<34} {val['divergentes']:>12}",
        f"  {'Tamanho CSV (origem)':<34} {fmt_bytes(val['bytes_origem']):>12}",
        f"  {'Tamanho Parquet (Bronze)':<34} {fmt_bytes(bytes_parquet):>12}",
        f"  {'Redução de armazenamento':<34} {reducao:>11.0f}%",
        f"  {'Municípios do recorte resolvidos':<34} {val['municipios_recorte']:>12}",
        f"  {'Testes dbt nas fontes':<34} {dbt_status:>12}",
        "=" * 64,
    ]
    texto = "\n".join(linhas)
    print(texto)
    carimbo = time.strftime("%Y%m%d_%H%M")      # não sobrescreve resumos anteriores
    (DIR_LOGS / f"resumo_sprint1_{val['competencia']}_{carimbo}.txt").write_text(texto, encoding="utf-8")


if __name__ == "__main__":
    main()
