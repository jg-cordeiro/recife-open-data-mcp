# Servidor MCP, Ferramentas e System Prompt

## Implementação e abordagem
O servidor MCP foi implementado a partir de uma instância do FastMCP, com um conjunto enxuto de ferramentas voltadas a duas necessidades: (i) exploração do schema (descobrir tabelas/colunas) e (ii) consulta de dados (executar SQL diretamente ou gerar SQL a partir de linguagem natural). Toda execução de SQL passa por uma rotina central (_run_sql) que valida a query, garante que seja read-only (SELECT/WITH/EXPLAIN) e aplica limites de segurança antes de consultar o banco.

Em vez de disponibilizar a estrutura completa do banco como recurso de contexto único, a exploração é feita de forma incremental via ferramentas. Essa decisão evita janelas de contexto grandes e prepara o protótipo para cenários com múltiplos bancos ou domínios heterogêneos. O fluxo típico é: listar tabelas → descrever colunas → gerar/executar SQL → obter resultados.

## Ferramentas expostas
- `list_tables()`: lista tabelas disponíveis com schema.
- `describe_table(table_name)`: retorna colunas/tipos de uma tabela específica.
- `search_schema(search_term)`: busca tabelas/colunas por termo.
- `list_databases()`: lista schemas (geralmente apenas `public`).
- `execute_sql(sql)`: executa SQL read-only com limite automático.
- `answer_question(question)`: gera SQL via LLM, valida e executa com retry.
- Resources: dicionários de dados para consulta contextual (`resource://dicionario-situacao-final`, `resource://dicionario-infracoes`, `resource://dicionario-naufragios`).

Guardrails principais: bloqueio de DDL/DML, `LIMIT` aplicado automaticamente, quoting obrigatório para nomes com acentos/hífens e validação de colunas/tabelas via ferramentas.

## System prompt (racional linha a linha)
O prompt enviado ao LLM (ver `server/openrouter_client.py`) inclui instruções explícitas para reduzir alucinações e proteger o banco. Principais linhas e seus motivos:
- **"You are a SQL expert... DuckDB"**: ancora o modelo no dialeto e domínio esperado.
- **"Always call list_tables... REQUIRED describe_table"**: força descoberta de nomes reais antes de escrever SQL, evitando colunas inventadas.
- **"consultar dataset dictionaries via resources"**: oferece contexto sem enviar todo o schema, mantendo a janela pequena.
- **"Use ONLY names returned by the tools"**: reforça vínculo com o schema efetivo.
- **Regras de filtragem (casing, regex para ano, profundidade)**: tratam nuances específicas dos datasets e reduzem retries desnecessários.
- **"Never mutate data" / "Do NOT add LIMIT automaticamente"**: garante operações só de leitura e evita truncar resultados quando não solicitado.
- **Quoting obrigatório (schema/tabela/coluna)**: endereça caracteres especiais (acentos, hífens, espaços) presentes nos nomes originais.
- **Exemplos reais de SQL**: servem de few-shot para guiar formato e aliases consistentes.
- **"If a column error occurs, STOP and call describe_table"**: instrui o modelo a corrigir erros consultando o schema, não chutando nomes.

Essa combinação de ferramentas + prompt obriga o cliente a explorar o esquema de forma incremental, reduz ambiguidade em cenários com múltiplos datasets e facilita auditar cada decisão durante os experimentos.
