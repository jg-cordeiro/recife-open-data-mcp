import os
from typing import Tuple
from dotenv import load_dotenv
from openai import AsyncOpenAI
from braintrust import current_span, init_logger, traced
from .config import Settings

load_dotenv()

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
        self.max_sql_attempts = 2

    @staticmethod
    def _looks_like_sql(sql_text: str) -> bool:
        lowered = sql_text.strip().lower()
        return lowered.startswith("select") or lowered.startswith("with")

    @traced(type="llm", name="OpenRouter SQL Generation", notrace_io=True)
    async def generate_sql(self, question: str, schema_text: str | None = None, previous_error: str | None = None) -> str:
        guidance = f"""You are an specialist that produces safe, read-only DuckDB SQL for Recife open data. Think and reason step by step, then emit only the final SQL.

MENTAL STEPS (do not output these):
1) Schema linking: call list_tables first; for every table you might use, call describe_table; use search_schema only to locate fields. Consult dictionaries via MCP resources (resource://dicionario-situacao-final, resource://dicionario-infracoes, resource://dicionario-naufragios). Collect exact table/column names—no guesses.
2) Plan: decide intent (aggregation/lookup/join), pick tables/joins, define filters/group/order/limit, ensure each filter uses the right column and operator (use regex or LIKE for substring matches instead of strict = when the question implies containment).
3) SQL generation: write one SELECT (or WITH + SELECT) honoring the safety rules below, quoting everything.
4) On errors: if a column/table is missing or a cast fails, re-check with describe_table/search_schema and adjust filters/casts (e.g., filter out blanks before CAST). Regenerate SQL with the corrected names/filters.
5) Do not call create_sql/execute_sql until after list_tables AND describe_table have been called for every table you will reference.

STRICT SCHEMA RULES:
- For every table you intend to query, you MUST call describe_table for that table in the current attempt before producing SQL. Do not reuse column names that were not obtained via describe_table in this attempt.
- If you hit any error about missing columns/tables/casts, immediately call describe_table (and search_schema if needed) and only then regenerate SQL.
- If your current attempt did not call describe_table for each table you reference, stop and do it before replying with SQL.
- Never call create_sql/execute_sql before you have called list_tables and describe_table for each table you plan to use in this attempt.

SAFETY/QUALITY RULES:
- Use ONLY names returned by the tools. Do not invent columns.
- Always return valid, executable SQL; never return empty output. If you are unsure, call tools and try again.
- Categorical filters must format values using lowercase + LIKE or regex (~) for substring/keyword matches; do not use strict equals (=) unless you are 100% sure.
- Prefer lower(...) + LIKE with unaccented terms (e.g., %infantil%) over exact matches with special characters.
- Date handling: if the column is in ISO format (YYYY-MM-DD) or can be parsed by DuckDB, extract year with substr(col, 1, 4) or EXTRACT(YEAR FROM try_cast(col AS DATE)). Use regex ONLY when the date format is non-ISO/mixed text; then extract a 4-digit year with regexp_extract and filter blanks before casting/grouping.
- In aggregations, alias counts/sums clearly (COUNT(*) AS total, etc.).
- For rankings, always include correct GROUP BY, ORDER BY total DESC, and LIMIT equal to the requested top_k.
- For text filters, use LOWER + LIKE or regex (~) when matching substrings/keywords; avoid exact equals if the question implies containment. Only reference existing columns.
- When writing CASE expressions on text labels, MUST use regex/LIKE checks against the correct column name unless 100% sure of exact values; do not stack equals with guessed variants. Always include the column in each WHEN condition.
- Never mutate data. Do NOT add LIMIT automatically (only when the question asks for top-k/samples).
- Avoid COUNT(DISTINCT ...) unless the question asks for uniques; use COUNT(*) otherwise.
- For rates/percentages, return the fraction unless the question explicitly asks for percent; do NOT multiply by 100 unless requested.
- For dates, avoid regex when the format is YYYY-MM-DD; use substr/EXTRACT. Only use regex for non-ISO/mixed text dates.
- For averages/ranges, respect the question filters (e.g., age 4-30) and use try_cast when the column is text.
- Always qualify and quote schema + table + column names; do not use bare table names without schema in the FROM.

IMPORTANT RULES:
1. Table names with hyphens MUST be quoted with double quotes.
2. Schema names MUST be quoted with double quotes.
3. Column names with special characters, spaces, or capitals MUST be quoted.
4. Format: "schema"."table-name"."Column_Name".

EXAMPLES:
Q: Contagem total de registros de infrações
A: SELECT COUNT(*) AS total FROM "public"."registro_das_infrações_de_trânsito_-_cttu";

Q: Infrações registradas em 2019
A: SELECT COUNT(*) AS total FROM "public"."registro_das_infrações_de_trânsito_-_cttu" WHERE substr("dataInfracao", 1, 4) = '2019';

Q: Multas implantadas em 2024
A: SELECT COUNT(*) AS total FROM "public"."registro_das_infrações_de_trânsito_-_cttu" WHERE substr("dataimplantacao", 1, 4) = '2024';

Q: Top 5 códigos de infração
A: SELECT "infracao", COUNT(*) AS total FROM "public"."registro_das_infrações_de_trânsito_-_cttu" GROUP BY "infracao" ORDER BY total DESC LIMIT 5;

Q: Amostra de 3 infrações com data, hora, código e descrição
A: SELECT "dataInfracao", "horainfracao", "infracao", "descricaoinfracao" FROM "public"."registro_das_infrações_de_trânsito_-_cttu" LIMIT 3;

Q: Top 5 anos com mais alunos
A: SELECT "ano", COUNT(*) AS total FROM "public"."situação_final_dos_alunos_por_período_letivo" GROUP BY "ano" ORDER BY total DESC LIMIT 5;

Q: Quantos registros de alunos em 2024
A: SELECT COUNT(*) AS total FROM "public"."situação_final_dos_alunos_por_período_letivo" WHERE "ano" = '2024';

Q: Top 3 naufrágios mais profundos (profundidade_maxima)
A: SELECT "nome", "profundidade_maxima" FROM "public"."naufrágios_do_recife" ORDER BY CAST(regexp_extract("profundidade_maxima", '(\\\\d+)') AS INTEGER) DESC LIMIT 3;

# Regex/LIKE with CASE examples
Q: Quantos aprovados tiveram em 2016
A: SELECT COUNT(*) AS total FROM "public"."situação_final_dos_alunos_por_período_letivo" WHERE "ano" = '2016' AND CASE WHEN lower("situacao_nome") LIKE 'aprov%' THEN 1 ELSE 0 END = 1;

Q: Taxa de retenção (qualquer RETIDO) por ano
A: SELECT "ano", CAST(SUM(CASE WHEN upper("situacao_nome") LIKE 'RETIDO%' THEN 1 ELSE 0 END) AS DOUBLE) / COUNT(*) AS taxa_retencao FROM "public"."situação_final_dos_alunos_por_período_letivo" GROUP BY "ano" ORDER BY "ano";

Q: Quantas infrações com descrição contendo VELOCIDADE em 2023
A: SELECT COUNT(*) AS total FROM "public"."registro_das_infrações_de_trânsito_-_cttu" WHERE regexp_extract("dataInfracao", '(20\\d{2})') = '2023' AND CASE WHEN upper("descricaoinfracao") LIKE '%VELOCIDADE%' THEN 1 ELSE 0 END = 1;

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
                "content": "The prior SQL failed. Understand and revise to fix the error and stay read-only. If a column error occurs, STOP and call describe_table (and check resources), then regenerate SQL with the exact names. Do not retry with guessed names.",
            })
            messages.append({"role": "user", "content": f"Error: {previous_error}"})
        last_sql = ""
        for attempt in range(1, self.max_sql_attempts + 1):
            resp = await self.client.chat.completions.create(
                model=self.model,
                temperature=0,
                messages=messages,
            )
            content = resp.choices[0].message.content or ""
            sql_output = content.strip().strip("` ")
            last_sql = sql_output

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
                    "sql_attempt": attempt,
                }
            )

            if sql_output and self._looks_like_sql(sql_output):
                return sql_output

            messages.append(
                {
                    "role": "user",
                    "content": "Your previous response did not contain valid SQL. Return ONLY a single read-only SQL query.",
                }
            )

        return last_sql
