import asyncio
from fastmcp import FastMCP, tool, resource
from .config import Settings
from .db import Database
from .sql_guard import ensure_limit, ensure_read_only
from .openrouter_client import OpenRouterClient

settings = Settings.load()
settings.require_api_key()
db = Database(settings)
llm = OpenRouterClient(settings)
mcp = FastMCP("recife-open-data-mcp")


async def _run_sql(sql: str):
    ensure_read_only(sql)
    limited = ensure_limit(sql, settings.max_result_rows)
    rows = await db.fetch_rows(limited, timeout_ms=settings.statement_timeout_ms)
    return {"sql": limited, "row_count": len(rows), "rows": rows}


@resource()
async def schema_snapshot():
    text = await db.fetch_schema_snapshot()
    return {"schema": text}


@tool()
async def execute_sql(sql: str):
    """Execute a read-only SQL query with timeout and row limit."""
    return await _run_sql(sql)


@tool()
async def answer_question(question: str):
    """Convert a natural language question into SQL, run it, and return the result."""
    schema_text = await db.fetch_schema_snapshot()
    sql_first = await llm.generate_sql(question, schema_text)
    try:
        return await _run_sql(sql_first)
    except Exception as first_error:
        sql_second = await llm.generate_sql(question, schema_text, previous_error=str(first_error))
        return await _run_sql(sql_second)


if __name__ == "__main__":
    asyncio.run(mcp.run())
