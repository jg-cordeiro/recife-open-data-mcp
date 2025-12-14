# Recife Open Data MCP - HTTP Transport

Camada MCP em Python/FastMCP para consultar datasets públicos do Recife via linguagem natural usando **HTTP transport** em vez de stdio. Os dados são armazenados em um banco DuckDB embutido (arquivo local) e expostos a um LLM via OpenRouter para gerar e executar SQL com limites e guardrails.

## Arquitetura HTTP
- **Servidor MCP HTTP**: FastAPI rodando na porta 8000 (por padrão)
- **Cliente HTTP**: comunica com o servidor via REST
- **LLM (OpenRouter)**: processa linguagem natural e faz tool calling
- **Banco de dados**: DuckDB local (`./data/recife.duckdb` por padrão)

## Pré-requisitos
- Python 3.12+
- Chave de API do OpenRouter (`OPENROUTER_API_KEY`) com acesso ao modelo `openai/gpt-5.1-codex-max` (Preview)

## Configuração rápida
1. Copie as variáveis de ambiente:
   ```bash
   cp .env.example .env
   # preencha OPENROUTER_API_KEY
   ```
2. Crie/ative o ambiente virtual e instale dependências:
   ```bash
   /opt/homebrew/bin/python3.12 -m venv .venv  # ajuste o caminho conforme seu sistema
   source .venv/bin/activate
   pip install -r requirements.txt
   ```
   > Dica: `uv venv && source .venv/bin/activate && uv pip sync requirements.txt` acelera o setup.
3. (Opcional) Altere onde o arquivo DuckDB será salvo:
   ```bash
   export DUCKDB_DATA_DIR=./data  # padrão
   ```
4. Inicie o servidor HTTP:
   ```bash
   OPENROUTER_API_KEY=... uvicorn server.http_server:app --reload --port 8000
   ```

## Ingestão de dados
Use `scripts/ingest.py` para carregar datasets a partir de um JSON de descrição e um CSV.

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

Comando para ingerir um arquivo:
```bash
python -m scripts.ingest load datasets/escolas.json datasets/escolas.csv --schema public --replace
```

Ingestão em lote no diretório `datasets/` (procura pares `<nome>.json` + `<nome>.csv`):
```bash
python -m scripts.ingest batch --input-dir datasets --schema public --replace
```

## Testando via HTTP

### Cliente manual
```bash
source .venv/bin/activate
python http_client.py interactive
```

### Curl direto
```bash
# Health check
curl http://localhost:8000/health

# Listar ferramentas disponíveis
curl http://localhost:8000/mcp/v1/tools

# Executar SQL diretamente
curl -X POST http://localhost:8000/mcp/v1/tools/execute \
  -H "Content-Type: application/json" \
  -d '{
    "name": "execute_sql",
    "arguments": {"sql": "SELECT COUNT(*) FROM escolas"}
  }'

# Pergunta em linguagem natural
curl -X POST http://localhost:8000/mcp/v1/tools/execute \
  -H "Content-Type: application/json" \
  -d '{
    "name": "answer_question",
    "arguments": {"question": "Quantas escolas existem?"}
  }'
```

## Endpoints HTTP MCP
- `GET /` - health check básico
- `GET /health` - health check detalhado (testa DB)
- `GET /mcp/v1/capabilities` - capacidades do servidor
- `GET /mcp/v1/tools` - lista ferramentas disponíveis
- `POST /mcp/v1/tools/execute` - executa uma ferramenta
- `GET /mcp/v1/resources` - lista recursos disponíveis
- `POST /mcp/v1/resources/read` - lê um recurso (schema)

## Ferramentas MCP disponíveis
1. `execute_sql`: executa SQL read-only com limite automático de linhas.
2. `answer_question`: converte pergunta em SQL seguro, executa e retorna resultado formatado.

## Variáveis de ambiente
```env
OPENROUTER_API_KEY=sk-or-...
OPENROUTER_MODEL=openai/gpt-5.1-codex-max

# Caminho do banco (opcional)
DUCKDB_DATA_DIR=./data

# Servidor HTTP
HTTP_PORT=8000
MAX_RESULT_ROWS=200
```

## Troubleshooting rápido
- Verifique se a porta 8000 está livre: `lsof -i :8000`
- Confirme se o arquivo DuckDB existe: `ls -lh ${DUCKDB_DATA_DIR:-./data}`
- Logs do servidor (rodando com `--reload`): veja o terminal em que o `uvicorn` está ativo

