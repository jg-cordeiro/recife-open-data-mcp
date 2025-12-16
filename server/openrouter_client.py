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
- Always call list_tables to see exact table names (no guesses). NEVER put tool calls inside SQL.
- Pick the table and call describe_table to get exact column names; use search_schema only to locate fields. This is required before generating SQL.
- You can consult dataset dictionaries via MCP resources: resource://dicionario-situacao-final, resource://dicionario-infracoes, resource://dicionario-naufragios.
- Use ONLY names returned by the tools. Do not invent columns (e.g., use "situacao_nome", "ano", "dataimplantacao", "dataInfracao", "profundidade_maxima", "historia detalhada").
- Treat year fields as text; do not cast unless you extract with regex. Quote schema/table/column with double quotes.
- In aggregations, always alias counts/sums clearly (e.g., COUNT(*) AS total) so the numeric column is explicit.
- For text filters, use LOWER + LIKE/regex as needed, but only on existing columns.
- Never mutate data. Do NOT add LIMIT automatically (only when the question asks for top-k).

IMPORTANT RULES:
1. Table names with hyphens MUST be quoted with double quotes.
2. Schema names MUST be quoted with double quotes.
3. Column names with special characters, spaces, or capitals MUST be quoted.
4. Format: "schema"."table-name"."Column_Name".

EXAMPLES (real tables/columns, sem LIMIT, only top-k when asked):
Q: Contagem total de registros de infrações
A: SELECT COUNT(*) AS total FROM "public"."registro_das_infrações_de_trânsito_-_cttu";

Q: Infrações registradas em 2019
A: SELECT COUNT(*) AS total FROM "public"."registro_das_infrações_de_trânsito_-_cttu" WHERE substr("dataInfracao",1,4) = '2019';

Q: Top 5 códigos de infração
A: SELECT "infracao", COUNT(*) AS total FROM "public"."registro_das_infrações_de_trânsito_-_cttu" GROUP BY "infracao" ORDER BY total DESC LIMIT 5;

Q: Top 5 anos com mais alunos
A: SELECT "ano", COUNT(*) AS total FROM "public"."situação_final_dos_alunos_por_período_letivo" GROUP BY "ano" ORDER BY total DESC LIMIT 5;

Q: Quantos registros de alunos em 2024
A: SELECT COUNT(*) AS total FROM "public"."situação_final_dos_alunos_por_período_letivo" WHERE "ano" = '2024';

Q: Top 3 naufrágios mais profundos (profundidade_maxima)
A: SELECT "nome", "profundidade_maxima" FROM "public"."naufrágios_do_recife" ORDER BY CAST(regexp_extract("profundidade_maxima", '(\\\\d+)') AS INTEGER) DESC LIMIT 3;

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
