# Recife Open Data MCP

Servidor [MCP (Model Context Protocol)](https://modelcontextprotocol.io/) para consultar dados publicos abertos do Recife em linguagem natural. O servidor expoe ferramentas que permitem a qualquer cliente MCP explorar o schema de um banco DuckDB local e executar consultas SQL read-only sobre os datasets do municipio.

## Arquitetura

O projeto tem tres camadas independentes:

```
┌──────────────────────────────────────────────────────┐
│                  Clientes MCP                        │
│  (Claude Desktop, Cursor, qualquer cliente MCP)      │
└──────────────┬───────────────────────────────────────┘
               │ protocolo MCP (stdio ou HTTP/SSE)
┌──────────────▼───────────────────────────────────────┐
│            Servidor MCP (FastMCP)                     │
│                                                      │
│  Ferramentas:                                        │
│   list_tables · describe_table · search_schema       │
│   list_databases · create_sql · execute_sql          │
│                                                      │
│  Resources:                                          │
│   dicionarios de dados (JSON)                        │
│                                                      │
│  Guardrails:                                         │
│   somente SELECT/WITH/EXPLAIN · bloqueio de DDL/DML  │
└──────────────┬───────────────────────────────────────┘
               │
┌──────────────▼───────────────────────────────────────┐
│             DuckDB (banco embutido)                   │
│  ./data/recife.duckdb                                │
│                                                      │
│  Tabelas:                                            │
│   situacao_final_dos_alunos_por_periodo_letivo       │
│   registro_das_infracoes_de_transito_-_cttu          │
│   naufragios_do_recife                               │
└──────────────────────────────────────────────────────┘
```

### Servidor MCP (`server/`)

O componente principal. Um servidor FastMCP que expoe ferramentas para explorar o schema do banco e consultar dados. Pode rodar via **stdio** (protocolo MCP nativo) ou **HTTP/SSE** (FastAPI). Toda consulta SQL e validada como read-only antes da execucao.

A geracao de SQL a partir de linguagem natural e feita pelo modelo **Gemini 2.5 Flash** via OpenRouter, com um prompt que forca a exploracao previa do schema e aplica regras de seguranca.

| Arquivo | Responsabilidade |
|---|---|
| `server/main.py` | Aplicacao FastMCP com ferramentas e resources |
| `server/http_server.py` | Transporte HTTP/SSE via FastAPI |
| `server/db.py` | Interface com o DuckDB (queries, introspeccao de schema) |
| `server/openrouter_client.py` | Cliente OpenRouter para geracao de SQL via Gemini 2.5 Flash |
| `server/sql_guard.py` | Validacao de SQL (somente leitura, statement unico) |
| `server/config.py` | Configuracao via variaveis de ambiente |

### Cliente CLI (`client.py`)

Um agente interativo para testes que simula o fluxo de tool calling localmente:

1. Envia a pergunta do usuario ao Gemini 2.5 Flash via OpenRouter
2. O modelo responde com chamadas de ferramentas (`tool_calls`)
3. O cliente executa cada ferramenta chamando diretamente as funcoes Python do servidor (e.g. `server.db.list_tables()`, `server.openrouter_client.generate_sql()`)
4. Os resultados sao enviados de volta ao modelo
5. O ciclo repete ate o modelo produzir uma resposta final (maximo 10 iteracoes)

Isso permite testar o fluxo completo de tool calling sem precisar de um cliente MCP externo.

### Scripts

| Arquivo | Responsabilidade |
|---|---|
| `scripts/ingest.py` | Carga de CSVs no DuckDB a partir de descritores JSON |
| `scripts/run_eval.py` | Execucao de casos de avaliacao comparando SQL gerado com queries de referencia |

### Datasets (`datasets/`)

CSVs originais obtidos do [Portal de Dados Abertos do Recife](http://dados.recife.pe.gov.br/), rastreados via Git LFS:

| Dataset | Diretorio | Periodo |
|---|---|---|
| Situacao final dos alunos por periodo letivo | `datasets/situacao-final-estudantes/` | 2012-2024 |
| Registro das infracoes de transito (CTTU) | `datasets/registro-das-infracoes-de-transito/` | 2010-2024 |
| Naufragios do Recife | `datasets/naufragios-recife/` | -- |


### Avaliacao (`eval_cases.json`)

30 casos de teste (10 por dataset) que comparam o SQL gerado com queries de referencia. Tipos de comparacao: numerica, ranking e lista.

## Pre-requisitos

- Python 3.12+
- [Git LFS](https://git-lfs.com/) (`brew install git-lfs && git lfs install`)
- Chave do [OpenRouter](https://openrouter.ai/) com acesso ao modelo `google/gemini-2.5-flash`

## Configuracao rapida

```bash
# 1. Clone e baixe arquivos LFS
git clone https://github.com/<usuario>/recife-open-data-mcp.git
cd recife-open-data-mcp
git lfs pull

# 2. Crie o ambiente e instale dependencias
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 3. Configure variaveis de ambiente
cp .env.example .env
# Edite .env e preencha OPENROUTER_API_KEY
```

## Executando

### Servidor MCP (stdio)

```bash
python -m server.main
```

Use esse modo para conectar clientes MCP como Claude Desktop ou Cursor.

### Servidor HTTP

```bash
uvicorn server.http_server:app --reload --port 8000
```

Endpoints disponiveis em `http://localhost:8000/mcp/v1/`.

### Cliente CLI interativo

```bash
python client.py interactive
```

Comandos internos:
- `:tools` -- lista ferramentas disponiveis
- `:tables` -- lista tabelas do banco
- `:schemas` -- lista schemas
- `:describe <tabela>` -- descreve colunas de uma tabela
- `:search <termo>` -- busca tabelas/colunas por termo

## Ferramentas MCP
O servidor expoe ferramentas voltadas a duas necessidades: (i) exploracao incremental do schema e (ii) consulta de dados. A exploracao incremental evita enviar o schema completo na janela de contexto e prepara o prototipo para cenarios com multiplos bancos.

| Ferramenta | Descricao |
|---|---|
| `list_tables()` | Lista todas as tabelas com schema |
| `describe_table(table_name)` | Retorna colunas, tipos e nullability de uma tabela |
| `search_schema(search_term)` | Busca tabelas/colunas por termo |
| `list_databases()` | Lista schemas disponiveis |
| `create_sql(question, schema_context?)` | Gera SQL read-only a partir de linguagem natural via Gemini 2.5 Flash |
| `execute_sql(sql)` | Executa SQL pre-validado como somente leitura |

O racional completo das ferramentas e do system prompt esta em [`FERRAMENTAS_MCP.md`](FERRAMENTAS_MCP.md).

### Guardrails de SQL

- Somente `SELECT`, `WITH` e `EXPLAIN` sao permitidos
- Multiplos statements em uma unica query sao bloqueados
- DDL/DML (`INSERT`, `UPDATE`, `DELETE`, `DROP`, `ALTER`, `TRUNCATE`, `CREATE`, `GRANT`, `REVOKE`) sao bloqueados

### System prompt

O prompt enviado ao Gemini 2.5 Flash (em `server/openrouter_client.py`) inclui instrucoes para:

- **Forcar exploracao do schema**: o modelo deve chamar `list_tables` e `describe_table` antes de gerar qualquer SQL, evitando colunas inventadas
- **Consultar dicionarios de dados**: via MCP resources, para entender o significado dos campos
- **Usar somente nomes retornados pelas ferramentas**: reforcar vinculo com o schema real
- **Quoting obrigatorio**: nomes com acentos, hifens e espacos devem ser sempre entre aspas duplas (`"schema"."tabela"."coluna"`)
- **Regras de filtragem**: usar `LIKE`/regex para filtros categoricos, `substr`/`EXTRACT` para datas ISO, `regexp_extract` para datas em texto livre
- **Exemplos few-shot**: queries reais dos tres datasets para guiar formato e aliases

## Dados e ingestao

Os CSVs sao mantidos como vieram do portal. A carga no DuckDB e feita por descritores JSON que definem tabela e schema. Detalhes em [`INGESTAO_DATASETS.md`](INGESTAO_DATASETS.md).

```bash
# Ingestao em lote
python -m scripts.ingest batch --input-dir datasets/situacao-final-estudantes
python -m scripts.ingest batch --input-dir datasets/registro-das-infracoes-de-transito
python -m scripts.ingest batch --input-dir datasets/naufragios-recife
```

## Avaliacao

```bash
python -m scripts.run_eval --help
python -m scripts.run_eval
```

Executa os 30 casos de `eval_cases.json` e gera um relatorio Markdown em `eval_runs/`.

Cada caso:

1. Envia a pergunta ao modelo com as ferramentas disponiveis
2. O modelo explora o schema e gera SQL via tool calling
3. Executa o SQL gerado e o SQL de referencia
4. Compara os resultados (numerico, ranking ou lista)
## Variaveis de ambiente

| Variavel | Padrao | Descricao |
|---|---|---|
| `OPENROUTER_API_KEY` | (obrigatorio) | Chave de API do OpenRouter |
| `OPENROUTER_MODEL` | `google/gemini-2.5-flash` | Modelo LLM usado para geracao de SQL |
| `DUCKDB_DATA_DIR` | `./data` | Diretorio do banco DuckDB |
| `MAX_RESULT_ROWS` | `200` | Limite de linhas retornadas |
| `STATEMENT_TIMEOUT_MS` | `10000` | Timeout de execucao SQL (ms) |
| `HTTP_PORT` | `8000` | Porta do servidor HTTP |

## Documentacao complementar

Este projeto e o resultado de um **Trabalho de Conclusao de Curso (TCC)** do bacharelado em **Sistemas de Informacao** na **Universidade Federal de Pernambuco (UFPE)**.

### Resumo

Os dados abertos governamentais tem grande valor social, mas muitos cidadaos enfrentam barreiras tecnicas para acessa-los e explora-los. Este trabalho investiga a viabilidade tecnica de uma interface de consulta em linguagem natural para os dados publicos do Recife. Desenvolveu-se um prototipo funcional utilizando o protocolo Model Context Protocol (MCP) como camada de abstracao entre uma base de dados relacional local e um modelo de linguagem, responsavel por gerar consultas SQL a partir de perguntas em portugues. Realizou-se uma avaliacao exploratoria do prototipo com um conjunto de perguntas em linguagem natural aplicadas a tres conjuntos de dados reais do Recife (educacao, transito e naufragios). Os resultados indicam bom desempenho em consultas simples, enquanto consultas mais complexas revelaram desafios devido a qualidade dos dados e as variacoes de formato. Conclui-se que a solucao proposta e promissora para ampliar o acesso exploratorio de usuarios nao especialistas a dados publicos, embora sua eficacia dependa diretamente da qualidade e padronizacao das bases de dados.


## Contribuindo

Veja [`CONTRIBUTING.md`](CONTRIBUTING.md).
