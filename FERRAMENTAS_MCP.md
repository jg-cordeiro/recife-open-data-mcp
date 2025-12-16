# Guia de Uso das Ferramentas MCP

## Ferramentas Disponíveis

### 1. `list_tables()` - Listar Tabelas
Quando usar: descobrir quais tabelas existem.  
Retorna: lista de tabelas com schema e nome completo.

### 2. `describe_table(table_name)` - Descrever Tabela
Quando usar: saber colunas e tipos antes de gerar SQL.  
Parâmetros: `table_name` sem schema (ex.: `situação_final_dos_alunos_por_período_letivo` ou `registro_das_infrações_de_trânsito_-_cttu`).

### 3. `search_schema(search_term)` - Buscar no Schema
Quando usar: localizar tabelas/colunas por palavra‑chave.

### 4. `list_databases()` - Listar Schemas
Geralmente retorna apenas `public`.

### 5. `execute_sql(sql)` - Executar SQL direto
Use apenas se já tiver a query pronta. Lembre de quotar nomes com hífen/acentos.

### 6. `answer_question(question)` - Responder Pergunta de Dados
Para contagens, agregações, filtros. Não usar para descobrir estrutura.

## Fluxo Recomendado
1. `list_tables()` → ver tabelas disponíveis.  
2. `describe_table("<tabela>")` → colunas exatas.  
3. `answer_question("...")` ou `execute_sql("...")` se já tiver SQL.

## Exemplos de Uso
- Listar tabelas: `list_tables()`  
- Colunas da tabela de infrações: `describe_table("registro_das_infrações_de_trânsito_-_cttu")`  
- Contagem de multas implantadas em 2024:  
  `SELECT COUNT(*) AS total FROM "public"."registro_das_infrações_de_trânsito_-_cttu" WHERE substr("dataimplantacao",1,4) = '2024';`
- Top 5 anos com mais registros de alunos:  
  `SELECT "ano", COUNT(*) AS total FROM "public"."situação_final_dos_alunos_por_período_letivo" GROUP BY "ano" ORDER BY total DESC LIMIT 5;`

## Dicas
- Sempre use `describe_table` para pegar os nomes corretos (ex.: `situacao_nome`, `ano`, `dataInfracao`, `agenteequipamento`).  
- Colunas com hífen ou acento exigem aspas duplas em SQL.  
- Consulte os dicionários via resources (`resource://dicionario-situacao-final`, `resource://dicionario-infracoes`) para confirmar nomenclatura.
