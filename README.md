# Recife Open Data MCP

Camada MCP em Python/FastMCP para consultar datasets públicos do Recife via linguagem natural. Os dados são armazenados em um banco DuckDB embutido (arquivo local) e expostos a um LLM via OpenRouter para gerar e executar SQL com limites e guardrails.

## Pré-requisitos
- Docker + Docker Compose (opcional, para deploy containerizado)
- Python 3.11+
- Chave de API do OpenRouter (`OPENROUTER_API_KEY`), com acesso ao modelo `openai/gpt-5.1-codex-max` (Preview)

## Configuração
1. Copie variáveis de ambiente:
   ```bash
   cp .env.example .env
   # preencha OPENROUTER_API_KEY
   ```

2. Instale dependências Python (recomendado usar venv):
   ```bash
   python -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

3. (Opcional) Configure o diretório de dados do DuckDB:
   ```bash
   export DUCKDB_DATA_DIR=./data  # padrão; cria a pasta automaticamente
   ```

## Ingestão de dados

### Fluxo Recomendado: Consolidação + Ingestão em Lote

O projeto inclui um workflow automatizado para consolidar múltiplos arquivos CSV (ex: dados anuais) e carregá-los no DuckDB.

#### 1. Consolidar Datasets

Use `scripts/consolidate.py` para unificar múltiplos CSVs em um único arquivo:

```bash
python -m scripts.consolidate <pasta-dataset> "<descrição-breve>"
```

**Exemplo:**
```bash
python -m scripts.consolidate \
  datasets/atendimentos-defesa-civil \
  "Registro de atendimentos da Defesa Civil do Recife"
```

O script irá:
- Detectar automaticamente o delimitador (`;` ou `,`)
- Unificar esquemas mesmo com colunas diferentes entre anos
- Gerar dicionário de dados via LLM se não existir
- Criar arquivo consolidado em `datasets/consolidated/`

#### 2. Ingestão em Lote

Carregue todos os datasets consolidados de uma vez:

```bash
python -m scripts.ingest batch
```

Isso escaneia `datasets/consolidated/` e carrega todos os pares `*.json` + `*.csv` no DuckDB.

**Saída esperada:**
```
📦 Batch ingestion from datasets/consolidated
   Found 2 descriptor(s)

📄 Loading atendimentos-defesa-civil_consolidated...
   ✅ Success: 795,839 rows loaded

📄 Loading situacao-final-estudantes_consolidated...
   ✅ Success: 1,278,609 rows loaded

📊 Batch ingestion complete:
   ✅ Successful: 2
   ❌ Failed: 0
```

### Ingestão Individual (Método Alternativo)

Para carregar um único CSV manualmente, use `scripts/ingest.py`:

Exemplo de descriptor (`datasets/escolas.json`):
```json
{
  "table": "escolas",
  "description": "Escolas públicas do Recife",
  "columns": [
    {"name": "id", "type": "INTEGER"},
    {"name": "nome", "type": "VARCHAR"},
    {"name": "bairro", "type": "VARCHAR"},
    {"name": "qtde_alunos", "type": "INTEGER"}
  ]
}
```

Comando para ingerir:
```bash
python -m scripts.ingest load datasets/escolas.json datasets/escolas.csv --schema public --replace
```

- Se `columns` não for fornecido no JSON, o script infere tipos a partir das primeiras linhas do CSV.
- `--replace` recria a tabela; remova a flag ou use `--replace False` para anexar.
- Tipos suportados: `INTEGER`, `DOUBLE`, `BOOLEAN`, `TIMESTAMP`, `VARCHAR`.

## Executando o servidor MCP localmente
```bash
OPENROUTER_API_KEY=... python -m server.main
```

Ou via FastAPI HTTP:
```bash
OPENROUTER_API_KEY=... uvicorn server.http_server:app --reload
```

Exposição principal (via MCP):
- `schema_snapshot` (resource): entrega esquema completo.
- `execute_sql(sql)`: executa SELECT com LIMIT automático.
- `answer_question(question)`: gera SQL com o LLM (dois estágios de retry), valida, executa e retorna o resultado.

Guardrails:
- Somente SELECT/WITH/EXPLAIN são aceitos; DDL/DML são bloqueados.
- `LIMIT` automático (configurável via `MAX_RESULT_ROWS`).
- Sem timeout por statement (DuckDB executa rapidamente localmente).

## Executando com Docker
```bash
docker compose up -d
# Servidor disponível em http://localhost:8000
```

## Testando interativamente (CLI)
Cliente interativo usando OpenRouter para fazer perguntas em linguagem natural:

```bash
# Configure OPENROUTER_API_KEY em .env primeiro
./test.sh
```

Ou manualmente:
```bash
source .venv/bin/activate
python client.py interactive
```

Exemplos de perguntas:
- "Quantas escolas existem no dataset?"
- "Qual é o bairro com mais escolas?"
- "Liste todas as escolas de Boa Viagem"
- "Qual é a escola com mais alunos?"

## Uso com clientes MCP / FastMCP Cloud
- Endpoint/entrypoint: `server/main.py`.
- Variáveis obrigatórias: `OPENROUTER_API_KEY`. O modelo padrão é `OPENROUTER_MODEL=openai/gpt-5.1-codex-max`.
- O arquivo DuckDB é armazenado localmente (variável `DUCKDB_DATA_DIR`), permitindo persistência mesmo em restarts.

## Troubleshooting
- DuckDB não inicializa: verifique se o diretório `./data` existe e tem permissões de escrita.
- LLM falhou ou devolveu SQL inválido: `answer_question` faz retry com o erro; revise schema e dados.
- Ingestão falha: confirme que o CSV está bem-formado e os tipos no descriptor são válidos para DuckDB.
- Banco cresce muito: dados em DuckDB são comprimidos automaticamente; considere arquivar datasets antigos em volumes separados.
