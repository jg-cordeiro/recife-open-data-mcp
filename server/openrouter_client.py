from typing import Tuple
from openai import AsyncOpenAI
from .config import Settings


class OpenRouterClient:
    def __init__(self, settings: Settings) -> None:
        self.client = AsyncOpenAI(api_key=settings.openrouter_api_key, base_url="https://openrouter.ai/api/v1")
        self.model = settings.openrouter_model
        self.max_rows = settings.max_result_rows

    async def generate_sql(self, question: str, schema_text: str, previous_error: str | None = None) -> str:
        guidance = (
            "You are a SQL expert producing safe, read-only DuckDB SQL. "
            "Use only tables and columns from the schema. "
            f"Never mutate data. Always add LIMIT {self.max_rows} unless the query already limits rows. \n\n"
            "IMPORTANT RULES:\n"
            "1. Table names with hyphens MUST be quoted with double quotes\n"
            "2. Schema names MUST be quoted with double quotes\n"
            "3. Column names with special characters or capitals MUST be quoted\n"
            "4. Format: \"schema\".\"table-name\".\"Column_Name\"\n\n"
            "EXAMPLES:\n"
            "Q: How many records in the civil defense table?\n"
            'A: SELECT COUNT(*) FROM "public"."atendimentos-defesa-civil_consolidated" LIMIT 200;\n\n'
            "Q: Show me the first 5 student records\n"
            'A: SELECT * FROM "public"."situacao-final-estudantes_consolidated" LIMIT 5;\n\n'
            "Q: How many distinct years in civil defense data?\n"
            'A: SELECT COUNT(DISTINCT "Ano") AS distinct_years FROM "public"."atendimentos-defesa-civil_consolidated" LIMIT 200;\n\n'
            "Q: List neighborhoods with most incidents\n"
            'A: SELECT "Bairro", COUNT(*) as total FROM "public"."atendimentos-defesa-civil_consolidated" GROUP BY "Bairro" ORDER BY total DESC LIMIT 10;'
        )
        messages = [
            {"role": "system", "content": guidance},
            {
                "role": "user",
                "content": (
                    f"Schema:\n{schema_text}\n\nQuestion: {question}\n"
                    "Return ONLY SQL, no markdown fences or commentary."
                ),
            },
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
        return content.strip().strip("` ")
