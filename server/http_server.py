"""
HTTP Transport server for MCP using FastAPI and SSE.
"""
import asyncio
import json
import logging
from typing import Any, Dict, List
from decimal import Decimal
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from sse_starlette.sse import EventSourceResponse
from contextlib import asynccontextmanager
from braintrust import start_span

from .config import Settings
from .db import Database
from .sql_guard import ensure_limit, ensure_read_only
from .openrouter_client import OpenRouterClient


# Global state
settings = Settings.load()
db: Database = None
llm: OpenRouterClient = None


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
logger = logging.getLogger("mcp.http")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize database connection on startup."""
    global db, llm
    settings.require_api_key()
    logger.info("Starting MCP HTTP server with DuckDB database at %s", settings.db_path)
    db = Database(settings)
    await db.init()
    llm = OpenRouterClient(settings)
    logger.info("MCP HTTP server ready")
    yield
    await db.close()
    logger.info("MCP HTTP server shutdown complete")


app = FastAPI(
    title="Recife Open Data MCP Server",
    description="MCP server for querying Recife open datasets via HTTP/SSE",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


async def _run_sql(sql: str) -> Dict[str, Any]:
    """Execute SQL with guardrails."""
    logger.info("_run_sql called", extra={"sql_preview": sql[:200]})
    ensure_read_only(sql)
    limited = ensure_limit(sql, settings.max_result_rows)
    rows = await db.fetch_rows(limited)
    logger.info("SQL executed", extra={"row_count": len(rows)})
    return {"sql": limited, "row_count": len(rows), "rows": rows}


def _convert_to_serializable(obj: Any) -> Any:
    """Convert Decimal and other non-JSON types to JSON-serializable types."""
    if isinstance(obj, Decimal):
        return float(obj)
    elif isinstance(obj, dict):
        return {k: _convert_to_serializable(v) for k, v in obj.items()}
    elif isinstance(obj, (list, tuple)):
        return [_convert_to_serializable(item) for item in obj]
    return obj


@app.get("/")
async def root():
    """Health check endpoint."""
    return {"status": "ok", "service": "recife-open-data-mcp", "transport": "http"}


@app.get("/health")
async def health():
    """Detailed health check."""
    try:
        # Test database connection
        await db.list_tables()
        return {"status": "healthy", "database": "connected", "llm": "configured"}
    except Exception as e:
        return JSONResponse(
            status_code=503,
            content={"status": "unhealthy", "error": str(e)}
        )


@app.get("/mcp/v1/capabilities")
async def get_capabilities():
    """Return MCP server capabilities."""
    return {
        "capabilities": {
            "tools": True,
            "resources": True,
            "prompts": False,
        },
        "serverInfo": {
            "name": "recife-open-data-mcp",
            "version": "1.0.0",
        },
    }


@app.get("/mcp/v1/tools")
async def list_tools():
    """List available MCP tools."""
    return {
        "tools": [
            {
                "name": "list_tables",
                "description": "List all available tables in the database with their schemas.",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                    "required": [],
                },
            },
            {
                "name": "describe_table",
                "description": "Get detailed column information for a specific table including column names, types, and nullability.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "table_name": {
                            "type": "string",
                            "description": "Name of the table to describe (without schema)"
                        }
                    },
                    "required": ["table_name"],
                },
            },
            {
                "name": "search_schema",
                "description": "Search for tables or columns matching a keyword.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "search_term": {
                            "type": "string",
                            "description": "Keyword to search for in table and column names"
                        }
                    },
                    "required": ["search_term"],
                },
            },
            {
                "name": "list_databases",
                "description": "List all database schemas available.",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                    "required": [],
                },
            },
            {
                "name": "execute_sql",
                "description": "Execute a read-only SQL query with timeout and row limit.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "sql": {
                            "type": "string",
                            "description": "SQL query to execute"
                        }
                    },
                    "required": ["sql"],
                },
            },
            {
                "name": "answer_question",
                "description": "Convert a natural language question into SQL, run it, and return formatted results.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "question": {
                            "type": "string",
                            "description": "Natural language question about the data"
                        }
                    },
                    "required": ["question"],
                },
            },
        ]
    }


@app.post("/mcp/v1/tools/execute")
async def execute_tool(request: Request):
    """Execute a tool and return results."""
    body = await request.json()
    tool_name = body.get("name")
    arguments = body.get("arguments", {})

    logger.info(
        "Tool request",
        extra={"tool": tool_name, "arguments_preview": json.dumps(arguments)[:500]},
    )

    try:
        if tool_name == "list_tables":
            tables = await db.list_tables()
            payload = _convert_to_serializable({
                "message": f"Found {len(tables)} tables",
                "tables": tables,
            })
            return {
                "content": [
                    {"type": "text", "text": json.dumps(payload, indent=2, ensure_ascii=False)}
                ]
            }

        elif tool_name == "describe_table":
            table_name = arguments.get("table_name")
            if not table_name:
                return JSONResponse(status_code=400, content={"error": "table_name is required"})
            columns = await db.describe_table(table_name)
            payload = _convert_to_serializable({
                "table": table_name,
                "column_count": len(columns) if columns else 0,
                "columns": columns or [],
            })
            return {
                "content": [
                    {"type": "text", "text": json.dumps(payload, indent=2, ensure_ascii=False)}
                ]
            }

        elif tool_name == "search_schema":
            search_term = arguments.get("search_term")
            if not search_term:
                return JSONResponse(status_code=400, content={"error": "search_term is required"})
            results = await db.search_schema(search_term)
            payload = _convert_to_serializable({
                "message": f"Found {len(results)} matches" if results else f"No matches for '{search_term}'",
                "results": results or [],
            })
            return {
                "content": [
                    {"type": "text", "text": json.dumps(payload, indent=2, ensure_ascii=False)}
                ]
            }

        elif tool_name == "list_databases":
            schemas = await db.list_databases()
            payload = _convert_to_serializable({
                "message": f"Found {len(schemas)} schemas",
                "schemas": schemas,
            })
            return {
                "content": [
                    {"type": "text", "text": json.dumps(payload, indent=2, ensure_ascii=False)}
                ]
            }

        if tool_name == "execute_sql":
            sql = arguments.get("sql")
            if not sql:
                return JSONResponse(
                    status_code=400,
                    content={"error": "SQL query is required"}
                )
            result = await _run_sql(sql)
            result = _convert_to_serializable(result)
            return {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(result, indent=2, ensure_ascii=False)
                    }
                ]
            }

        elif tool_name == "answer_question":
            question = arguments.get("question")
            if not question:
                return JSONResponse(
                    status_code=400,
                    content={"error": "Question is required"}
                )
            
            with start_span(name="answer_question_http") as span:
                span.log(input={"question": question})
                
                sql_first = await llm.generate_sql(question)
                logger.info("Generated SQL (first pass)", extra={"sql_preview": sql_first[:200]})
                
                try:
                    result = await _run_sql(sql_first)
                    # Format response nicely
                    formatted = {
                        "question": question,
                        "sql": result["sql"],
                        "row_count": result["row_count"],
                        "data": result["rows"]
                    }
                    formatted = _convert_to_serializable(formatted)
                    logger.info(
                        "answer_question succeeded",
                        extra={"row_count": result["row_count"], "sql_preview": result["sql"][:200]},
                    )
                    
                    span.log(
                        output=formatted,
                        metadata={
                            "sql_generated": sql_first,
                            "retry_attempted": False,
                            "success": True
                        }
                    )
                    
                    return {
                        "content": [
                            {
                                "type": "text",
                                "text": json.dumps(formatted, indent=2, ensure_ascii=False)
                            }
                        ]
                    }
                except Exception as first_error:
                    # Retry with error feedback
                    logger.warning("answer_question first attempt failed", extra={"error": str(first_error)})
                    span.log(metadata={"first_error": str(first_error)})
                    
                    sql_second = await llm.generate_sql(question, previous_error=str(first_error))
                    logger.info("Generated SQL (retry)", extra={"sql_preview": sql_second[:200]})
                    result = await _run_sql(sql_second)
                    formatted = {
                        "question": question,
                        "sql": result["sql"],
                        "row_count": result["row_count"],
                        "data": result["rows"],
                        "note": "Query was retried due to initial error"
                    }
                    formatted = _convert_to_serializable(formatted)
                    logger.info(
                        "answer_question succeeded on retry",
                        extra={"row_count": result["row_count"], "sql_preview": result["sql"][:200]},
                    )
                    
                    span.log(
                        output=formatted,
                        metadata={
                            "sql_generated": sql_second,
                            "retry_attempted": True,
                            "success": True
                        }
                    )
                    
                    return {
                        "content": [
                            {
                                "type": "text",
                                "text": json.dumps(formatted, indent=2, ensure_ascii=False)
                            }
                        ]
                }

        else:
            return JSONResponse(
                status_code=404,
                content={"error": f"Tool '{tool_name}' not found"}
            )

    except Exception as e:
        logger.exception("Tool execution failed")
        return JSONResponse(
            status_code=500,
            content={"error": str(e)}
        )


@app.get("/mcp/v1/resources")
async def list_resources():
    """List available MCP resources."""
    return {"resources": []}


@app.post("/mcp/v1/resources/read")
async def read_resource(request: Request):
    """Read a resource."""
    return JSONResponse(
        status_code=404,
        content={"error": "No resources exposed"}
    )


if __name__ == "__main__":
    import uvicorn
    port = int(settings.__dict__.get("http_port", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
