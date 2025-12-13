import json
import subprocess
import sys
from pathlib import Path

from openai import AsyncOpenAI
import asyncio
import typer
from dotenv import load_dotenv
from server.config import Settings

load_dotenv()

app = typer.Typer(help="Interactive MCP client for testing via OpenRouter.")
settings = Settings.load()


class MCPClient:
    def __init__(self):
        self.process = None
        self.settings = settings
        self.client = AsyncOpenAI(
            api_key=settings.openrouter_api_key,
            base_url="https://openrouter.ai/api/v1",
        )
        self.model = settings.openrouter_model
        self.tools = None
        self.schema_snapshot = None

    async def start_server(self) -> None:
        """Start the MCP server."""
        typer.secho("🚀 Starting MCP server...", fg=typer.colors.CYAN)
        self.process = subprocess.Popen(
            [sys.executable, "-m", "server.main"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        await asyncio.sleep(2)
        typer.secho("✅ MCP server started", fg=typer.colors.GREEN)

    async def fetch_tools(self) -> list:
        """Fetch available tools from MCP server."""
        # For now, return hardcoded tools since we're in stdio mode
        return [
            {
                "type": "function",
                "function": {
                    "name": "list_tables",
                    "description": "List all available tables in the database with their schemas. Use this when the user asks what tables exist, what data is available, or wants to know the database structure.",
                    "parameters": {"type": "object", "properties": {}, "required": []},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "describe_table",
                    "description": "Get detailed column information for a specific table including column names, types, and nullability. Use this when you need to know the structure of a specific table before querying it.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "table_name": {
                                "type": "string",
                                "description": "Name of the table to describe (without schema, e.g., 'atendimentos-defesa-civil_consolidated')",
                            }
                        },
                        "required": ["table_name"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "search_schema",
                    "description": "Search for tables or columns matching a keyword. Use this when you need to find where certain data might be located or what columns contain specific information.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "search_term": {
                                "type": "string",
                                "description": "Keyword to search for in table and column names",
                            }
                        },
                        "required": ["search_term"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "list_databases",
                    "description": "List all database schemas available. Use this to see what schemas exist in the database.",
                    "parameters": {"type": "object", "properties": {}, "required": []},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "execute_sql",
                    "description": "Execute a pre-written SQL query directly. Use this only when you already have a complete, valid SQL query and don't need SQL generation.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "sql": {"type": "string", "description": "Complete SQL query to execute"}
                        },
                        "required": ["sql"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "answer_question",
                    "description": "Convert a complex analytical question into SQL, run it, and return results. Use this ONLY for questions that require data analysis, aggregations, filtering, or complex queries. Do NOT use for schema exploration.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "question": {
                                "type": "string",
                                "description": "Analytical question requiring SQL generation and execution",
                            }
                        },
                        "required": ["question"],
                    },
                },
            },
        ]

    async def call_mcp_tool(self, tool_name: str, tool_input: dict) -> str:
        """Call a tool via MCP server."""
        from server.db import Database
        from server.sql_guard import ensure_limit, ensure_read_only
        from server.openrouter_client import OpenRouterClient

        db = Database(self.settings)
        await db.init()

        try:
            if tool_name == "list_tables":
                typer.secho("📋 Listing all tables...", fg=typer.colors.BLUE)
                tables = await db.list_tables()
                return json.dumps(tables)
            elif tool_name == "describe_table":
                table_name = tool_input.get("table_name", "")
                typer.secho(f"📄 Describing table: {table_name}", fg=typer.colors.BLUE)
                columns = await db.describe_table(table_name)
                return json.dumps(columns)
            elif tool_name == "search_schema":
                search_term = tool_input.get("search_term", "")
                typer.secho(f"🔍 Searching schema for: {search_term}", fg=typer.colors.BLUE)
                results = await db.search_schema(search_term)
                return json.dumps(results)
            elif tool_name == "list_databases":
                typer.secho("🗄️  Listing databases/schemas...", fg=typer.colors.BLUE)
                schemas = await db.list_databases()
                return json.dumps(schemas)
            elif tool_name == "execute_sql":
                sql = tool_input.get("sql", "")
                typer.secho(f"📊 Executing SQL: {sql[:80]}...", fg=typer.colors.BLUE)
                ensure_read_only(sql)
                limited = ensure_limit(sql, self.settings.max_result_rows)
                rows = await db.fetch_rows(limited)
                result = {"sql": limited, "row_count": len(rows), "rows": rows}
                return json.dumps(result)
            elif tool_name == "answer_question":
                question = tool_input.get("question", "")
                typer.secho(f"❓ Question: {question}", fg=typer.colors.BLUE)
                llm = OpenRouterClient(self.settings)
                schema_text = await db.fetch_schema_snapshot()
                sql_first = await llm.generate_sql(question, schema_text)
                typer.secho(f"🔍 Generated SQL: {sql_first[:100]}...", fg=typer.colors.YELLOW)
                try:
                    ensure_read_only(sql_first)
                    limited = ensure_limit(sql_first, self.settings.max_result_rows)
                    rows = await db.fetch_rows(limited)
                    result = {"sql": limited, "row_count": len(rows), "rows": rows}
                    return json.dumps(result)
                except Exception as first_error:
                    typer.secho(f"⚠️  First SQL attempt failed: {first_error}", fg=typer.colors.YELLOW)
                    sql_second = await llm.generate_sql(question, schema_text, previous_error=str(first_error))
                    typer.secho(f"🔄 Retrying with revised SQL: {sql_second[:100]}...", fg=typer.colors.YELLOW)
                    ensure_read_only(sql_second)
                    limited = ensure_limit(sql_second, self.settings.max_result_rows)
                    rows = await db.fetch_rows(limited)
                    result = {"sql": limited, "row_count": len(rows), "rows": rows}
                    return json.dumps(result)
            else:
                return json.dumps({"error": f"Unknown tool: {tool_name}"})
        finally:
            await db.close()

    async def chat(self, user_message: str) -> str:
        """Send a message to Claude via OpenRouter and process tool calls."""
        typer.secho(f"\n👤 User: {user_message}", fg=typer.colors.CYAN)

        messages = [{"role": "user", "content": user_message}]
        tools = await self.fetch_tools()

        # First request with tools
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            tools=tools,
            tool_choice="auto",
        )

        # Tool use loop
        while response.choices[0].finish_reason == "tool_calls":
            tool_calls = response.choices[0].message.tool_calls
            
            # Add assistant message with tool calls
            assistant_message = {
                "role": "assistant",
                "content": response.choices[0].message.content or "",
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments
                        }
                    }
                    for tc in tool_calls
                ]
            }
            messages.append(assistant_message)

            # Process all tool calls
            tool_results = []
            for tool_call in tool_calls:
                tool_name = tool_call.function.name
                tool_input = json.loads(tool_call.function.arguments)
                typer.secho(f"\n🔧 Calling tool: {tool_name}", fg=typer.colors.MAGENTA)
                result = await self.call_mcp_tool(tool_name, tool_input)
                tool_results.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "name": tool_name,
                        "content": result,
                    }
                )

            messages.extend(tool_results)

            # Next response after tool execution
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                tools=tools,
                tool_choice="auto",
            )

        # Extract final response
        final_response = response.choices[0].message.content or ""
        typer.secho(f"\n🤖 Assistant: {final_response}", fg=typer.colors.GREEN)
        return final_response


@app.command()
async def interactive():
    """Start interactive CLI client for testing."""
    client = MCPClient()
    await client.start_server()

    typer.secho("\n" + "=" * 60, fg=typer.colors.CYAN)
    typer.secho("🎯 Recife Open Data MCP - Interactive Test Client", fg=typer.colors.CYAN)
    typer.secho("=" * 60, fg=typer.colors.CYAN)
    typer.secho("Type your questions in natural language. Examples:", fg=typer.colors.CYAN)
    typer.secho("  - How many schools are there?", fg=typer.colors.CYAN)
    typer.secho("  - List all schools in Santo Amaro", fg=typer.colors.CYAN)
    typer.secho("  - What's the total number of students?", fg=typer.colors.CYAN)
    typer.secho("Type 'exit' to quit.\n", fg=typer.colors.CYAN)

    while True:
        try:
            user_input = typer.prompt("You").strip()
            if user_input.lower() in ("exit", "quit", "q"):
                typer.secho("\n👋 Goodbye!", fg=typer.colors.CYAN)
                break
            if not user_input:
                continue
            await client.chat(user_input)
        except KeyboardInterrupt:
            typer.secho("\n\n👋 Goodbye!", fg=typer.colors.CYAN)
            break
        except Exception as e:
            typer.secho(f"\n❌ Error: {e}", fg=typer.colors.RED)


if __name__ == "__main__":
    # If no CLI args, run interactive mode directly to avoid Typer async issues
    if len(sys.argv) == 1:
        asyncio.run(interactive())
    else:
        app()
