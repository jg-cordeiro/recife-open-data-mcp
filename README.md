# Recife Open Data MCP

Protótipo para consultar dados públicos do Recife em linguagem natural usando MCP como camada de orquestração. A implementação realizada materializa um protótipo funcional para consulta a dados públicos abertos do município do Recife a partir de linguagem natural, utilizando um servidor MCP como camada de abstração entre (i) um repositório local de dados estruturados em banco relacional e (ii) um cliente que orquestra chamadas a um modelo de linguagem para geração de consultas SQL e leitura dos resultados. A escolha do MCP como protocolo busca padronizar o acesso a dados estruturados por modelos de linguagem, reduzindo a necessidade de integrações ad hoc entre cada fonte de dados e cada aplicação cliente.

## Arquitetura do protótipo
- **Dados**: arquivos CSV do portal de dados abertos são carregados em um DuckDB local (`./data/recife.duckdb`), preservando a estrutura original (detalhes em `INGESTAO_DATASETS.md`).
- **Camada MCP (FastMCP)**: expõe ferramentas para explorar o schema, executar SQL direto e gerar SQL via LLM com guardrails. A versão HTTP usa FastAPI/uvicorn; o mesmo app roda via stdio.
- **Cliente/LLM**: perguntas em linguagem natural são enviadas ao OpenRouter (`openai/gpt-5.1-codex-max`) com um prompt que força exploração prévia do schema e checagens de segurança.
- **Observabilidade**: Braintrust registra chamadas LLM e spans de ingestão/consulta (ver `OBSERVABILITY.md`).
- **Avaliação**: `scripts/run_eval.py` executa casos de teste (`eval_cases.json`) comparando o SQL gerado com queries de referência.

## Pré-requisitos e dependências principais
- Python 3.12+ e Git LFS (para baixar `data/recife.duckdb`): `brew install python@3.12 git-lfs && git lfs install`
- Chave do OpenRouter (`OPENROUTER_API_KEY`) com acesso ao modelo `openai/gpt-5.1-codex-max` (Preview)
- Bibliotecas centrais: FastMCP/FastAPI, DuckDB, OpenAI SDK, Typer (CLIs), Braintrust (observabilidade)

## Configuração rápida
1. Copie variáveis de ambiente:
   ```bash
   cp .env.example .env
   # preencha OPENROUTER_API_KEY (e opcionalmente BRAINTRUST_API_KEY)
   ```
2. Crie o ambiente e instale dependências:
   ```bash
   /opt/homebrew/bin/python3.12 -m venv .venv  # ajuste o caminho conforme seu sistema
   source .venv/bin/activate
   pip install -r requirements.txt
   ```
   Dica: `uv venv && source .venv/bin/activate && uv pip sync requirements.txt` acelera o setup.
3. (Opcional) Configure onde o DuckDB será salvo:
   ```bash
   export DUCKDB_DATA_DIR=./data  # padrão; criado automaticamente
   ```

## Executando o servidor MCP
- **Stdio (FastMCP)**:
  ```bash
  OPENROUTER_API_KEY=... python -m server.main
  ```
- **HTTP (FastAPI/uvicorn)**:
  ```bash
  OPENROUTER_API_KEY=... uvicorn server.http_server:app --reload --port 8000
  ```
- **Clientes de teste**:
  - MCP interativo (stdio): `python client.py interactive`
  - MCP via HTTP: `python http_client.py interactive`

Endpoints HTTP MCP principais: `GET /health`, `GET /mcp/v1/tools`, `POST /mcp/v1/tools/execute`, `GET /mcp/v1/resources`.

## Dados e ingestão
Os CSVs são mantidos exatamente como vieram do portal, e a carga é feita por descritores JSON que definem tabela/esquema. A agregação por dataset junta múltiplos CSVs homogêneos em uma tabela única para permitir consultas longitudinais sem remodelagens profundas. O script `scripts/ingest.py` suporta ingestão individual ou em lote; detalhes e critérios estão em `INGESTAO_DATASETS.md`.

## Ferramentas MCP e prompt
O servidor expõe um conjunto enxuto de ferramentas para explorar schema e consultar dados (`list_tables`, `describe_table`, `search_schema`, `list_databases`, `execute_sql`) e dicionários de dados via resources. O prompt do LLM obriga a explorar tabelas/colunas antes de gerar SQL e aplica regras de segurança/quoting; o racional completo está em `FERRAMENTAS_MCP.md`.

## Testes e evals
Casos de avaliação em `eval_cases.json` são executados por `python -m scripts.run_eval --help`. Cada caso compara o SQL gerado e as linhas retornadas com uma query de referência, produzindo um relatório Markdown em `eval_runs/`. Use o DuckDB local com os dados já ingeridos antes de rodar os evals.

## Observabilidade
Braintrust coleta spans de geração/execução de SQL (servidor MCP e clientes). Adicione `BRAINTRUST_API_KEY` no `.env` para ativar; consulte `OBSERVABILITY.md` para escopo e métricas.

## Documentação complementar
- `INGESTAO_DATASETS.md`: ingestão e organização do banco (princípios, estratégia de agregação, escolha do DuckDB)
- `FERRAMENTAS_MCP.md`: implementação do servidor MCP, ferramentas disponíveis e detalhamento do system prompt
- `OBSERVABILITY.md`: monitoramento de chamadas LLM e spans de consulta
