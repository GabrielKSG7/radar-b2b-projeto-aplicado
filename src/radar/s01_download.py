"""Etapa 1 — Download automatizado dos arquivos do mês (dados abertos CNPJ).

- Descobre as competências (pastas AAAA-MM) no compartilhamento WebDAV da Receita.
- Baixa só os arquivos do recorte (config/recorte_mvp.yml -> arquivos_receita.incluir).
- Idempotente: pula arquivo que já existe com o mesmo tamanho; retoma download interrompido (.part + Range).

Uso:
    python -m radar.s01_download                       # competência mais recente
    python -m radar.s01_download --competencia 2026-10
    python -m radar.s01_download --somente Cnaes,Municipios   # teste rápido com arquivos pequenos
"""
from __future__ import annotations

import argparse
import os
import re
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import unquote, urljoin

import httpx

from radar.comum import DIR_ZIP, WEBDAV_TOKEN, WEBDAV_URL, carregar_recorte, fmt_bytes, logger

log = logger("download")
NS = {"d": "DAV:"}
RE_COMP = re.compile(r"^\d{4}-\d{2}$")


def _cliente() -> httpx.Client:
    token = os.environ.get("RFB_SHARE_TOKEN", WEBDAV_TOKEN)
    return httpx.Client(
        auth=(token, ""),
        timeout=httpx.Timeout(60.0, connect=20.0),
        follow_redirects=True,
        headers={"User-Agent": "radar-b2b/0.1 (projeto academico)"},
    )


def _propfind(cli: httpx.Client, url: str, tentativas: int = 15) -> list[dict]:
    """Lista uma pasta WebDAV. O balanceador da Receita às vezes responde 200 vazio: por isso o retry."""
    for i in range(1, tentativas + 1):
        try:
            r = cli.request("PROPFIND", url, headers={"Depth": "1"})
            if r.status_code == 207 and r.content:
                itens = []
                for resp in ET.fromstring(r.content).findall("d:response", NS):
                    href = unquote(resp.findtext("d:href", default="", namespaces=NS))
                    nome = href.rstrip("/").split("/")[-1]
                    tam = resp.findtext(".//d:getcontentlength", default="0", namespaces=NS)
                    eh_pasta = resp.find(".//d:resourcetype/d:collection", NS) is not None
                    itens.append({"nome": nome, "tamanho": int(tam or 0), "pasta": eh_pasta})
                return itens
            log.warning("PROPFIND %d/%d sem conteúdo válido (HTTP %s). Tentando de novo...", i, tentativas, r.status_code)
        except httpx.HTTPError as e:
            log.warning("PROPFIND %d/%d falhou: %s", i, tentativas, e)
        time.sleep(2)
    raise RuntimeError(f"Não foi possível listar {url}. O servidor da Receita pode estar instável; tente mais tarde.")


def listar_competencias(cli: httpx.Client) -> list[str]:
    return sorted(i["nome"] for i in _propfind(cli, WEBDAV_URL) if i["pasta"] and RE_COMP.match(i["nome"]))


def _baixar(cli: httpx.Client, url: str, destino: Path, tamanho_esperado: int) -> str:
    if destino.exists() and (tamanho_esperado == 0 or destino.stat().st_size == tamanho_esperado):
        return "ja_existia"
    parte = destino.with_suffix(destino.suffix + ".part")
    inicio = parte.stat().st_size if parte.exists() else 0
    headers = {"Range": f"bytes={inicio}-"} if inicio else {}
    with cli.stream("GET", url, headers=headers, timeout=httpx.Timeout(600.0, connect=30.0)) as r:
        if r.status_code == 200 and inicio:          # servidor ignorou o Range: recomeça do zero
            inicio = 0
        r.raise_for_status()
        with open(parte, "ab" if inicio else "wb") as f:
            f.writelines(r.iter_bytes(1024 * 1024))
    if tamanho_esperado and parte.stat().st_size != tamanho_esperado:
        raise OSError(f"Tamanho divergente em {destino.name}: {parte.stat().st_size} != {tamanho_esperado}")
    parte.replace(destino)
    return "baixado"


def executar(competencia: str = "latest", somente: list[str] | None = None) -> dict:
    prefixos = somente or carregar_recorte()["arquivos_receita"]["incluir"]
    t0 = time.perf_counter()
    with _cliente() as cli:
        comps = listar_competencias(cli)
        log.info("Competências disponíveis na Receita: %s ... %s (%d no total)", comps[0], comps[-1], len(comps))
        comp = comps[-1] if competencia == "latest" else competencia
        if comp not in comps:
            raise SystemExit(f"Competência {comp} não encontrada. Disponíveis: {comps[-6:]}")
        pasta_url = urljoin(WEBDAV_URL, comp + "/")
        arquivos = [i for i in _propfind(cli, pasta_url) if i["nome"].lower().endswith(".zip")]
        alvo = [a for a in arquivos if any(a["nome"].lower().startswith(p.lower()) for p in prefixos)]
        alvo.sort(key=lambda a: a["tamanho"])  # pequenos primeiro: falha cedo se algo estiver errado
        log.info("Competência %s: %d arquivos selecionados (%s)", comp, len(alvo), fmt_bytes(sum(a["tamanho"] for a in alvo)))

        destino_dir = DIR_ZIP / comp
        destino_dir.mkdir(parents=True, exist_ok=True)
        resumo = []
        for a in alvo:
            t = time.perf_counter()
            for tentativa in range(1, 4):
                try:
                    status = _baixar(cli, pasta_url + a["nome"], destino_dir / a["nome"], a["tamanho"])
                    break
                except (OSError, httpx.HTTPError) as e:
                    log.warning("%s: tentativa %d falhou (%s)", a["nome"], tentativa, e)
                    time.sleep(5 * tentativa)
            else:
                status = "erro"
            seg = time.perf_counter() - t
            log.info("%-26s %10s  %-10s %6.1fs", a["nome"], fmt_bytes(a["tamanho"]), status, seg)
            resumo.append({**a, "status": status, "segundos": round(seg, 1)})

    erros = [r for r in resumo if r["status"] == "erro"]
    log.info("Download concluído em %.1f min | %d arquivos | %d erro(s)", (time.perf_counter() - t0) / 60, len(resumo), len(erros))
    if erros:
        raise SystemExit("Arquivos com erro: " + ", ".join(e["nome"] for e in erros))
    return {"competencia": comp, "arquivos": resumo}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--competencia", default="latest")
    ap.add_argument("--somente", help="prefixos separados por vírgula, ex.: Cnaes,Municipios")
    a = ap.parse_args()
    executar(a.competencia, a.somente.split(",") if a.somente else None)
