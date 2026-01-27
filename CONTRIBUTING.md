# Contribuindo

Obrigado pelo interesse em contribuir com o **Recife Open Data MCP**! Este guia explica como participar do desenvolvimento.

## Pre-requisitos

- Python 3.12+
- [Git LFS](https://git-lfs.com/) instalado (`brew install git-lfs && git lfs install`)
- Chave de API do [OpenRouter](https://openrouter.ai/) com acesso ao modelo `google/gemini-2.5-flash`

## Configurando o ambiente

```bash
# 1. Clone o repositorio
git clone https://github.com/<seu-usuario>/recife-open-data-mcp.git
cd recife-open-data-mcp

# 2. Instale o Git LFS e baixe arquivos grandes
git lfs install
git lfs pull

# 3. Crie o ambiente virtual
python3.12 -m venv .venv
source .venv/bin/activate

# 4. Instale dependencias
pip install -r requirements.txt

# 5. Configure variaveis de ambiente
cp .env.example .env
# Edite .env e preencha OPENROUTER_API_KEY
```

## Estrutura do projeto

Antes de contribuir, familiarize-se com a arquitetura descrita no [README](README.md). Os principais pontos de entrada sao:

| Componente | Caminho | Descricao |
|---|---|---|
| Servidor MCP (stdio) | `server/main.py` | Ferramentas expostas via protocolo MCP |
| Servidor HTTP | `server/http_server.py` | Mesmas ferramentas via REST/SSE |
| Cliente CLI | `client.py` | Agente interativo que simula tool calling |
| Ingestao | `scripts/ingest.py` | Carga de CSVs no DuckDB |
| Avaliacao | `scripts/run_eval.py` | Execucao de casos de teste |

## Como contribuir

### 1. Abra uma issue primeiro

Antes de comecar a trabalhar em algo, abra uma issue descrevendo o que pretende fazer. Isso evita esforco duplicado e permite discutir a abordagem.

### 2. Crie um branch

```bash
git checkout -b feat/descricao-curta
```

Use prefixos:
- `feat/` para novas funcionalidades
- `fix/` para correcoes de bugs
- `docs/` para documentacao
- `refactor/` para refatoracao sem mudanca funcional

### 3. Faca suas alteracoes

- Mantenha o codigo consistente com o estilo existente
- Adicione ou atualize casos de avaliacao em `eval_cases.json` se sua mudanca afetar a geracao de SQL
- Teste manualmente com `python client.py interactive`
- Se adicionar um novo dataset, inclua o descritor JSON e atualize o script de ingestao

### 4. Rode os evals

```bash
python -m scripts.run_eval
```

Verifique que os casos existentes continuam passando.

### 5. Abra um Pull Request

- Descreva claramente o que foi alterado e por que
- Referencie a issue relacionada
- Inclua exemplos de uso se aplicavel

## Adicionando novos datasets

1. Obtenha os CSVs e o descritor JSON do [Portal de Dados Abertos do Recife](http://dados.recife.pe.gov.br/)
2. Coloque os arquivos em `datasets/<nome-do-dataset>/`
3. Crie um dicionario de dados em `resources/`
4. Rode a ingestao: `python -m scripts.ingest batch --input-dir datasets/<nome-do-dataset>`
5. Adicione casos de avaliacao em `eval_cases.json`
6. Registre o novo resource no servidor (`server/main.py`)

## Diretrizes de codigo

- **Modelo LLM**: o projeto usa `google/gemini-2.5-flash` via OpenRouter. Nao adicione dependencias diretas de outros provedores de LLM
- **SQL seguro**: todo SQL gerado deve passar pelos guardrails em `server/sql_guard.py` (somente SELECT/WITH/EXPLAIN)
- **DuckDB**: use a sintaxe DuckDB. Evite funcoes especificas de outros bancos
- **Idioma**: codigo e comentarios em ingles; documentacao em portugues

## Licenca

Ao contribuir, voce concorda que suas contribuicoes serao licenciadas sob a [Licenca MIT](LICENSE) do projeto.
