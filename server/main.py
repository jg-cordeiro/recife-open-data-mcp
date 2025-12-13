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
    """Execute a pre-written SQL query directly.
    
    Use this ONLY when:
    - You already have a complete, valid SQL query
    - You don't need SQL generation
    - You're testing or validating a specific query
    
    The query will be validated for read-only operations and automatically limited.
    For questions requiring SQL generation, use answer_question instead.
    """
    result = await _run_sql(sql)
    return str(result)


@app.tool()
async def list_tables() -> str:
    """List all available tables in the database with their schemas. 
    
    Use this when:
    - User asks what tables exist
    - User asks what data is available
    - User wants to know the database structure
    - Before generating SQL to verify table names
    
    Returns a list of tables with their full quoted names for use in queries.
    """
    tables = await db.list_tables()
    return str(tables)


@app.tool()
async def describe_table(table_name: str) -> str:
    """Get detailed column information for a specific table.
    
    Use this when:
    - You need to know what columns are in a table
    - You need to know column data types
    - Before writing queries to ensure correct column names
    
    Args:
        table_name: The table name without schema (e.g., 'atendimentos-defesa-civil_consolidated')
    
    Returns column names, types, and nullability information.
    """
    columns = await db.describe_table(table_name)
    return str(columns)


@app.tool()
async def search_schema(search_term: str) -> str:
    """Search for tables or columns matching a keyword.
    
    Use this when:
    - Looking for where specific data might be stored
    - Searching for columns by name or concept
    - Finding tables related to a topic
    
    Args:
        search_term: Keyword to search for (case-insensitive)
    
    Returns matching tables and columns with their full quoted references.
    """
    results = await db.search_schema(search_term)
    return str(results)


@app.tool()
async def list_databases() -> str:
    """List all database schemas available.
    
    Use this to see what schemas exist in the database.
    Most tables are in the 'public' schema.
    
    Returns a list of schema names.
    """
    schemas = await db.list_databases()
    return str(schemas)


@app.tool()
async def answer_question(question: str) -> str:
    """Convert a natural language question into SQL and execute it.
    
    Use this ONLY for:
    - Analytical questions requiring data queries
    - Questions about data content (not structure)
    - Questions needing aggregations, filtering, or joins
    
    Do NOT use for:
    - Asking what tables exist (use list_tables)
    - Asking what columns a table has (use describe_table)
    - Searching for schema elements (use search_schema)
    
    The system will generate SQL with proper quoting for table/column names,
    validate it, execute it, and return results. Includes automatic retry on errors.
    """
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

