"""Gera uma AMOSTRA SINTÉTICA no layout da Receita para testar o pipeline sem baixar ~6 GB.

Uso (só para teste — NÃO use como evidência da Sprint):
    python tests/gerar_amostra.py
    python run_sprint1.py --pular-download --competencia 2000-01
Depois apague data/ e rode o pipeline real.
"""
from __future__ import annotations

import random
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from radar.comum import DIR_ZIP

COMP = sys.argv[1] if len(sys.argv) > 1 else "2000-01"
random.seed(42)
MUNIS = [("9001", "VARGINHA"), ("9002", "TRES CORACOES"), ("9003", "TRÊS PONTAS"), ("9004", "ELOI MENDES"),
         ("9005", "BOA ESPERANCA"), ("9006", "CAMPANHA"), ("9007", "CAMPO DO MEIO"), ("9008", "CAMPOS GERAIS"),
         ("9009", "CARMO DA CACHOEIRA"), ("9010", "COQUEIRAL"), ("9011", "GUAPE"), ("9012", "ILICINEA"),
         ("9013", "MONSENHOR PAULO"), ("9014", "SANTANA DA VARGEM"), ("9015", "SAO BENTO ABADE"),
         ("9016", "SAO TOME DAS LETRAS"), ("7107", "SAO PAULO"), ("4123", "BELO HORIZONTE"), ("8001", "BOA ESPERANCA")]


def linha(campos: list[str]) -> str:
    return ";".join(f'"{c}"' for c in campos)


def gravar(nome_zip: str, nome_interno: str, linhas: list[str], bytes_extras: bytes = b"") -> None:
    destino = DIR_ZIP / COMP
    destino.mkdir(parents=True, exist_ok=True)
    conteudo = ("\n".join(linhas) + "\n").encode("latin-1") + bytes_extras
    with zipfile.ZipFile(destino / nome_zip, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(nome_interno, conteudo)


gravar("Municipios.zip", "F.K03200$Z.D51108.MUNICCSV", [linha(m) for m in MUNIS])
gravar("Cnaes.zip", "F.K03200$Z.D51108.CNAECSV",
       [linha(["6920601", "Atividades de contabilidade"]), linha(["4781400", "Comércio varejista de artigos do vestuário"]),
        linha(["5611201", "Restaurantes e similares"]), linha(["8411600", "Administração pública em geral"])])
gravar("Naturezas.zip", "F.K03200$Z.D51108.NATJUCSV",
       [linha(["2062", "Sociedade Empresária Limitada"]), linha(["2135", "Empresário (Individual)"]),
        linha(["3999", "Associação Privada"])])
gravar("Motivos.zip", "F.K03200$Z.D51108.MOTICSV", [linha(["00", "SEM MOTIVO"]), linha(["01", "EXTINCAO POR ENCERRAMENTO"])])
for nome in ("Paises", "Qualificacoes"):
    gravar(f"{nome}.zip", f"F.K03200$Z.D51108.{nome.upper()}", [linha(["01", f"Item de {nome}"]), linha(["02", "Ação"])])

for parte in range(2):
    est, emp, sim = [], [], []
    for i in range(5000):
        base = f"{parte}{i:07d}"
        cod, _ = random.choice(MUNIS)
        uf = {"7107": "SP", "8001": "ES"}.get(cod, "MG")
        nome = f"LOJA {i}\nFILIAL" if i == 4321 else f"LOJA {i} D'ÁGUA"   # quebra de linha dentro do campo, como no real
        # Sprint 2: sujeiras que a Silver precisa tratar (datas "0", TAB, espaços, e-mail maiúsculo, CNAE secundário)
        inicio = "0" if i == 7 else f"{random.choice([2019, 2024, 2025, 2026])}{random.randint(1, 10):02d}15"
        bairro = "CENTRO\tVELHO" if i == 11 else "  JARDIM   ANDERE "
        registro = [base, "0001", "00", "1", nome, random.choice(["02", "02", "08", "04", "2"]), "20260101",
                    random.choice(["00", "01"]), "", "", inicio, random.choice(["6920601", "4781400", "5611201", "8411600"]),
                    "4781400,5611201" if i % 3 == 0 else "", "RUA", "DAS FLORES", str(i), "", bairro, "37000000", uf, cod,
                    "35", "32210000", "", "", "", "", f" Contato{i}@Exemplo.COM ", "", ""]
        est.append(linha(registro))
        if i in (100, 200):                       # mesmo CNPJ repetido na origem
            est.append(linha(registro[:6] + ["20250101"] + registro[7:]))
        emp.append(linha([base, f"EMPRESA {i}  LTDA", random.choice(["2062", "2062", "2135", "3999"]), "49",
                          random.choice(["10000,00", "1500,50", "0,00"]), random.choice(["01", "03", "05", "00"]), ""]))
        sim.append(linha([base, "S", "20260101", "", random.choice(["S", "N", "N"]), "", ""]))
    # um byte de controle 0x96 no fim de um arquivo, como acontece em alguns arquivos reais
    extra = (linha([f"9{parte}999999", "0001", "00", "1", "ACME", "02", "", "", "", "", "20261001", "6920601", "", "",
                    "", "", "", "", "", "MG", "9001", "", "", "", "", "", "", "", "", ""]) + "\n").encode("latin-1").replace(b"ACME", b"AC\x96ME")
    gravar(f"Estabelecimentos{parte}.zip", f"K3241.K03200Y{parte}.D51108.ESTABELE", est, extra if parte == 1 else b"")
    gravar(f"Empresas{parte}.zip", f"K3241.K03200Y{parte}.D51108.EMPRECSV", emp)
    if parte == 0:
        gravar("Simples.zip", "F.K03200$W.SIMPLES.CSV.D51108", sim)

print(f"Amostra sintética gerada em {DIR_ZIP / COMP}")
