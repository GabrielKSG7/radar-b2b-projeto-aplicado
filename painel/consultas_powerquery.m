// ============================================================================
// Radar B2B — consultas do Power Query (Power BI Desktop)
// 1) Página Inicial > Transformar dados > Gerenciar Parâmetros > Novo:
//      Nome: PastaGold | Tipo: Texto | Valor atual:
//      G:\XP\PA\SPRINTS\SPRINT 1 - SP105 - Postagem da Sprint 1\radar-b2b\data\gold\
//    (com a barra \ no final)
// 2) Para cada tabela: Nova Fonte > Consulta Nula > Editor Avançado > cole o bloco
//    > renomeie a consulta com o nome indicado.
// O Parquet já traz os tipos (data, número, verdadeiro/falso): não precisa "Alterar tipo".
// ============================================================================

// ---- consulta: fct_estabelecimentos ----
let
    Fonte = Parquet.Document(File.Contents(PastaGold & "fct_estabelecimentos.parquet"))
in
    Fonte

// ---- consulta: dim_municipio ----
let
    Fonte = Parquet.Document(File.Contents(PastaGold & "dim_municipio.parquet"))
in
    Fonte

// ---- consulta: dim_cnae ----
let
    Fonte = Parquet.Document(File.Contents(PastaGold & "dim_cnae.parquet"))
in
    Fonte

// ---- consulta: dim_porte ----
let
    Fonte = Parquet.Document(File.Contents(PastaGold & "dim_porte.parquet"))
in
    Fonte

// ---- consulta: dim_calendario ----
let
    Fonte = Parquet.Document(File.Contents(PastaGold & "dim_calendario.parquet"))
in
    Fonte
