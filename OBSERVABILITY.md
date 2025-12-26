# Observabilidade com Braintrust

Este projeto usa [Braintrust](https://www.braintrustdata.com/) para observabilidade e monitoramento de **todas** as chamadas LLM.

## Configuração

1. Obtenha uma API key do Braintrust em https://www.braintrustdata.com/
2. Adicione a chave no arquivo `.env`:

```bash
BRAINTRUST_API_KEY=sk-your-api-key-here
```

## O que está sendo monitorado

### 1. Geração de SQL (`server/openrouter_client.py::generate_sql`)
- **Tipo**: LLM call
- **Input**: Mensagens do sistema e do usuário com schema e pergunta
- **Output**: SQL gerado
- **Métricas**: 
  - `prompt_tokens`: Tokens usados no prompt
  - `completion_tokens`: Tokens gerados na resposta
  - `total_tokens`: Total de tokens consumidos
- **Metadata**:
  - Modelo usado
  - Temperatura
  - Pergunta original
  - Se houve erro anterior (retry)

### 2. Geração de Dicionário de Dados (`scripts/consolidate.py::generate_dictionary_with_llm`)
- **Tipo**: LLM call
- **Input**: Prompt com informações do dataset e amostras
- **Output**: Dicionário de dados JSON
- **Métricas**: 
  - Tokens de prompt, completion e total
- **Metadata**:
  - Nome do dataset
  - Número de colunas
  - Número de arquivos processados
  - Modelo e temperatura

### 3. Cliente MCP Interativo (`client.py::chat`)
- **Tipo**: LLM call com tool calling
- **Input**: Mensagem do usuário e ferramentas disponíveis
- **Output**: Resposta final do assistente
- **Métricas**: 
  - Tokens de cada chamada (inicial e follow-ups)
- **Metadata**:
  - Número total de chamadas de ferramentas
  - Ferramentas utilizadas em cada iteração
  - Finish reason de cada resposta

### 4. Cliente HTTP MCP (`http_client.py::chat`)
- **Tipo**: LLM call com tool calling via HTTP
- **Input**: Mensagem do usuário
- **Output**: Resposta final do assistente
- **Métricas**: 
  - Tokens de cada chamada
- **Metadata**:
  - Iterações de tool calling
  - Ferramentas executadas
  - Sucesso da operação

## Como visualizar os dados

1. Acesse o dashboard do Braintrust em https://www.braintrustdata.com/
2. Selecione o projeto "Recife Open Data MCP"
3. Você verá:
   - Histórico de todas as chamadas LLM
   - Tempo de resposta
   - Custos por chamada
   - Taxa de sucesso/falha
   - Queries SQL geradas
   - Traces completos de cada pergunta

## Benefícios

- **Debugging**: Veja exatamente o que foi enviado para a LLM e o que foi retornado
- **Performance**: Monitore tempos de resposta e identifique gargalos
- **Custos**: Acompanhe o consumo de tokens e custos por query
- **Qualidade**: Analise a qualidade das respostas SQL geradas
- **Retry Analysis**: Identifique queries que precisaram de retry e por quê

## Exemplo de uso

Quando você faz uma pergunta via MCP, o cliente gera SQL com `generate_sql` e executa via `execute_sql`. O Braintrust registra:
1. A pergunta original
2. O prompt completo enviado para a LLM
3. O SQL gerado
4. Tokens consumidos
5. Se houve erro e retry
6. O resultado final

Tudo isso fica disponível no dashboard para análise posterior.
