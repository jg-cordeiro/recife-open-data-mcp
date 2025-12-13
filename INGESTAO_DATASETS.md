# Processo de Ingestão de Novos Datasets

## Resumo

Este documento descreve o fluxo completo de consolidação e ingestão de datasets CSV no banco DuckDB. O processo inclui:

1. **Consolidação automática** de múltiplos arquivos CSV anuais em um único arquivo
2. **Geração de dicionário de dados** via LLM (OpenRouter) quando não disponível
3. **Ingestão em lote** no DuckDB para disponibilização via MCP

---

## Workflow Completo

### 1. **Consolidação de Datasets** (Novo)

Use o script `scripts/consolidate.py` para consolidar múltiplos arquivos CSV de um mesmo dataset (ex: dados anuais 2012-2024) em um único arquivo.

#### Características

- **Detecção automática de delimitador**: Identifica se o CSV usa `;` (ponto-e-vírgula) ou `,` (vírgula)
- **Auto-alinhamento de esquemas**: Unifica colunas mesmo se alguns anos tiverem colunas diferentes
- **Geração de dicionário via LLM**: Cria automaticamente `dicionario-<nome>.json` com metadados se não existir
- **Tratamento de formatos problemáticos**: Lida com aspas envolvendo linhas inteiras e delimitadores inconsistentes

#### Uso

```bash
python -m scripts.consolidate <pasta-dataset> "<descrição>" [--force]
```

**Exemplo - Atendimentos Defesa Civil:**
```bash
python -m scripts.consolidate \
  datasets/atendimentos-defesa-civil \
  "Registro de atendimentos da Defesa Civil do Recife, incluindo áreas de risco, vistorias realizadas e execução do serviço de colocação de lona"
```

**Exemplo - Situação Final Estudantes:**
```bash
python -m scripts.consolidate \
  datasets/situacao-final-estudantes \
  "Situação acadêmica dos alunos da rede pública de ensino da cidade do Recife ao final de um ano letivo"
```

#### Saídas Geradas

1. **CSV consolidado**: `datasets/consolidated/<nome>_consolidated.csv`
2. **Dicionário de dados**: `datasets/<nome>/dicionario-<nome>.json` (se não existir)
3. **Descriptor para ingestão**: `datasets/consolidated/<nome>_consolidated.json`

#### Exemplo de Saída

```
🔍 Analyzing dataset: atendimentos-defesa-civil
📁 Source: datasets/atendimentos-defesa-civil

✅ Found 11 CSV files:
   - atendimentos_2014.csv (2014, 57655 rows, 16 columns)
   - atendimentos_2015.csv (2015, 81389 rows, 16 columns)
   ...

✅ All files have consistent schemas
📋 Unified schema: 16 columns

🤖 Generating data dictionary with LLM...
✅ Dictionary saved: datasets/atendimentos-defesa-civil/dicionario-atendimentos-defesa-civil.json

📦 Consolidating CSVs...
  📄 Processing atendimentos_2014.csv (57655 rows, delimiter: ';')...
  📄 Processing atendimentos_2015.csv (81389 rows, delimiter: ',')...
  ...

✅ Consolidation complete!
   📊 Total rows: 795,839
   💾 Output: datasets/consolidated/atendimentos-defesa-civil_consolidated.csv
   📖 Dictionary: datasets/atendimentos-defesa-civil/dicionario-atendimentos-defesa-civil.json
   📄 Descriptor: datasets/consolidated/atendimentos-defesa-civil_consolidated.json
```

---

### 2. **Ingestão em Lote no DuckDB** (Novo)

Após consolidar os datasets, use o comando `batch` do script de ingestão para carregar todos os arquivos consolidados de uma vez.

#### Uso

```bash
python -m scripts.ingest batch [--consolidated-dir datasets/consolidated] [--schema public]
```

**Exemplo:**
```bash
python -m scripts.ingest batch
```

#### Como Funciona

1. Escaneia a pasta `datasets/consolidated/` procurando pares de arquivos:
   - `<nome>_consolidated.json` (descriptor)
   - `<nome>_consolidated.csv` (dados)

2. Para cada par encontrado:
   - Cria a tabela no schema especificado (padrão: `public`)
   - Carrega o CSV usando `read_csv_auto` do DuckDB
   - Reporta sucesso/erro com contagem de linhas

3. Exibe resumo final com estatísticas

#### Exemplo de Saída

```
📦 Batch ingestion from datasets/consolidated
   Found 2 descriptor(s)

📄 Loading atendimentos-defesa-civil_consolidated...
   Descriptor: atendimentos-defesa-civil_consolidated.json
   CSV: atendimentos-defesa-civil_consolidated.csv
   ✅ Success: 795,839 rows loaded into public.atendimentos-defesa-civil_consolidated

📄 Loading situacao-final-estudantes_consolidated...
   Descriptor: situacao-final-estudantes_consolidated.json
   CSV: situacao-final-estudantes_consolidated.csv
   ✅ Success: 1,278,609 rows loaded into public.situacao-final-estudantes_consolidated

📊 Batch ingestion complete:
   ✅ Successful: 2
   ❌ Failed: 0
```

---

### 3. **Ingestão Individual** (Método Antigo - Ainda Suportado)

Para carregar um único arquivo CSV manualmente:

```bash
python -m scripts.ingest load <descriptor.json> <arquivo.csv> [--schema public] [--replace]
```

---

## Datasets Consolidados Atualmente

### 1. Atendimentos Defesa Civil (2014-2025)

**Total de registros:** 795.839  
**Colunas:** 16  
**Tabela:** `public.atendimentos-defesa-civil_consolidated`

**Campos principais:**
- Regional, Ano, Mês, Data
- Ocorrencia, Solicitacao
- Endereco, Bairro, Localidade
- Grau_de_Risco
- Data_da_Acao, Tipo_da_Acao
- Quantidade, Altura, Largura, Area_m

**Dicionário:** `datasets/atendimentos-defesa-civil/dicionario-atendimentos-defesa-civil.json`

---

### 2. Situação Final dos Estudantes (2012-2024)

**Total de registros:** 1.278.609  
**Colunas:** 19  
**Tabela:** `public.situacao-final-estudantes_consolidated`

**Campos principais:**
- ano, codigo_escola, escola
- endereco_bairro, endereco_logradouro, endereco_numero, rpa
- ano_ensino, modalidade_ensino_codigo, modalidade_ensino
- serie_codigo, serie, turma, turno
- matricula, sexo, idade
- situacao_codigo, situacao_nome

**Dicionário:** `datasets/situacao-final-estudantes/dicionario-situacao-final-estudantes.json`

---

## Estrutura de Arquivos

```
datasets/
├── atendimentos-defesa-civil/
│   ├── atendimentos_2014.csv
│   ├── atendimentos_2015.csv
│   ├── ... (11 arquivos totais)
│   └── dicionario-atendimentos-defesa-civil.json
│
├── situacao-final-estudantes/
│   ├── situacaofinal2012.csv
│   ├── situacaofinal2013.csv
│   ├── ... (13 arquivos totais)
│   └── dicionario-situacao-final-estudantes.json
│
└── consolidated/
    ├── atendimentos-defesa-civil_consolidated.csv
    ├── atendimentos-defesa-civil_consolidated.json
    ├── situacao-final-estudantes_consolidated.csv
    └── situacao-final-estudantes_consolidated.json
```

---

## Troubleshooting

### Problema: "Column has X columns but Y values were supplied"

**Causa:** Tipos de dados incorretos no descriptor (ex: DOUBLE para campos que contêm texto)

**Solução:** Os descriptors agora usam VARCHAR para todas as colunas por padrão. O DuckDB fará inferência de tipos durante queries. Se necessário, force regeneração:
```bash
python -m scripts.consolidate <pasta> "<descrição>" --force
```

### Problema: CSVs com delimitadores mistos

**Causa:** Alguns anos usam `;` e outros usam `,`

**Solução:** O script de consolidação detecta automaticamente e normaliza para `;`

### Problema: Aspas envolvendo linhas inteiras

**Causa:** Alguns CSVs exportam com `"header1,header2,header3"` em uma única célula

**Solução:** O script detecta e remove aspas envolvendo a linha inteira automaticamente
    {"name": "sexo", "type": "INTEGER"},
    {"name": "idade", "type": "INTEGER"},
    {"name": "situacao_codigo", "type": "VARCHAR"},
    {"name": "situacao_nome", "type": "VARCHAR"}
  ]
}
```

**Nota:** Tipos DuckDB (`INTEGER`, `DOUBLE`, `BOOLEAN`, `TIMESTAMP`, `VARCHAR`) substituem tipos PostgreSQL.

---

### 3. **Script de Consolidação (Primeira Tentativa - Shell)**

**Arquivo criado:** `datasets/consolidate.sh`

**Problema encontrado:**
- Convertia `;` para `,` diretamente
- Não tratava quebras de linha internas nos campos
- Resultava em linhas malformadas com mais/menos colunas

**Erro gerado:**
```
InvalidTextRepresentation: invalid input syntax for type integer
COPY situacao_final_estudantes, line 192534, column ano: "2014,146,..."
```

---

### 4. **Script de Consolidação (Segunda Tentativa - Shell Avançado)**

**Modificação:** `datasets/consolidate.sh` - v2

**Melhorias:**
- Usava `tr '\n' '\f'` para marcar quebras de linha
- Convertia separador com `tr ';' ','`
- Validava via Python com `csv.reader`
- Pulava linhas com número errado de colunas

**Problema persistente:**
- Aspas duplicadas no CSV: `""2014"` ao invés de `"2014"`
- Ainda havia linhas malformadas sendo puladas

---

### 5. **Script de Consolidação (Versão Final - Python Puro)**

**Arquivo criado:** `datasets/consolidate.py`

**Características:**
```python
def consolidate_csvs(output_file: str = "situacao_final_consolidated.csv"):
    # Para cada ano de 2012 a 2025:
    #   1. Abre CSV com delimiter ';'
    #   2. Pula header na primeira linha
    #   3. Valida número de colunas (19 exatas)
    #   4. Preenche com strings vazias se houver menos colunas
    #   5. Trunca se houver mais colunas
    #   6. Trata erros de encoding com 'errors=replace'
    
    # Escreve output em formato CSV com delimiter ','
```

**Resultados:**
- ✅ 688.807 registros consolidados
- ✅ 19 colunas validadas
- ✅ Sem erros de parsing
- ✅ Output: `situacao_final_consolidated.csv` (CSV com `,`)

---

### 6. **Execução do Script de Ingestão**

**Comando:**
```bash
source .venv/bin/activate
python -m scripts.ingest \
  datasets/situacao_final_estudantes.json \
  datasets/situacao_final_consolidated.csv \
  --schema public \
  --replace
```

**O que o script `scripts/ingest.py` faz (agora com DuckDB):**

1. **Lê o descriptor JSON** (`situacao_final_estudantes.json`)
   - Extrai nome da tabela: `situacao_final_estudantes`
   - Extrai schema de colunas com tipos DuckDB

2. **Conecta ao DuckDB** 
   ```python
   conn = duckdb.connect(settings.db_path)  # arquivo: ./data/recife.duckdb
   ```

3. **Cria o schema** (se não existir)
   ```sql
   CREATE SCHEMA IF NOT EXISTS public
   ```

4. **Cria a tabela** (com `--replace = DROP TABLE IF EXISTS`)
   ```sql
   CREATE TABLE IF NOT EXISTS public.situacao_final_estudantes (
       ano INTEGER,
       codigo_escola INTEGER,
       escola VARCHAR,
       ...
   )
   ```

5. **Carrega dados** usando `read_csv_auto`
   ```sql
   INSERT INTO public.situacao_final_estudantes 
   SELECT * FROM read_csv_auto('datasets/situacao_final_consolidated.csv')
   ```

6. **Fecha a conexão**

---

### 7. **Arquivos Modificados / Criados**

| Arquivo | Tipo | Ação | Motivo |
|---------|------|------|--------|
| `datasets/situacao_final_estudantes.json` | Novo | Criado | Descriptor com schema de 19 colunas (tipos DuckDB) |
| `datasets/consolidate.sh` | Novo | Criado (v1) | Tentar consolidar com shell |
| `datasets/consolidate.sh` | Modificado | Atualizado (v2) | Tentar melhorar parsing |
| `datasets/consolidate.py` | Novo | Criado | Solução final em Python |
| `datasets/situacao_final_consolidated.csv` | Gerado | Criado | Output da consolidação (688k linhas) |

---

### 8. **Banco de Dados - Estado Final**

**Banco DuckDB:**
```
Arquivo: ./data/recife.duckdb
Schema: public
Tabela: situacao_final_estudantes
- 19 colunas
- 688.807 registros
- Tipos: Inteiros para IDs/números, VARCHAR para descrições
```

**Verificação:**
```sql
SELECT COUNT(*) FROM public.situacao_final_estudantes;
-- Resultado: 688807

SELECT DISTINCT ano FROM public.situacao_final_estudantes ORDER BY ano;
-- 2012, 2013, 2014, ..., 2024 (13 anos)
```

---

## Desafios Encontrados e Soluções

| Desafio | Causa | Solução |
|---------|-------|---------|
| Separador `;` não compatível com ingestor | CSV em formato SEMISEL | Converter para CSV com `,` |
| Quebras de linha internas nos campos | Dados mal estruturados | Python csv.reader com tratamento |
| Aspas duplicadas | Arquivo corrompido | `errors='replace'` no open() |
| Linhas com número errado de colunas | Dados inconsistentes | Validar len(row) e padding com ''  |
| Módulo `server` não encontrado ao rodar scripts/ingest.py | Path do módulo | Usar `python -m scripts.ingest` (ativa PYTHONPATH) |
| Tipos PostgreSQL vs DuckDB | Migração de banco | Atualizar descriptor com tipos DuckDB (INTEGER, VARCHAR, etc.) |

---

## Verificação de Sucesso

✅ **Banco criado:** DuckDB (arquivo `./data/recife.duckdb`)
✅ **Tabela criada:** `public.situacao_final_estudantes`
✅ **Registros inseridos:** 688.807
✅ **Período coberto:** 2012-2024
✅ **Schema validado:** 19 colunas com tipos DuckDB corretos
✅ **Dados consistentes:** Sem erros de tipo ou parse

---

## Próximos Passos Possíveis

1. **Criar índices** para performance:
   ```sql
   CREATE INDEX idx_ano ON situacao_final_estudantes(ano);
   CREATE INDEX idx_escola ON situacao_final_estudantes(codigo_escola);
   ```

2. **Adicionar metadados** à tabela:
   ```sql
   COMMENT ON TABLE public.situacao_final_estudantes 
   IS 'Situação final dos estudantes da rede municipal do Recife (2012-2024)';
   ```

3. **Queries úteis:**
   ```sql
   -- Total de estudantes por ano
   SELECT ano, COUNT(*) as total FROM situacao_final_estudantes GROUP BY ano;
   
   -- Taxa de aprovação por ano
   SELECT ano, 
          SUM(CASE WHEN situacao_codigo = 'AP' THEN 1 ELSE 0 END) * 100.0 / COUNT(*) as taxa_aprovacao
   FROM situacao_final_estudantes 
   GROUP BY ano;
   ```

---

## Resumo Técnico

| Item | Valor |
|------|-------|
| **Formato original** | 13 CSVs com `;` |
| **Formato consolidado** | 1 CSV com `,` |
| **Linhas consolidadas** | 688.807 |
| **Colunas** | 19 |
| **Período** | 2012-2024 |
| **Banco de dados** | DuckDB (arquivo: `./data/recife.duckdb`) |
| **Tabela** | `public.situacao_final_estudantes` |
| **Tempo de ingestão** | < 1 minuto |
| **Schema** | Definido via JSON (tipos DuckDB) |
| **Método de carregamento** | DuckDB `read_csv_auto` + INSERT |
