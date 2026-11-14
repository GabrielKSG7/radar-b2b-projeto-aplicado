"""Etapa 2 — Descompactação dos .zip da competência.

Cada zip vira uma pasta em data/raw/<competencia>/<NomeDoZip>/ (ex.: Estabelecimentos3/).
Idempotente: se a pasta já tem o arquivo extraído com o mesmo tamanho, pula.
Protegido contra "zip slip" (nomes com ../).
"""
from __future__ import annotations

import argparse
import time
import zipfile
from pathlib import Path

from radar.comum import DIR_RAW, DIR_ZIP, fmt_bytes, ja_carregado, logger

log = logger("extrair")


def ultima_competencia() -> str:
    comps = sorted(p.name for p in DIR_ZIP.iterdir() if p.is_dir())
    if not comps:
        raise SystemExit("Nenhuma competência em data/zip. Rode a etapa 1 (download) antes.")
    return comps[-1]


def executar(competencia: str | None = None, reprocessar: bool = False) -> list[Path]:
    comp = competencia or ultima_competencia()
    zips = sorted((DIR_ZIP / comp).glob("*.zip"))
    t0 = time.perf_counter()
    extraidos: list[Path] = []
    for z in zips:
        if not reprocessar and ja_carregado(comp, z.name):
            log.info("%-26s já está na Bronze e validado — não precisa extrair", z.name)
            continue
        destino = DIR_RAW / comp / z.stem
        destino.mkdir(parents=True, exist_ok=True)
        try:
            with zipfile.ZipFile(z) as zf:
                for info in zf.infolist():
                    if info.is_dir():
                        continue
                    alvo = (destino / Path(info.filename).name).resolve()
                    if destino.resolve() not in alvo.parents:
                        raise ValueError(f"Caminho suspeito dentro do zip: {info.filename}")
                    if alvo.exists() and alvo.stat().st_size == info.file_size:
                        status = "ja_existia"
                    else:
                        with zf.open(info) as src, open(alvo, "wb") as dst:
                            while bloco := src.read(8 * 1024 * 1024):
                                dst.write(bloco)
                        status = "extraido"
                    extraidos.append(alvo)
                    log.info("%-26s -> %-38s %10s  %s", z.name, alvo.name, fmt_bytes(info.file_size), status)
        except zipfile.BadZipFile:
            log.error("%s está corrompido. Apague o arquivo e rode o download de novo.", z.name)
            raise
    log.info("Extração concluída em %.1fs | %d arquivo(s)", time.perf_counter() - t0, len(extraidos))
    return extraidos


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--competencia")
    executar(ap.parse_args().competencia)
