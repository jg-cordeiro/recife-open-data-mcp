import asyncio
from fastmcp import FastMCP
from .config import Settings
from .db import Database
from .sql_guard import ensure_limit, ensure_read_only
from .openrouter_client import OpenRouterClient

settings = Settings.load()
settings.require_api_key()
db = Database(settings)
llm = OpenRouterClient(settings)
app = FastMCP("recife-open-data-mcp")


async def _run_sql(sql: str):
    ensure_read_only(sql)
    limited = ensure_limit(sql, settings.max_result_rows)
    rows = await db.fetch_rows(limited)
    return {"sql": limited, "row_count": len(rows), "rows": rows}


@app.resource("database://schema")
async def schema_snapshot():
    """Get the schema snapshot of all tables and columns."""
    text = await db.fetch_schema_snapshot()
    return text


@app.tool()
async def execute_sql(sql: str) -> str:
    """Execute a read-only SQL query with timeout and row limit."""
    result = await _run_sql(sql)
    return str(result)


@app.tool()
async def answer_question(question: str) -> str:
    """Convert a natural language question into SQL, run it, and return the result."""
    schema_text = await db.fetch_schema_snapshot()
    sql_first = await llm.generate_sql(question, schema_text)
    try:
        result = await _run_sql(sql_first)
        return str(result)
    except Exception as first_error:
        sql_second = await llm.generate_sql(question, schema_text, previous_error=str(first_error))
        result = await _run_sql(sql_second)
        return str(result)


if __name__ == "__main__":
    app.run()

