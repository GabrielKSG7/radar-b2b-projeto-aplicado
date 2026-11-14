"""Gera o projeto do Power BI (PBIP: modelo em TMDL + relatório em PBIR) do painel Radar B2B.

    python painel/gerar_pbip.py                     # lê os tipos da Gold no radar.duckdb e grava painel/radar_b2b.*
    python painel/gerar_pbip.py --pasta-gold "D:\\outra\\pasta\\gold\\"

Depois: abra painel/radar_b2b.pbip no Power BI Desktop e clique em Atualizar (Página Inicial > Atualizar).
O projeto é texto (versionável no Git); o Power BI Desktop pode salvar por cima normalmente.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import uuid
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

NOME = "radar_b2b"
DESTINO = RAIZ / "painel"
SM = f"{NOME}.SemanticModel"
RP = f"{NOME}.Report"
SCHEMA = "https://developer.microsoft.com/json-schemas/fabric/item/report/definition"
FATO = "fct_estabelecimentos"
TABELAS = [FATO, "dim_municipio", "dim_cnae", "dim_porte", "dim_calendario"]

# ------------------------------------------------------------------ modelo semântico (TMDL)
TIPOS = {  # DuckDB -> (tipo TMDL, tipo do Power Query)
    "VARCHAR": ("string", "type text"),
    "BOOLEAN": ("boolean", "type logical"),
    "DATE": ("dateTime", "type date"),
    "DOUBLE": ("double", "type number"),
    "BIGINT": ("int64", "Int64.Type"),
    "INTEGER": ("int64", "Int64.Type"),
}

ROTULOS = {  # nomes amigáveis exibidos no painel (o nome técnico continua no modelo)
    "razao_social": "Razão social", "municipio": "Município", "faixa_prioridade": "Faixa", "score": "Score",
    "ranking": "Pos.", "regime_tributario": "Regime", "data_inicio_atividade": "Abertura",
    "telefone_1": "Telefone", "email": "E-mail", "motivos": "Por que está nesta posição",
    "etapa_funil": "Etapa do ICP", "secao_rotulo": "Setor (seção CNAE)", "porte": "Porte",
    "ano_mes": "Mês de abertura", "mes_rotulo": "Mês de abertura", "cnae": "CNAE principal",
    "fl_email_contabilidade": "E-mail de escritório contábil?",
}

MEDIDAS = [  # (nome, DAX, formato)
    ("Ativos", f"COUNTROWS ( {FATO} )", "#,0"),
    ("Abertos na janela", f"CALCULATE ( [Ativos], {FATO}[fl_aberto_na_janela] = TRUE () )", "#,0"),
    ("Oportunidades", f"CALCULATE ( [Ativos], {FATO}[fl_icp] = TRUE () )", "#,0"),
    ("Oportunidades Faixa A", f"CALCULATE ( [Oportunidades], {FATO}[faixa_prioridade] = \"A\" )", "#,0"),
    ("Sem contador identificado", f"CALCULATE ( [Oportunidades], {FATO}[fl_email_contabilidade] = FALSE () )", "#,0"),
    ("% do mercado ativo", "DIVIDE ( [Oportunidades], [Ativos] )", "0.0%"),
    ("Score medio", f"CALCULATE ( AVERAGE ( {FATO}[score] ), {FATO}[fl_icp] = TRUE () )", "0.0"),
    ("Base de referencia",
     f"\"Base da Receita com aberturas até \" & FORMAT ( MAX ( {FATO}[data_referencia] ), \"dd/mm/yyyy\" )", None),
]
ORDENAR_POR = {("dim_calendario", "ano_mes"): "ano_mes_num", ("dim_calendario", "mes_rotulo"): "ano_mes_num",
               ("dim_porte", "porte"): "ordem"}
RELACOES = [("municipio_cod", "dim_municipio", "municipio_cod"), ("cnae_cod", "dim_cnae", "cnae_cod"),
            ("porte_cod", "dim_porte", "porte_cod"), ("data_inicio_atividade", "dim_calendario", "data")]


def tag() -> str:
    return str(uuid.uuid4())


def q(nome: str) -> str:
    """Identificador TMDL: entre aspas simples se tiver espaço ou símbolo."""
    return nome if nome.replace("_", "").isalnum() else "'" + nome.replace("'", "''") + "'"


def tipo_tmdl(tipo_duckdb: str) -> tuple[str, str]:
    if tipo_duckdb.startswith("DECIMAL"):
        return "double", "type number"
    return TIPOS[tipo_duckdb]


def tabela_tmdl(nome: str, colunas: list[tuple[str, str]]) -> str:
    L = [f"table {nome}", f"\tlineageTag: {tag()}"]
    if nome == "dim_calendario":
        L.append("\tdataCategory: Time")
    L.append("")
    if nome == FATO:
        for m, dax, fmt in MEDIDAS:
            L.append(f"\tmeasure {q(m)} = {dax}")
            if fmt:
                L.append(f"\t\tformatString: {fmt}")
            L += [f"\t\tlineageTag: {tag()}", ""]
    for col, tipo in colunas:
        dt, _ = tipo_tmdl(tipo)
        L.append(f"\tcolumn {q(col)}")
        L.append(f"\t\tdataType: {dt}")
        if nome == "dim_calendario" and col == "data":
            L.append("\t\tisKey")
        if dt == "dateTime":
            L.append("\t\tformatString: dd/mm/yyyy")
        elif dt == "double":
            L.append("\t\tformatString: #,0.0" if col != "capital_social" else "\t\tformatString: #,0.00")
        elif dt == "int64":
            L.append("\t\tformatString: 0")
        L += [f"\t\tlineageTag: {tag()}", "\t\tsummarizeBy: none", f"\t\tsourceColumn: {col}"]
        if (nome, col) in ORDENAR_POR:
            L.append(f"\t\tsortByColumn: {ORDENAR_POR[(nome, col)]}")
        L += ["", "\t\tannotation SummarizationSetBy = User", ""]
        if dt == "dateTime":
            L += ["\t\tannotation UnderlyingDateTimeDataType = Date", ""]
    tipos_m = ", ".join(f'{{"{c}", {tipo_tmdl(t)[1]}}}' for c, t in colunas)
    L += [
        f"\tpartition {nome} = m",
        "\t\tmode: import",
        "\t\tsource =",
        "\t\t\t\tlet",
        f'\t\t\t\t    Fonte = Parquet.Document(File.Contents(PastaGold & "{nome}.parquet")),',
        f"\t\t\t\t    Tipos = Table.TransformColumnTypes(Fonte, {{{tipos_m}}})",
        "\t\t\t\tin",
        "\t\t\t\t    Tipos",
        "",
        "\tannotation PBI_ResultType = Table",
        "",
    ]
    return "\n".join(L)


def gerar_modelo(base: Path, schemas: dict[str, list[tuple[str, str]]], pasta_gold: str) -> None:
    d = base / SM / "definition"
    (d / "tables").mkdir(parents=True, exist_ok=True)
    (base / SM / "definition.pbism").write_text(json.dumps({"version": "4.0", "settings": {}}, indent=2), encoding="utf-8")
    (d / "database.tmdl").write_text("database\n\tcompatibilityLevel: 1601\n", encoding="utf-8")
    ordem = json.dumps(["PastaGold", *TABELAS])
    (d / "model.tmdl").write_text("\n".join([
        "model Model",
        "\tculture: pt-BR",
        "\tdefaultPowerBIDataSourceVersion: powerBI_V3",
        "\tdiscourageImplicitMeasures",
        "\tsourceQueryCulture: pt-BR",
        "\tdataAccessOptions",
        "\t\tlegacyRedirects",
        "\t\treturnErrorValuesAsNull",
        "",
        f"annotation PBI_QueryOrder = {ordem}",
        "",
        "annotation __PBI_TimeIntelligenceEnabled = 0",
        "",
        'annotation PBI_ProTooling = ["DevMode"]',
        "",
        *[f"ref table {t}" for t in TABELAS],
        "",
    ]), encoding="utf-8")
    caminho = pasta_gold.replace('"', '""')
    (d / "expressions.tmdl").write_text("\n".join([
        "/// Pasta com os Parquet da camada Gold, gerados pelo run_sprint3.py (com barra no final)",
        f'expression PastaGold = "{caminho}" meta [IsParameterQuery = true, Type = "Text", IsParameterQueryRequired = true]',
        f"\tlineageTag: {tag()}",
        "",
        "\tannotation PBI_ResultType = Text",
        "",
    ]), encoding="utf-8")
    rel = []
    for col, dim, chave in RELACOES:
        rel += [f"relationship {tag()}", f"\tfromColumn: {FATO}.{col}", f"\ttoColumn: {dim}.{chave}", ""]
    (d / "relationships.tmdl").write_text("\n".join(rel), encoding="utf-8")
    for t in TABELAS:
        (d / "tables" / f"{t}.tmdl").write_text(tabela_tmdl(t, schemas[t]), encoding="utf-8")


# ------------------------------------------------------------------ relatório (PBIR)
def lit(v: str) -> dict:
    return {"expr": {"Literal": {"Value": v}}}


def col(tab: str, c: str) -> dict:
    return {"Column": {"Expression": {"SourceRef": {"Entity": tab}}, "Property": c}}


def med(m: str) -> dict:
    return {"Measure": {"Expression": {"SourceRef": {"Entity": FATO}}, "Property": m}}


def proj(campo: dict, nome_amigavel: str | None = None) -> dict:
    tab = campo[next(iter(campo))]["Expression"]["SourceRef"]["Entity"]
    prop = campo[next(iter(campo))]["Property"]
    p = {"field": campo, "queryRef": f"{tab}.{prop}", "nativeQueryRef": prop}
    rot = nome_amigavel or ROTULOS.get(prop)
    if rot:
        p["displayName"] = rot
    return p


def filtro_verdadeiro(nome: str, tab: str, c: str) -> dict:
    return {
        "name": nome, "field": col(tab, c), "type": "Categorical", "howCreated": "User",
        "filter": {"Version": 2, "From": [{"Name": "t", "Entity": tab, "Type": 0}],
                   "Where": [{"Condition": {"In": {
                       "Expressions": [{"Column": {"Expression": {"SourceRef": {"Source": "t"}}, "Property": c}}],
                       "Values": [[{"Literal": {"Value": "true"}}]]}}}]},
    }


class Pagina:
    def __init__(self, nome: str, titulo: str):
        self.nome, self.titulo, self.visuais, self.z = nome, titulo, [], 0

    def add(self, nome: str, x, y, w, h, visual: dict, filtros: list | None = None, titulo: str | None = None):
        self.z += 1000
        if titulo:
            visual.setdefault("visualContainerObjects", {})["title"] = [
                {"properties": {"show": lit("true"), "text": lit(f"'{titulo}'")}}]
        visual.setdefault("drillFilterOtherVisuals", True)
        v = {"$schema": f"{SCHEMA}/visualContainer/2.0.0/schema.json", "name": nome,
             "position": {"x": x, "y": y, "z": self.z, "width": w, "height": h, "tabOrder": self.z},
             "visual": visual}
        if filtros:
            v["filterConfig"] = {"filters": filtros}
        self.visuais.append(v)


def texto(t: str, tamanho="20pt") -> dict:
    return {"visualType": "textbox", "objects": {"general": [{"properties": {"paragraphs": [
        {"textRuns": [{"value": t, "textStyle": {"fontWeight": "bold", "fontSize": tamanho}}]}]}}]}}


def cartao(medida: str, tamanho="24D", rotulo=True) -> dict:
    return {"visualType": "card",
            "query": {"queryState": {"Values": {"projections": [proj(med(medida))]}}},
            "objects": {"labels": [{"properties": {"fontSize": lit(tamanho), "labelDisplayUnits": lit("1D")}}],
                        "categoryLabels": [{"properties": {"show": lit("true" if rotulo else "false")}}]}}


def segmentacao(campo: dict) -> dict:
    return {"visualType": "slicer",
            "query": {"queryState": {"Values": {"projections": [proj(campo)]}},
                      "sortDefinition": {"sort": [{"field": campo, "direction": "Ascending"}], "isDefaultSort": True}},
            "objects": {"data": [{"properties": {"mode": lit("'Dropdown'")}}]}}


def barras(tipo: str, categoria: dict, valores: list[dict], ordenar: dict, direcao="Descending",
           serie: dict | None = None) -> dict:
    qs = {"Category": {"projections": [{**proj(categoria), "active": True}]},
          "Y": {"projections": [proj(v) for v in valores]}}
    if serie:
        qs["Series"] = {"projections": [proj(serie)]}
    return {"visualType": tipo,
            "query": {"queryState": qs, "sortDefinition": {"sort": [{"field": ordenar, "direction": direcao}]}},
            "objects": {"labels": [{"properties": {"show": lit("true"), "labelDisplayUnits": lit("1D")}}]}}


def filtro_exceto(nome: str, tab: str, c: str, valor: str) -> dict:
    cond = {"In": {"Expressions": [{"Column": {"Expression": {"SourceRef": {"Source": "t"}}, "Property": c}}],
                   "Values": [[{"Literal": {"Value": f"'{valor}'"}}]]}}
    return {"name": nome, "field": col(tab, c), "type": "Categorical", "howCreated": "User",
            "filter": {"Version": 2, "From": [{"Name": "t", "Entity": tab, "Type": 0}],
                       "Where": [{"Condition": {"Not": {"Expression": cond}}}]}}


def pagina_mercado() -> Pagina:
    p = Pagina("mercado", "Mercado x Oportunidades")
    seg = [(col("dim_municipio", "municipio"), "seg_municipio"), (col("dim_cnae", "secao_rotulo"), "seg_setor"),
           (col("dim_porte", "porte"), "seg_porte"), (col("dim_calendario", "ano_mes"), "seg_mes")]
    for i, (campo, nome) in enumerate(seg):
        filtros = [filtro_verdadeiro("FiltroJanelaMes", "dim_calendario", "fl_janela_prospeccao")] if nome == "seg_mes" else None
        p.add(nome, 10, 70 + i * 95, 195, 85, segmentacao(campo), filtros)
    p.add("titulo", 215, 5, 760, 45, texto("Radar B2B — Oportunidades na Microrregião de Varginha", "18pt"))
    p.add("base_referencia", 975, 5, 295, 55, cartao("Base de referencia", "11D", rotulo=False))
    for i, m in enumerate(["Ativos", "Abertos na janela", "Oportunidades", "Oportunidades Faixa A"]):
        p.add(f"kpi_{i}", 215 + i * 265, 60, 255, 95, cartao(m))
    p.add("funil", 215, 165, 520, 270,
          barras("clusteredBarChart", col(FATO, "etapa_funil"), [med("Ativos")], col(FATO, "etapa_funil"), "Ascending"),
          [filtro_exceto("FiltroForaJanela", FATO, "etapa_funil", "1. Aberta antes da janela")],
          titulo="Abertas na janela de 6 meses: onde cada uma sai do ICP")
    p.add("por_mes", 745, 165, 525, 270,
          barras("columnChart", col("dim_calendario", "mes_rotulo"), [med("Oportunidades")],
                 col("dim_calendario", "mes_rotulo"), "Ascending", serie=col(FATO, "faixa_prioridade")),
          [filtro_verdadeiro("FiltroJanela", "dim_calendario", "fl_janela_prospeccao")],
          titulo="Oportunidades por mês de abertura e faixa")
    p.add("por_municipio", 215, 445, 520, 270,
          barras("clusteredBarChart", col("dim_municipio", "municipio"),
                 [med("Oportunidades"), med("Oportunidades Faixa A")], med("Oportunidades")),
          titulo="Oportunidades por município")
    p.add("por_setor", 745, 445, 525, 270,
          barras("clusteredBarChart", col("dim_cnae", "secao_rotulo"), [med("Oportunidades")], med("Oportunidades")),
          titulo="Oportunidades por setor")
    return p


def pagina_lista() -> Pagina:
    p = Pagina("lista", "Lista priorizada")
    seg = [(col("dim_municipio", "municipio"), "seg_municipio"), (col("dim_cnae", "secao_rotulo"), "seg_setor"),
           (col("dim_porte", "porte"), "seg_porte"), (col("dim_calendario", "ano_mes"), "seg_mes"),
           (col(FATO, "faixa_prioridade"), "seg_faixa"), (col(FATO, "fl_email_contabilidade"), "seg_contador")]
    for i, (campo, nome) in enumerate(seg):
        filtros = [filtro_verdadeiro("FiltroJanelaMes", "dim_calendario", "fl_janela_prospeccao")] if nome == "seg_mes" else None
        p.add(nome, 10, 10 + i * 95, 195, 85, segmentacao(campo), filtros)
    p.add("titulo", 215, 5, 640, 45, texto("Radar B2B — Lista priorizada de prospecção", "18pt"))
    p.add("base_referencia", 975, 5, 295, 55, cartao("Base de referencia", "11D", rotulo=False))
    for i, m in enumerate(["Oportunidades", "Sem contador identificado", "Score medio"]):
        p.add(f"kpi_{i}", 215 + i * 265, 55, 255, 85, cartao(m, "20D"))
    campos = [col(FATO, "ranking"), col(FATO, "faixa_prioridade"), col(FATO, "score"), col(FATO, "razao_social"),
              col(FATO, "municipio"), col("dim_cnae", "cnae"), col("dim_porte", "porte"), col(FATO, "regime_tributario"),
              col(FATO, "data_inicio_atividade"), col(FATO, "telefone_1"), col(FATO, "email"), col(FATO, "motivos")]
    tabela = {"visualType": "tableEx",
              "query": {"queryState": {"Values": {"projections": [proj(c) for c in campos]}},
                        "sortDefinition": {"sort": [{"field": col(FATO, "ranking"), "direction": "Ascending"}]}}}
    p.add("tabela_oportunidades", 215, 150, 1055, 565, tabela, titulo="Oportunidades do ICP, da mais para a menos prioritária")
    p.filtros = [filtro_verdadeiro("FiltroICP", FATO, "fl_icp")]
    return p


def gravar_json(caminho: Path, dados: dict) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(json.dumps(dados, indent=2, ensure_ascii=False), encoding="utf-8")


def gerar_relatorio(base: Path, tema: Path) -> list[Path]:
    r = base / RP
    gravar_json(r / "definition.pbir", {
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definitionProperties/2.0.0/schema.json",
        "version": "4.0", "datasetReference": {"byPath": {"path": f"../{SM}"}}})
    d = r / "definition"
    gravar_json(d / "version.json", {"$schema": f"{SCHEMA}/versionMetadata/1.0.0/schema.json", "version": "2.0.0"})
    nome_tema = tema.stem
    gravar_json(d / "report.json", {
        "$schema": f"{SCHEMA}/report/1.3.0/schema.json",
        "themeCollection": {"baseTheme": {"name": nome_tema, "reportVersionAtImport": "5.61", "type": "SharedResources"}},
        "layoutOptimization": "None",
        "resourcePackages": [{"name": "SharedResources", "type": "SharedResources",
                              "items": [{"name": nome_tema, "path": f"BaseThemes/{tema.name}", "type": "BaseTheme"}]}],
        "settings": {"useStylableVisualContainerHeader": True, "exportDataMode": "AllowSummarized",
                     "defaultDrillFilterOtherVisuals": True, "allowChangeFilterTypes": True, "useEnhancedTooltips": True},
    })
    destino_tema = r / "StaticResources" / "SharedResources" / "BaseThemes" / tema.name
    destino_tema.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(tema, destino_tema)
    paginas = [pagina_mercado(), pagina_lista()]
    gravar_json(d / "pages" / "pages.json", {"$schema": f"{SCHEMA}/pagesMetadata/1.0.0/schema.json",
                                             "pageOrder": [p.nome for p in paginas], "activePageName": paginas[0].nome})
    arquivos = []
    for p in paginas:
        page = {"$schema": f"{SCHEMA}/page/1.4.0/schema.json", "name": p.nome, "displayName": p.titulo,
                "displayOption": "FitToPage", "height": 720, "width": 1280}
        if getattr(p, "filtros", None):
            page["filterConfig"] = {"filters": p.filtros}
        gravar_json(d / "pages" / p.nome / "page.json", page)
        arquivos.append(d / "pages" / p.nome / "page.json")
        for v in p.visuais:
            caminho = d / "pages" / p.nome / "visuals" / v["name"] / "visual.json"
            gravar_json(caminho, v)
            arquivos.append(caminho)
    return arquivos


def main() -> None:
    import duckdb
    from radar.comum import DB_PATH

    ap = argparse.ArgumentParser()
    ap.add_argument("--pasta-gold", default=str(RAIZ / "data" / "gold") + "\\")
    ap.add_argument("--tema", default=str(Path(__file__).parent / "tema" / "CY24SU10.json"))
    a = ap.parse_args()
    con = duckdb.connect(str(DB_PATH), read_only=True)
    schemas = {t: [(r[0], r[1]) for r in con.execute(f"DESCRIBE gold.{t}").fetchall()] for t in TABELAS}
    con.close()
    for pasta in (DESTINO / SM, DESTINO / RP):
        if pasta.exists():
            shutil.rmtree(pasta)
    gerar_modelo(DESTINO, schemas, a.pasta_gold)
    gerar_relatorio(DESTINO, Path(a.tema))
    gravar_json(DESTINO / f"{NOME}.pbip", {"version": "1.0", "artifacts": [{"report": {"path": RP}}],
                                            "settings": {"enableAutoRecovery": True}})
    print(f"Projeto gerado em {DESTINO / (NOME + '.pbip')}  (PastaGold = {a.pasta_gold})")


if __name__ == "__main__":
    main()
