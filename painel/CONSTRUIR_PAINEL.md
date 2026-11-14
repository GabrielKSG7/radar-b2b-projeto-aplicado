# Painel Radar B2B no Power BI Desktop

## Atalho: projeto pronto (`radar_b2b.pbip`)

O painel já vem como projeto do Power BI (modelo em TMDL + relatório em PBIR), gerado por `painel\gerar_pbip.py`:

1. Rode `python run_sprint3.py` (gera `data\gold\*.parquet`).
2. Abra `painel\radar_b2b.pbip` no Power BI Desktop.
3. **Página Inicial > Atualizar** (o projeto abre sem dados; a atualização lê os Parquet).
4. **Arquivo > Salvar como** `radar_b2b.pbix` se quiser um arquivo único.

Se mover o projeto de pasta, ajuste o parâmetro `PastaGold` (Transformar dados > Gerenciar parâmetros)
ou gere de novo com `python painel\gerar_pbip.py --pasta-gold "<nova pasta>\"`.

O passo a passo manual abaixo continua valendo caso o Power BI recuse abrir o projeto.

---

Tempo estimado: 40 a 60 minutos. Ao final, salve como `painel\radar_b2b.pbix`.
Pré-requisito: ter rodado `python run_sprint3.py` (gera `data\gold\*.parquet`).

## 1. Carregar os dados (Power Query)

1. Abra o Power BI Desktop > **Obter dados > Consulta em branco** > feche a janela que abrir e vá em **Transformar dados**.
2. **Gerenciar Parâmetros > Novo**: nome `PastaGold`, tipo **Texto**, valor:
   `G:\XP\PA\SPRINTS\SPRINT 1 - SP105 - Postagem da Sprint 1\radar-b2b\data\gold\` (com `\` no final).
3. Para cada uma das 5 tabelas de `consultas_powerquery.m`: **Nova Fonte > Consulta Nula > Editor Avançado**, cole o bloco, clique em Concluído e renomeie a consulta (fct_estabelecimentos, dim_municipio, dim_cnae, dim_porte, dim_calendario).
4. Apague a consulta em branco do passo 1 > **Fechar e Aplicar**.

> **Print para o relatório (Requisito 1):** a tela do Power Query com as 5 consultas listadas à esquerda.

## 2. Modelo estrela (exibição de Modelo)

Crie os relacionamentos arrastando a coluna do fato para a dimensão (todos **Muitos para um**, filtro em **direção única**):

| fct_estabelecimentos | → | dimensão |
|---|---|---|
| `municipio_cod` | → | `dim_municipio[municipio_cod]` |
| `cnae_cod` | → | `dim_cnae[cnae_cod]` |
| `porte_cod` | → | `dim_porte[porte_cod]` |
| `data_inicio_atividade` | → | `dim_calendario[data]` |

Ordenações (exibição de Dados > selecione a coluna > **Classificar por coluna**):
- `dim_calendario[ano_mes]` e `dim_calendario[mes_rotulo]` → por `ano_mes_num`
- `dim_porte[porte]` → por `ordem`

Marque `dim_calendario` como tabela de datas (**Marcar como tabela de datas** > coluna `data`).

> **Print para o relatório (Requisito 1):** a exibição de Modelo mostrando a estrela (fato no centro, 4 dimensões).

## 3. Medidas

Cole as medidas de `medidas.dax` na tabela `fct_estabelecimentos` (uma por vez, **Nova medida**).
Formate `% do mercado ativo` como porcentagem com 1 casa e `Score medio` com 1 casa decimal.

## 4. Página 1 — "Mercado x Oportunidades"

Tema sugerido: **Exibir > Temas > Executivo** (ou o padrão).

| Visual | Configuração |
|---|---|
| Caixa de texto (topo) | "Radar B2B — Oportunidades de prospecção · Microrregião de Varginha" |
| Cartão | medida `Base de referencia` (fonte pequena, abaixo do título) |
| 4 Cartões (linha) | `Ativos` · `Abertos na janela` · `Oportunidades` · `Oportunidades Faixa A` |
| Gráfico de barras **horizontais** "Funil do ICP" | Eixo Y: `fct_estabelecimentos[etapa_funil]` · Eixo X: `Ativos` · ordenar pelo eixo Y crescente · rótulos de dados ligados |
| Gráfico de colunas **empilhadas** "Oportunidades por mês de abertura" | Eixo X: `dim_calendario[mes_rotulo]` · Eixo Y: `Oportunidades` · Legenda: `faixa_prioridade` · Filtro do visual: `dim_calendario[fl_janela_prospeccao]` = Verdadeiro |
| Gráfico de barras "Oportunidades por município" | Eixo Y: `dim_municipio[municipio]` · Eixo X: `Oportunidades` e `Oportunidades Faixa A` |
| Gráfico de barras "Top 10 setores" | Eixo Y: `dim_cnae[secao_rotulo]` · Eixo X: `Oportunidades` · Filtro do visual: **N superior** 10 por `Oportunidades` |
| 4 Segmentações (lado esquerdo) | `dim_municipio[municipio]` · `dim_cnae[secao_rotulo]` · `dim_porte[porte]` · `dim_calendario[ano_mes]` |

Na segmentação de mês: filtro do visual `dim_calendario[fl_janela_prospeccao]` = Verdadeiro (senão ela lista meses desde 1954) e estilo **Lista suspensa**.
Cores das faixas (Formatar > Cores): A = verde, B = amarelo/âmbar, C = cinza.

> **Prints para o relatório:** a página inteira sem filtro (Requisito 3) e a mesma página com um filtro aplicado,
> por exemplo município = VARGINHA e porte = DEMAIS, mostrando os números mudando (prova dos filtros).

## 5. Página 2 — "Lista priorizada"

1. Duplique a página 1 (para manter as segmentações), apague os gráficos e renomeie para "Lista priorizada".
2. Painel de filtros > **Filtros nesta página**: `fct_estabelecimentos[fl_icp]` = Verdadeiro.
3. Adicione duas segmentações: `faixa_prioridade` e `fl_email_contabilidade` (renomeie o campo no visual para "E-mail de escritório contábil?").
4. Visual **Tabela** com as colunas, nesta ordem:
   `ranking` · `faixa_prioridade` · `score` · `razao_social` · `municipio` · `dim_cnae[cnae]` · `dim_porte[porte]` · `regime_tributario` · `data_inicio_atividade` · `telefone_1` · `email` · `motivos`
   - Em `ranking`: resumo **Não resumir** e ordenação crescente.
   - Formatação condicional: `faixa_prioridade` com cor de fundo por regra (A verde, B âmbar, C cinza); `score` com **barras de dados**.
   - Renomeie as colunas no visual: Pos., Faixa, Score, Razão social, Município, CNAE, Porte, Regime, Abertura, Telefone, E-mail, Por que está nesta posição.
5. (Opcional) Cartão com `Sem contador identificado`.

> **Prints para o relatório (Requisito 2):** a lista com as primeiras posições visíveis, de preferência com a
> coluna "Por que está nesta posição" legível (dá para aumentar a largura dela e reduzir a das outras).

## 6. Atualização mensal

Quando sair a competência nova: `python run_sprint1.py --apagar-csv` → `python run_sprint3.py` → no Power BI, **Página Inicial > Atualizar**. Nada no painel precisa ser refeito.
