# Recife Open Data MCP

Camada MCP em Python/FastMCP para consultar datasets públicos do Recife via linguagem natural. Os dados são carregados em Postgres (read-only para o servidor) e expostos a um LLM via OpenRouter para gerar e executar SQL com limites e timeouts.

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
2. Suba o Postgres local:
   ```bash
   docker compose up -d
   ```
3. Instale dependências Python (recomendado usar venv):
   ```bash
   python -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

## Ingestão de dados (hot reload)
Use `scripts/ingest.py` para carregar datasets a partir de um JSON de descrição e um CSV. Reexecute o comando sempre que houver novo arquivo para hot reload.

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

- Se `columns` não for fornecido no JSON, o script infere tipos a partir das primeiras linhas do CSV.
- `--replace` recria a tabela; remova a flag ou use `--replace False` para anexar.

## Executando o servidor MCP localmente
```bash
OPENROUTER_API_KEY=... python -m server.main
```

Exposição principal (via MCP):
- `schema_snapshot` (resource): entrega esquema completo.
- `execute_sql(sql)`: executa SELECT com timeout e LIMIT automáticos.
- `answer_question(question)`: gera SQL com o LLM (dois estágios de retry), valida, executa e retorna o resultado.

Guardrails:
- Somente SELECT/CTE são aceitos; DDL/DML são bloqueados.
- `LIMIT` automático (configurável via `MAX_RESULT_ROWS`).
- `statement_timeout` configurável via `STATEMENT_TIMEOUT_MS`.

## Uso com clientes MCP / FastMCP Cloud
- Endpoint/entrypoint: `server/main.py`.
- Variáveis obrigatórias: `OPENROUTER_API_KEY`. O modelo padrão é `OPENROUTER_MODEL=openai/gpt-5.1-codex-max`.
- Ao implantar no FastMCP Cloud, aponte para este entrypoint e replique as variáveis de ambiente do `.env` (exceto credenciais locais de Postgres, que devem apontar para o banco gerenciado de produção se houver).

## Exemplo de pergunta
Pergunta: "Quantas escolas existem no dataset?"  
Fluxo: cliente MCP -> `schema_snapshot` -> LLM gera SQL `SELECT COUNT(*) FROM public.escolas LIMIT 1;` -> `answer_question` executa e devolve o total.

## Troubleshooting
- Postgres não sobe: verifique portas/arquivos de dados (`docker compose logs postgres`).
- LLM falhou ou devolveu SQL inválido: `answer_question` faz retry com o erro; revise schema e dados. Ajuste `STATEMENT_TIMEOUT_MS` ou `MAX_RESULT_ROWS` se necessário.
- Ingestão lenta: mantenha índices para consultas específicas após o load inicial, se precisar de performance adicional.
