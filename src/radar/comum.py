"""Configurações e utilitários compartilhados do pipeline Radar B2B."""
from __future__ import annotations

import csv
import logging
import re
import sys
from pathlib import Path

import yaml

RAIZ = Path(__file__).resolve().parents[2]
DADOS = RAIZ / "data"
DIR_ZIP = DADOS / "zip"            # arquivos baixados da Receita (fonte da verdade)
DIR_RAW = DADOS / "raw"            # CSV extraídos (temporários)
DIR_BRONZE = DADOS / "bronze"      # Parquet particionado por competência
DB_PATH = DADOS / "radar.duckdb"
CONTROLE_CSV = DIR_BRONZE / "_controle_carga.csv"
DIR_LOGS = RAIZ / "logs"
CONFIG = RAIZ / "config" / "recorte_mvp.yml"

# Novo endereço (Nextcloud/WebDAV) — a pasta antiga /dados/cnpj/dados_abertos_cnpj/ foi descontinuada.
WEBDAV_URL = "https://arquivos.receitafederal.gov.br/public.php/webdav/Dados/Cadastros/CNPJ/"
WEBDAV_TOKEN = "gn672Ad4CF8N6TK"   # token público do compartilhamento; pode ser trocado por RFB_SHARE_TOKEN
LEGADO_URL = "https://arquivos.receitafederal.gov.br/dados/cnpj/dados_abertos_cnpj/"

# Layout oficial dos dados abertos do CNPJ (arquivos sem cabeçalho).
DOMINIO = ["codigo", "descricao"]
LAYOUTS: dict[str, list[str]] = {
    "empresas": [
        "cnpj_basico", "razao_social", "natureza_juridica", "qualificacao_responsavel",
        "capital_social", "porte_empresa", "ente_federativo_responsavel",
    ],
    "estabelecimentos": [
        "cnpj_basico", "cnpj_ordem", "cnpj_dv", "identificador_matriz_filial", "nome_fantasia",
        "situacao_cadastral", "data_situacao_cadastral", "motivo_situacao_cadastral",
        "nome_cidade_exterior", "pais", "data_inicio_atividade", "cnae_fiscal_principal",
        "cnae_fiscal_secundaria", "tipo_logradouro", "logradouro", "numero", "complemento",
        "bairro", "cep", "uf", "municipio", "ddd_1", "telefone_1", "ddd_2", "telefone_2",
        "ddd_fax", "fax", "correio_eletronico", "situacao_especial", "data_situacao_especial",
    ],
    "simples": [
        "cnpj_basico", "opcao_simples", "data_opcao_simples", "data_exclusao_simples",
        "opcao_mei", "data_opcao_mei", "data_exclusao_mei",
    ],
    "socios": [
        "cnpj_basico", "identificador_socio", "nome_socio", "cnpj_cpf_socio", "qualificacao_socio",
        "data_entrada_sociedade", "pais", "representante_legal", "nome_representante",
        "qualificacao_representante", "faixa_etaria",
    ],
    "cnaes": DOMINIO, "municipios": DOMINIO, "naturezas": DOMINIO,
    "motivos": DOMINIO, "paises": DOMINIO, "qualificacoes": DOMINIO,
}


def tabela_do_zip(nome_zip: str) -> str:
    """'Estabelecimentos3.zip' -> 'estabelecimentos'."""
    return re.sub(r"\d+$", "", Path(nome_zip).stem).lower()


def carregar_recorte() -> dict:
    with open(CONFIG, encoding="utf-8") as f:
        return yaml.safe_load(f)


def logger(nome: str) -> logging.Logger:
    DIR_LOGS.mkdir(parents=True, exist_ok=True)
    log = logging.getLogger(nome)
    if log.handlers:
        return log
    log.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s | %(levelname)-7s | %(name)s | %(message)s", "%Y-%m-%d %H:%M:%S")
    for h in (logging.StreamHandler(sys.stdout), logging.FileHandler(DIR_LOGS / "pipeline.log", encoding="utf-8")):
        h.setFormatter(fmt)
        log.addHandler(h)
    return log


def fmt_bytes(n: float) -> str:
    for u in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:,.1f} {u}"
        n /= 1024
    return f"{n:,.1f} TB"


def ler_controle() -> list[dict]:
    if not CONTROLE_CSV.exists():
        return []
    with open(CONTROLE_CSV, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def ja_carregado(competencia: str, arquivo_zip: str) -> bool:
    """True se o zip já foi convertido, validado (status OK) e o Parquet ainda existe."""
    for r in ler_controle():
        if r["competencia"] == competencia and r["arquivo_zip"] == arquivo_zip and r["status"] == "OK":
            parquet = DIR_BRONZE / r["tabela"] / f"competencia={competencia}" / arquivo_zip.replace(".zip", ".parquet")
            return parquet.exists()
    return False
