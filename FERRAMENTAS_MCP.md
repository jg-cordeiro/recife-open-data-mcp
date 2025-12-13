# Guia de Uso das Ferramentas MCP

## Ferramentas Disponíveis

### 1. `list_tables()` - Listar Tabelas
**Quando usar:**
- "Quais tabelas temos disponíveis?"
- "Que dados existem no banco?"
- "Mostre todas as tabelas"

**Retorna:** Lista de tabelas com schema e nome completo quotado

**Exemplo de saída:**
```json
[
  {
    "schema": "public",
    "table": "atendimentos-defesa-civil_consolidated",
    "full_name": "\"public\".\"atendimentos-defesa-civil_consolidated\""
  }
]
```

---

### 2. `describe_table(table_name)` - Descrever Tabela
**Quando usar:**
- "Quais colunas tem a tabela X?"
- "Qual é a estrutura da tabela Y?"
- "Mostre os campos da tabela Z"

**Parâmetros:**
- `table_name`: Nome da tabela SEM schema (ex: "atendimentos-defesa-civil_consolidated")

**Retorna:** Lista de colunas com tipo e nullable

**Exemplo de saída:**
```json
[
  {"column": "Regional", "type": "VARCHAR", "nullable": "YES"},
  {"column": "Ano", "type": "VARCHAR", "nullable": "YES"},
  {"column": "Bairro", "type": "VARCHAR", "nullable": "YES"}
]
```

---

### 3. `search_schema(search_term)` - Buscar no Schema
**Quando usar:**
- "Onde encontro dados sobre 'ano'?"
- "Quais colunas têm informação de 'bairro'?"
- "Procurar por 'defesa'"

**Parâmetros:**
- `search_term`: Termo de busca (case-insensitive)

**Retorna:** Tabelas e colunas que correspondem ao termo

**Exemplo de saída:**
```json
[
  {
    "schema": "public",
    "table": "atendimentos-defesa-civil_consolidated",
    "column": "Ano",
    "type": "VARCHAR",
    "full_reference": "\"public\".\"atendimentos-defesa-civil_consolidated\".\"Ano\""
  }
]
```

---

### 4. `list_databases()` - Listar Schemas
**Quando usar:**
- "Quais schemas existem?"
- "Listar databases"

**Retorna:** Lista de schemas (geralmente apenas "public")

**Exemplo de saída:**
```json
["public"]
```

---

### 5. `execute_sql(sql)` - Executar SQL Direto
**Quando usar:**
- Você já tem uma query SQL pronta
- Está testando uma query específica

**Parâmetros:**
- `sql`: Query SQL completa

**⚠️ Importante:** Use aspas duplas para tabelas/colunas com hífens ou caracteres especiais!

**Exemplo:**
```sql
SELECT COUNT(*) FROM "public"."atendimentos-defesa-civil_consolidated"
```

---

### 6. `answer_question(question)` - Responder Pergunta
**Quando usar:**
- Perguntas analíticas sobre os DADOS (não sobre estrutura)
- Agregações, filtros, joins
- "Quantos registros..."
- "Qual é o total de..."
- "Liste os top 10..."

**❌ NÃO usar para:**
- "Quais tabelas existem?" → Use `list_tables()`
- "Que colunas tem a tabela X?" → Use `describe_table()`
- "Onde encontro dados de Y?" → Use `search_schema()`

**Parâmetros:**
- `question`: Pergunta em linguagem natural

**Processo:**
1. Gera SQL automaticamente
2. Adiciona proper quoting
3. Valida segurança
4. Executa
5. Retry automático se falhar

**Exemplo de perguntas válidas:**
- "Quantos anos diferentes temos de dados da defesa civil?"
- "Qual bairro tem mais atendimentos?"
- "Mostre os 10 tipos de ocorrência mais comuns"

---

## Fluxo Recomendado

### Para questões sobre dados:

```
1. list_tables() → ver quais tabelas existem
2. describe_table("nome-tabela") → ver colunas disponíveis
3. answer_question("sua pergunta") → obter resposta
```

### Para exploração:

```
1. search_schema("termo") → encontrar onde está a informação
2. describe_table("tabela-encontrada") → ver estrutura completa
3. answer_question("pergunta específica") → análise dos dados
```

---

## Exemplos de Uso

### Exemplo 1: Descobrir estrutura
```
User: "Quais tabelas temos disponíveis?"
→ Chama: list_tables()

User: "Que colunas tem a tabela de defesa civil?"
→ Chama: describe_table("atendimentos-defesa-civil_consolidated")
```

### Exemplo 2: Análise de dados
```
User: "Quantos anos diferentes temos de dados da defesa civil?"
→ Chama: answer_question("Quantos anos diferentes temos de dados da defesa civil?")
→ Gera SQL: SELECT COUNT(DISTINCT "Ano") FROM "public"."atendimentos-defesa-civil_consolidated"
```

### Exemplo 3: Busca e análise
```
User: "Onde encontro informação sobre anos?"
→ Chama: search_schema("ano")

User: "Quantos registros temos por ano?"
→ Chama: answer_question("Quantos registros temos por ano na defesa civil?")
```

---

## Troubleshooting

### Problema: Query falhando com "syntax error at or near -"
**Causa:** Tabela/coluna com hífen não está com aspas duplas
**Solução:** O `answer_question` já faz isso automaticamente! Use-o ao invés de `execute_sql` manual.

### Problema: LLM escolhe ferramenta errada
**Causa:** Pergunta ambígua
**Solução:** Seja mais específico:
- ❌ "Me fale sobre as tabelas" (ambíguo)
- ✅ "Liste as tabelas disponíveis" (claro → list_tables)
- ✅ "Quantos registros tem na tabela?" (claro → answer_question)

### Problema: Não encontra coluna
**Causa:** Nome da coluna pode ter capitalização diferente
**Solução:** Use `search_schema("termo")` para encontrar o nome exato
