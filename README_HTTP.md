# Recife Open Data MCP - HTTP Transport

Camada MCP em Python/FastMCP para consultar datasets públicos do Recife via linguagem natural usando **HTTP transport** em vez de stdio. Os dados são carregados em Postgres (read-only para o servidor) e expostos a um LLM via OpenRouter para gerar e executar SQL com limites e timeouts.

## 🎯 Arquitetura HTTP

- **Servidor MCP HTTP**: FastAPI rodando na porta 8000
- **Cliente HTTP**: Comunica com o servidor via HTTP REST
- **LLM (OpenRouter)**: Processa linguagem natural e faz tool calling
- **Banco de dados**: PostgreSQL com datasets do Recife

## Pré-requisitos
- Docker + Docker Compose
- Python 3.11+
- Chave de API do OpenRouter (`OPENROUTER_API_KEY`), com acesso ao modelo `openai/gpt-5.1-codex-max` (Preview)

## Configuração
1. Copie variáveis de ambiente:
   ```bash
   cp .env.example .env
   # preencha OPENROUTER_API_KEY
   ```

2. Suba o Postgres e MCP server com Docker:
   ```bash
   docker compose up -d
   ```

   Ou rode localmente:
   ```bash
   # Suba apenas o Postgres
   docker compose up -d postgres
   
   # Instale dependências
   python -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   
   # Rode o servidor HTTP MCP
   uvicorn server.http_server:app --reload --port 8000
   ```

## Ingestão de dados

Use `scripts/ingest.py` para carregar datasets a partir de um JSON de descrição e um CSV.

Exemplo de descriptor (`datasets/escolas.json`):
```json
{
  "table": "escolas",
  "description": "Escolas públicas do Recife",
  "columns": [
    {"name": "id", "type": "integer"},
    {"name": "nome", "type": "text"},
    {"name": "bairro", "type": "text"},
    {"name": "qtde_alunos", "type": "integer"}
  ]
}
```

Comando para ingerir:
```bash
python scripts/ingest.py datasets/escolas.json datasets/escolas.csv --schema public --replace
```

## Testando via HTTP

### Cliente manual
```bash
source .venv/bin/activate
python http_client.py interactive
```

### Opção 3: Testar endpoints diretamente

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

# Fazer pergunta em linguagem natural
curl -X POST http://localhost:8000/mcp/v1/tools/execute \
  -H "Content-Type: application/json" \
  -d '{
    "name": "answer_question",
    "arguments": {"question": "Quantas escolas existem?"}
  }'
```

## Endpoints HTTP MCP

### Servidor MCP (porta 8000)

- `GET /` - Health check básico
- `GET /health` - Health check detalhado (testa DB)
- `GET /mcp/v1/capabilities` - Capacidades do servidor
- `GET /mcp/v1/tools` - Lista de ferramentas disponíveis
- `POST /mcp/v1/tools/execute` - Executa uma ferramenta
- `GET /mcp/v1/resources` - Lista de recursos disponíveis
- `POST /mcp/v1/resources/read` - Lê um recurso (schema)

## Ferramentas MCP disponíveis

### 1. `execute_sql`
Executa SQL read-only com timeout e limite de linhas.

**Input:**
```json
{
  "sql": "SELECT * FROM escolas LIMIT 10"
}
```

**Output:**
```json
{
  "sql": "SELECT * FROM escolas LIMIT 10",
  "row_count": 10,
  "rows": [...]
}
```

### 2. `answer_question`
Converte pergunta em linguagem natural para SQL, executa e retorna resultado formatado.

**Input:**
```json
{
  "question": "Quantas escolas existem no dataset?"
}
```

**Output:**
```json
{
  "question": "Quantas escolas existem no dataset?",
  "sql": "SELECT COUNT(*) FROM public.escolas",
  "row_count": 1,
  "data": [{"count": 150}]
}
```

## Exemplos de perguntas

Ao usar o cliente interativo (`python http_client.py interactive`):

- "Quantas escolas existem no dataset?"
- "Qual é o bairro com mais escolas?"
- "Liste todas as escolas de Boa Viagem"
- "Qual é a escola com mais alunos?"
- "Quantos alunos há no total?"
- "Quais são as 5 escolas com mais alunos?"

## Fluxo de execução

```
1. Usuário faz pergunta em linguagem natural
   ↓
2. Cliente HTTP envia para LLM (OpenRouter)
   ↓
3. LLM decide chamar ferramenta via function calling
   ↓
4. Cliente HTTP chama endpoint do servidor MCP
   ↓
5. Servidor MCP:
   - Gera SQL com LLM (se answer_question)
   - Valida SQL (somente SELECT)
   - Adiciona LIMIT automático
   - Executa no Postgres com timeout
   - Retorna resultado formatado
   ↓
6. Cliente recebe resultado e envia de volta ao LLM
   ↓
7. LLM formata resposta final em linguagem natural
   ↓
8. Usuário recebe resposta formatada
```

## Guardrails de segurança

- **Somente SELECT/CTE**: DDL/DML são bloqueados
- **LIMIT automático**: Configurável via `MAX_RESULT_ROWS` (padrão: 200)
- **Timeout**: Configurável via `STATEMENT_TIMEOUT_MS` (padrão: 10000ms)
- **Retry com feedback**: Se SQL falhar, LLM tenta novamente com o erro

## Variáveis de ambiente

```env
# OpenRouter (obrigatório)
OPENROUTER_API_KEY=sk-or-...
OPENROUTER_MODEL=openai/gpt-5.1-codex-max

# Postgres
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=recife_open_data
POSTGRES_USER=recife
POSTGRES_PASSWORD=recife

# Servidor HTTP
HTTP_PORT=8000

# Limites de segurança
STATEMENT_TIMEOUT_MS=10000
MAX_RESULT_ROWS=200
```

## Docker Compose

O `docker-compose.yml` agora sobe:
1. **postgres**: Banco de dados PostgreSQL
2. **mcp-server**: Servidor MCP HTTP (FastAPI)

Para subir tudo:
```bash
docker compose up -d
```

Para ver logs:
```bash
docker compose logs -f mcp-server
```

## Troubleshooting

### Servidor não inicia
```bash
# Verifique se a porta 8000 está livre
lsof -i :8000

# Veja os logs
docker compose logs mcp-server
```

### Cliente não conecta
```bash
# Teste o health check
curl http://localhost:8000/health

# Se estiver usando Docker, verifique se está rodando
docker compose ps
```

### Erro de API key
```bash
# Verifique se a variável está configurada
grep OPENROUTER_API_KEY .env

# Recrie o container com a nova variável
docker compose down
docker compose up -d
```

## Diferenças da versão stdio

| Aspecto | stdio (anterior) | HTTP (atual) |
|---------|------------------|--------------|
| Comunicação | stdin/stdout | REST HTTP |
| Porta | N/A | 8000 |
| Clientes | Apenas stdio | Qualquer HTTP client |
| Deploy | Difícil | Fácil (container) |
| Debug | Complexo | Simples (curl, logs) |
| Escalabilidade | Limitada | Horizontal |

## Próximos passos

- [ ] Adicionar autenticação (API keys)
- [ ] Implementar rate limiting
- [ ] Adicionar cache de queries
- [ ] Métricas e observabilidade (Prometheus)
- [ ] Deploy em produção (Railway, Render, etc.)
