# Recife Open Data MCP

Camada MCP em Python/FastMCP para consultar datasets públicos do Recife via linguagem natural. Os dados são armazenados em um banco DuckDB embutido (arquivo local) e expostos a um LLM via OpenRouter para gerar e executar SQL com limites e guardrails.

## Pré-requisitos
- Python 3.12+
- Git LFS instalado (para baixar o `data/recife.duckdb`): `brew install git-lfs` e `git lfs install`
- Chave de API do OpenRouter (`OPENROUTER_API_KEY`), com acesso ao modelo `openai/gpt-5.1-codex-max` (Preview)

## Configuração
1. Copie variáveis de ambiente:
   ```bash
   cp .env.example .env
   # preencha OPENROUTER_API_KEY
   ```

2. Instale dependências Python (recomendado usar venv):
   ```bash
   # macOS com Homebrew
   brew install python@3.12
   /opt/homebrew/bin/python3.12 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

### Ambiente de desenvolvimento mais rápido (uv)
- Instale o gerenciador `uv` (mais rápido que pip): `curl -LsSf https://astral.sh/uv/install.sh | sh`
- Crie/ative o ambiente e sincronize as dependências em uma linha: 
  ```bash
  uv venv && source .venv/bin/activate && uv pip sync requirements.txt
  ```
- Sincronizar novamente não reinstala tudo, só aplica diffs — resolve a necessidade de refazer installs toda hora.

3. (Opcional) Configure o diretório de dados do DuckDB:
   ```bash
   export DUCKDB_DATA_DIR=./data  # padrão; cria a pasta automaticamente
   ```

## Ingestão de dados

Os CSVs não são consolidados ou alterados neste repositório. Para carregar dados no DuckDB, mantenha os arquivos originais e forneça um descriptor JSON com o esquema esperado (nome da tabela e colunas). Toda a lógica necessária para ingestão está em `scripts/ingest.py`.

### Ingestão individual

Crie um descriptor para cada CSV, apontando para os nomes e tipos das colunas. Exemplo (`datasets/escolas.json`):
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

Ingerir um arquivo:
```bash
python -m scripts.ingest load datasets/escolas.json datasets/escolas.csv --schema public --replace
```

- Se `columns` não for fornecido no JSON, o script infere os tipos a partir das primeiras linhas do CSV.
- `--replace` recria a tabela; remova a flag ou use `--replace False` para anexar.
- Tipos suportados: `INTEGER`, `DOUBLE`, `BOOLEAN`, `TIMESTAMP`, `VARCHAR`.

### Ingestão em lote

Para carregar vários arquivos de uma vez, mantenha cada par `<nome>.json` + `<nome>.csv` no mesmo diretório (por exemplo, `datasets/`). O comando abaixo varre esse diretório sem modificar os CSVs:

```bash
python -m scripts.ingest batch --input-dir datasets --schema public --replace
```

O script cria tabelas com base nos descritores e insere os dados exatamente como estão nos CSVs originais.

## Executando o servidor MCP localmente
```bash
OPENROUTER_API_KEY=... python -m server.main
```

Ou via FastAPI HTTP:
```bash
OPENROUTER_API_KEY=... uvicorn server.http_server:app --reload
```

## Ferramentas MCP Disponíveis

Para guia completo com exemplos de uso, veja [FERRAMENTAS_MCP.md](FERRAMENTAS_MCP.md).

Exposição principal (via MCP):
- `list_tables()`: lista todas as tabelas disponíveis com seus schemas.
- `describe_table(table_name)`: retorna detalhes das colunas de uma tabela específica.
- `search_schema(search_term)`: busca tabelas e colunas que correspondem a um termo.
- `list_databases()`: lista todos os schemas disponíveis no banco.
- `execute_sql(sql)`: executa SELECT com LIMIT automático.
- `answer_question(question)`: gera SQL com o LLM (dois estágios de retry), valida, executa e retorna o resultado.
- Resources: dicionários dos datasets (`resource://dicionario-situacao-final`, `resource://dicionario-infracoes`, `resource://dicionario-naufragios`).

**Recomendação:** Sempre use `list_tables()` e, em seguida, `describe_table("<tabela>")` antes de gerar SQL para garantir que a LLM use nomes exatos (há hífens, acentos e espaços em colunas como `historia detalhada`).

Guardrails:
- Somente SELECT/WITH/EXPLAIN são aceitos; DDL/DML são bloqueados.
- `LIMIT` automático (configurável via `MAX_RESULT_ROWS`).
- Sem timeout por statement (DuckDB executa rapidamente localmente).

## Testando interativamente (CLI)
Cliente interativo usando OpenRouter para fazer perguntas em linguagem natural:

Ou manualmente:
```bash
source .venv/bin/activate
python client.py interactive
```

Exemplos de perguntas:
- "Quantos registros de alunos há em 2024?"
- "Quais são os 5 códigos de infração mais comuns?"
- "Liste 3 naufrágios com profundidade máxima informada"

## Uso com clientes MCP / FastMCP Cloud
- Endpoint/entrypoint: `server/main.py`.
- Variáveis obrigatórias: `OPENROUTER_API_KEY`. O modelo padrão é `OPENROUTER_MODEL=openai/gpt-5.1-codex-max`.
- O arquivo DuckDB é armazenado localmente (variável `DUCKDB_DATA_DIR`), permitindo persistência mesmo em restarts.

## Troubleshooting
- DuckDB não inicializa: verifique se o diretório `./data` existe e tem permissões de escrita.
- LLM falhou ou devolveu SQL inválido: `answer_question` faz retry com o erro; revise schema e dados.
- Ingestão falha: confirme que o CSV está bem-formado e os tipos no descriptor são válidos para DuckDB.
- Banco cresce muito: dados em DuckDB são comprimidos automaticamente; considere arquivar datasets antigos em volumes separados.
