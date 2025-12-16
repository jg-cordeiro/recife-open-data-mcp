import os
from typing import Tuple
from openai import AsyncOpenAI
from braintrust import current_span, init_logger, traced
from .config import Settings

# Initialize Braintrust logger
logger = init_logger(
    project="Recife Open Data MCP",
    api_key=os.getenv("BRAINTRUST_API_KEY")
)


class OpenRouterClient:
    def __init__(self, settings: Settings) -> None:
        self.client = AsyncOpenAI(api_key=settings.openrouter_api_key, base_url="https://openrouter.ai/api/v1")
        self.model = settings.openrouter_model
        self.max_rows = settings.max_result_rows

    @traced(type="llm", name="OpenRouter SQL Generation", notrace_io=True)
    async def generate_sql(self, question: str, schema_text: str | None = None, previous_error: str | None = None) -> str:
        guidance = f"""You are a SQL expert producing safe, read-only DuckDB SQL for Recife open data.
BEFORE any SQL:
- Call list_tables to see exact table names (no guesses). NEVER put tool calls inside SQL.
- Pick the table and call describe_table to get exact column names; use search_schema only to locate fields. This is required before generating SQL.
- You can consult dataset dictionaries via MCP resources: resource://dicionario-atendimentos and resource://dicionario-situacao-final to confirm naming.
- Use ONLY the names returned by the tools. Do not invent columns (e.g., no Ano_Letivo, no Ocorrência; use Ano, Ocorrencia, Grau_de_Risco, situacao_nome, ano, escola, sexo, etc.).
- Treat year fields as text; do not cast. Quote schema/table/column with double quotes.
- In aggregations, always alias counts/sums clearly (e.g., COUNT(*) AS total) so the numeric column is explicit.
- For text filters with variants (ex.: R3), use LOWER + LIKE/regex as needed, but only on existing columns.
- Never mutate data. Do NOT add LIMIT automatically.

IMPORTANT RULES:
1. Table names with hyphens MUST be quoted with double quotes
2. Schema names MUST be quoted with double quotes
3. Column names with special characters or capitals MUST be quoted
4. Format: "schema"."table-name"."Column_Name"

EXAMPLES (real tables/columns, sem LIMIT):
Q: Contagem total de atendimentos
A: SELECT COUNT(*) AS total FROM "public"."atendimentos-defesa-civil";

Q: Atendimentos de 2024
A: SELECT COUNT(*) AS total FROM "public"."atendimentos-defesa-civil" WHERE "Ano" = '2024';

Q: Top 5 bairros com mais atendimentos
A: SELECT "Bairro", COUNT(*) AS total FROM "public"."atendimentos-defesa-civil" GROUP BY "Bairro" ORDER BY total DESC LIMIT 5;

Q: Atendimentos de Monitoramento
A: SELECT COUNT(*) AS total FROM "public"."atendimentos-defesa-civil" WHERE "Ocorrencia" = 'Monitoramento';

Q: Quantos registros de alunos em 2024
A: SELECT COUNT(*) AS total FROM "public"."situação_final_dos_alunos_por_período_letivo" WHERE "ano" = '2024';

Q: Quantos alunos aprovados em 2023
A: SELECT COUNT(*) AS total FROM "public"."situação_final_dos_alunos_por_período_letivo" WHERE "ano" = '2023' AND "situacao_nome" = 'APROVADO';

Q: Top 5 anos com mais registros de alunos
A: SELECT "ano", COUNT(*) AS total FROM "public"."situação_final_dos_alunos_por_período_letivo" GROUP BY "ano" ORDER BY total DESC LIMIT 5;

If a column error occurs, STOP and call describe_table (and check resources), then regenerate SQL with the exact names. Do not retry with guessed names."""
        user_content = f"Question: {question}\nReturn ONLY SQL, no markdown fences or commentary."
        if schema_text:
            user_content = f"Schema:\n{schema_text}\n\n{user_content}"

        messages = [
            {"role": "system", "content": guidance},
            {"role": "user", "content": user_content},
        ]
        if previous_error:
            messages.append({
                "role": "assistant",
                "content": "The prior SQL failed. Revise to fix the error and stay read-only.",
            })
            messages.append({"role": "user", "content": f"Error: {previous_error}"})
        resp = await self.client.chat.completions.create(
            model=self.model,
            temperature=0,
            messages=messages,
        )
        content = resp.choices[0].message.content or ""
        sql_output = content.strip().strip("` ")
        
        # Log to Braintrust with structured input/output
        usage = resp.usage or None
        current_span().log(
            input=messages,
            output=sql_output,
            metrics={
                "prompt_tokens": usage.prompt_tokens if usage else 0,
                "completion_tokens": usage.completion_tokens if usage else 0,
                "total_tokens": usage.total_tokens if usage else 0,
            },
            metadata={
                "model": self.model,
                "temperature": 0,
                "question": question,
                "has_previous_error": previous_error is not None,
            }
        )
        
        return sql_output
