import asyncio
import json
from fastmcp import FastMCP
from braintrust import start_span
from .config import Settings
from .db import Database
from .sql_guard import ensure_limit, ensure_read_only
from .openrouter_client import OpenRouterClient

settings = Settings.load()
db = Database(settings)
llm: OpenRouterClient | None = None
app = FastMCP("recife-open-data-mcp")
mcp = app  # alias for runtimes expecting 'mcp'


def _require_llm() -> OpenRouterClient:
    """Instantiate the LLM client only when needed and after validating secrets."""
    global llm
    if llm is None:
        settings.require_api_key()
        llm = OpenRouterClient(settings)
    return llm


async def _run_sql(sql: str):
    ensure_read_only(sql)
    limited = ensure_limit(sql, settings.max_result_rows)
    rows = await db.fetch_rows(limited)
    return {"sql": limited, "row_count": len(rows), "rows": rows}


@app.tool()
async def execute_sql(sql: str) -> str:
    """Execute a pre-written SQL query directly.
    
    Use this ONLY when:
    - You already have a complete, valid SQL query
    - You don't need SQL generation
    - You're testing or validating a specific query
    
    The query will be validated for read-only operations and automatically limited.
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
    import json
    return json.dumps({"message": f"Found {len(tables)} tables", "tables": tables})


@app.tool()
async def describe_table(table_name: str) -> str:
    """Get detailed column information for a specific table.
    
    Use this when:
    - You need to know what columns are in a table
    - You need to know column data types
    - Before writing queries to ensure correct column names
    
    Args:
        table_name: The table name without schema (e.g., 'situação_final_dos_alunos_por_período_letivo')
    
    Returns column names, types, and nullability information.
    """
    import json
    columns = await db.describe_table(table_name)
    if not columns:
        return json.dumps({"error": f"Table '{table_name}' not found", "columns": []})
    return json.dumps({"table": table_name, "column_count": len(columns), "columns": columns})


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
    import json
    results = await db.search_schema(search_term)
    if not results:
        return json.dumps({"message": f"No tables or columns found matching '{search_term}'", "results": []})
    return json.dumps({"message": f"Found {len(results)} matches", "results": results})


@app.tool()
async def list_databases() -> str:
    """List all database schemas available.
    
    Use this to see what schemas exist in the database.
    Most tables are in the 'public' schema.
    
    Returns a list of schema names.
    """
    import json
    schemas = await db.list_databases()
    return json.dumps({"message": f"Found {len(schemas)} schemas", "schemas": schemas})


@app.resource("resource://dicionario-situacao-final")
async def resource_dicionario_situacao_final():
    """Descriptor JSON for situação_final_dos_alunos_por_período_letivo (metadata/campos)."""
    from pathlib import Path
    path = Path("resources/dicionario-situacao-final.json")
    return path.read_text(encoding="utf-8")


@app.resource("resource://dicionario-infracoes")
async def resource_dicionario_infracoes():
    """Descriptor JSON for registro das infrações de trânsito (metadata/campos)."""
    from pathlib import Path
    path = Path("resources/dicionario-de-dados-das-infracoes-de-transito.json")
    return path.read_text(encoding="utf-8")


@app.resource("resource://dicionario-naufragios")
async def resource_dicionario_naufragios():
    """Descriptor JSON for naufrágios do Recife (metadata/campos)."""
    from pathlib import Path
    path = Path("resources/dicionario-naufragios.json")
    return path.read_text(encoding="utf-8")


if __name__ == "__main__":
    app.run()
