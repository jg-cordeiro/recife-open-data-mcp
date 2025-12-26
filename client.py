import json
import os
import subprocess
import sys
from pathlib import Path

from openai import AsyncOpenAI
import asyncio
import typer
from dotenv import load_dotenv
from braintrust import current_span, init_logger, traced
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
        
        # Initialize Braintrust logger
        init_logger(
            project="Recife Open Data MCP",
            api_key=os.getenv("BRAINTRUST_API_KEY")
        )

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
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "required": {
                                "type": "boolean",
                                "description": "Must be true; this tool is required before generating SQL."
                            }
                        },
                        "required": ["required"],
                    },
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
                                "description": "Name of the table to describe (without schema, e.g., 'situação_final_dos_alunos_por_período_letivo')",
                            },
                            "required": {
                                "type": "boolean",
                                "description": "Must be true; this tool is required before generating SQL."
                            }
                        },
                        "required": ["table_name", "required"],
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
                return json.dumps({"message": f"Found {len(tables)} tables", "tables": tables})
            elif tool_name == "describe_table":
                table_name = tool_input.get("table_name", "")
                typer.secho(f"📄 Describing table: {table_name}", fg=typer.colors.BLUE)
                columns = await db.describe_table(table_name)
                if not columns:
                    return json.dumps({"error": f"Table '{table_name}' not found", "columns": []})
                return json.dumps({"table": table_name, "column_count": len(columns), "columns": columns})
            elif tool_name == "search_schema":
                search_term = tool_input.get("search_term", "")
                typer.secho(f"🔍 Searching schema for: {search_term}", fg=typer.colors.BLUE)
                results = await db.search_schema(search_term)
                if not results:
                    return json.dumps({"message": f"No tables or columns found matching '{search_term}'", "results": []})
                return json.dumps({"message": f"Found {len(results)} matches", "results": results})
            elif tool_name == "list_databases":
                typer.secho("🗄️  Listing databases/schemas...", fg=typer.colors.BLUE)
                schemas = await db.list_databases()
                return json.dumps({"message": f"Found {len(schemas)} schemas", "schemas": schemas})
            elif tool_name == "execute_sql":
                sql = tool_input.get("sql", "")
                typer.secho(f"📊 Executing SQL: {sql[:80]}...", fg=typer.colors.BLUE)
                ensure_read_only(sql)
                limited = ensure_limit(sql, self.settings.max_result_rows)
                rows = await db.fetch_rows(limited)
                result = {"sql": limited, "row_count": len(rows), "rows": rows}
                return json.dumps(result)
            else:
                return json.dumps({"error": f"Unknown tool: {tool_name}"})
        finally:
            await db.close()

    @traced(type="llm", name="MCP Client Chat", notrace_io=True)
    async def chat(self, user_message: str) -> str:
        """Send a message to Claude via OpenRouter and process tool calls."""
        typer.secho(f"\n👤 User: {user_message}", fg=typer.colors.CYAN)

        # Pré-busca: obter tabelas e descrições para dar contexto imediato à LLM
        tables = await self.fetch_tools()
        messages: list = []

        system_prompt = (
            "Você é um assistente MCP que responde em português e decide o uso de ferramentas para acessar dados públicos da Prefeitura do Recife no DuckDB.\n"
            "- SEMPRE comece chamando list_tables. Não gere SQL antes de listar.\n"
            "- Escolha a tabela e chame describe_table para pegar os nomes exatos de colunas. Não invente colunas ou acentos; use os nomes retornados (ex.: Ano, Ocorrencia, Grau_de_Risco, situacao_nome, ano, escola, sexo).\n"
            "- Use search_schema apenas se precisar achar onde está um campo.\n"
            "- Consulte os dicionários via resources (resource://dicionario-atendimentos e resource://dicionario-situacao-final) quando precisar confirmar nomes/colunas.\n"
            "- Gere o SQL explicitamente (sem tool especializada) e execute usando execute_sql.\n"
            "- Trate campos de ano como texto (sem casts) e mantenha aspas duplas em tabelas/colunas com hífen ou acentuação.\n"
            "- Siga exatamente os nomes retornados pelas ferramentas; se uma coluna faltar, chame describe_table e refaça o SQL."
        )

        messages.extend([
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ])

        # Adiciona contexto de schema curto (list_tables + describe_table de cada tabela encontrada)
        try:
            tables_list = json.loads(await self.call_mcp_tool("list_tables", {"required": True}))
            table_names = [t.get("table") for t in tables_list.get("tables", []) if t.get("table")]
            schema_context = {"tables": tables_list.get("tables", [])}
            for tname in table_names:
                desc_raw = await self.call_mcp_tool("describe_table", {"table_name": tname, "required": True})
                try:
                    desc_json = json.loads(desc_raw)
                except Exception:
                    desc_json = {"error": desc_raw}
                schema_context[tname] = desc_json
            messages.append({"role": "user", "content": f"Contexto de schema (não invente nada além disto):\n{json.dumps(schema_context, ensure_ascii=False)}"})
        except Exception as e:  # pylint: disable=broad-except
            typer.secho(f"⚠️ Falha ao obter contexto de schema: {e}", fg=typer.colors.YELLOW)

        tools = await self.fetch_tools()

        # First request with tools
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            tools=tools,
            tool_choice="auto",
        )
        
        # Log initial LLM call
        usage = response.usage or None
        current_span().log(
            input={"user_message": user_message, "tools_available": len(tools)},
            metrics={
                "prompt_tokens": usage.prompt_tokens if usage else 0,
                "completion_tokens": usage.completion_tokens if usage else 0,
                "total_tokens": usage.total_tokens if usage else 0,
            },
            metadata={
                "model": self.model,
                "finish_reason": response.choices[0].finish_reason,
                "has_tool_calls": response.choices[0].finish_reason == "tool_calls"
            }
        )

        # Tool use loop with max iterations
        tool_call_count = 0
        MAX_TOOL_ITERATIONS = 10
        
        while response.choices[0].finish_reason == "tool_calls" and tool_call_count < MAX_TOOL_ITERATIONS:
            tool_call_count += 1
            tool_calls = response.choices[0].message.tool_calls
            
            if not tool_calls:
                typer.secho("⚠️  No tool calls found, breaking loop", fg=typer.colors.YELLOW)
                break
            
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
            
            # Log follow-up LLM call
            usage = response.usage or None
            current_span().log(
                metrics={
                    "prompt_tokens": usage.prompt_tokens if usage else 0,
                    "completion_tokens": usage.completion_tokens if usage else 0,
                    "total_tokens": usage.total_tokens if usage else 0,
                },
                metadata={
                    "tool_call_iteration": tool_call_count,
                    "tools_called": [tc.function.name for tc in tool_calls],
                    "finish_reason": response.choices[0].finish_reason,
                }
            )

        # Check if we hit max iterations
        if tool_call_count >= MAX_TOOL_ITERATIONS:
            typer.secho(f"\n⚠️  Reached max tool iterations ({MAX_TOOL_ITERATIONS})", fg=typer.colors.YELLOW)
            final_response = "Desculpe, precisei usar muitas ferramentas e não consegui completar a resposta. Tente fazer uma pergunta mais específica."
        else:
            # Extract final response
            final_response = response.choices[0].message.content or ""
        
        # Handle empty final response
        if not final_response or final_response.strip() == "":
            final_response = "Desculpe, não consegui gerar uma resposta. Por favor, tente reformular sua pergunta."
            typer.secho("⚠️  Empty response from LLM", fg=typer.colors.YELLOW)
        
        # Log final output
        current_span().log(
            output={"final_response": final_response},
            metadata={
                "total_tool_calls": tool_call_count,
                "success": bool(final_response),
                "hit_max_iterations": tool_call_count >= MAX_TOOL_ITERATIONS
            }
        )
        
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
    typer.secho("Commands:", fg=typer.colors.CYAN)
    typer.secho("  :tools             - list available tools", fg=typer.colors.CYAN)
    typer.secho("  :tables            - list database tables", fg=typer.colors.CYAN)
    typer.secho("  :schemas           - list database schemas", fg=typer.colors.CYAN)
    typer.secho("  :describe <table>  - describe columns of a table", fg=typer.colors.CYAN)
    typer.secho("  :search <keyword>  - search tables/columns by keyword\n", fg=typer.colors.CYAN)

    while True:
        try:
            user_input = typer.prompt("You").strip()
            if user_input.lower() in ("exit", "quit", "q"):
                typer.secho("\n👋 Goodbye!", fg=typer.colors.CYAN)
                break
            if not user_input:
                continue
            # Built-in commands to exercise local tools directly
            if user_input.startswith(":"):
                parts = user_input.split()
                cmd = parts[0]
                arg = " ".join(parts[1:]) if len(parts) > 1 else ""

                if cmd == ":tools":
                    tools = await client.fetch_tools()
                    typer.echo(json.dumps({"tools": [t["function"]["name"] for t in tools]}, indent=2, ensure_ascii=False))
                    continue
                if cmd == ":tables":
                    res = await client.call_mcp_tool("list_tables", {})
                    typer.echo(res)
                    continue
                if cmd == ":schemas":
                    res = await client.call_mcp_tool("list_databases", {})
                    typer.echo(res)
                    continue
                if cmd == ":describe":
                    if not arg:
                        typer.secho("Usage: :describe <table>", fg=typer.colors.YELLOW)
                    else:
                        res = await client.call_mcp_tool("describe_table", {"table_name": arg})
                        typer.echo(res)
                    continue
                if cmd == ":search":
                    if not arg:
                        typer.secho("Usage: :search <keyword>", fg=typer.colors.YELLOW)
                    else:
                        res = await client.call_mcp_tool("search_schema", {"search_term": arg})
                        typer.echo(res)
                    continue

                typer.secho("Unknown command. Try :tools, :tables, :schemas, :describe, :search", fg=typer.colors.YELLOW)
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
