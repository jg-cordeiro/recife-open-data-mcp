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
        table_name: The table name without schema (e.g., 'atendimentos-defesa-civil')
    
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


@app.resource("resource://dicionario-atendimentos")
async def resource_dicionario_atendimentos():
    """Descriptor JSON for atendimentos-defesa-civil (metadata/campos)."""
    from pathlib import Path
    path = Path("datasets/atendimentos-defesa-civil/dicionario-atendimentos-defesa-civil.json")
    return path.read_text(encoding="utf-8")


@app.resource("resource://dicionario-situacao-final")
async def resource_dicionario_situacao_final():
    """Descriptor JSON for situação_final_dos_alunos_por_período_letivo (metadata/campos)."""
    from pathlib import Path
    path = Path("datasets/situacao-final-estudantes/dicionario-situacao-final.json")
    return path.read_text(encoding="utf-8")


@app.tool()
async def answer_question(question: str) -> str:
    """RECOMMENDED: Answer questions about DATA content by generating and executing SQL.
    
    Use this for:
    - Questions about actual data (counts, statistics, aggregations)
    - Analytical queries ("quantos", "qual a taxa de", "mostre os top 10")
    - Filtering and data analysis
    
    Do NOT use for:
    - Asking what tables exist (use list_tables)
    - Asking what columns a table has (use describe_table)
    - Searching for schema elements (use search_schema)
    
    The system will generate SQL with proper quoting for table/column names,
    validate it, execute it, and return results. Includes automatic retry on errors.
    """
    with start_span(name="answer_question") as span:
        span.log(input={"question": question})
        
        llm_client = _require_llm()
        sql_first = await llm_client.generate_sql(question)
        
        try:
            result = await _run_sql(sql_first)
            span.log(
                output=result,
                metadata={
                    "sql_generated": sql_first,
                    "retry_attempted": False,
                    "success": True
                }
            )
            return str(result)
        except Exception as first_error:
            span.log(metadata={"first_error": str(first_error)})
            sql_second = await llm_client.generate_sql(question, previous_error=str(first_error))
            result = await _run_sql(sql_second)
            span.log(
                output=result,
                metadata={
                    "sql_generated": sql_second,
                    "retry_attempted": True,
                    "success": True
                }
            )
            return str(result)


if __name__ == "__main__":
    app.run()
