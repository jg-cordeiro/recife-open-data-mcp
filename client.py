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
                    "name": "execute_sql",
                    "description": "Execute a read-only SQL query with timeout and row limit.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "sql": {"type": "string", "description": "SQL query to execute"}
                        },
                        "required": ["sql"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "answer_question",
                    "description": "Convert a natural language question into SQL, run it, and return the result.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "question": {
                                "type": "string",
                                "description": "Natural language question about the data",
                            }
                        },
                        "required": ["question"],
                    },
                },
            },
        ]

    async def call_mcp_tool(self, tool_name: str, tool_input: dict) -> str:
        """Call a tool via MCP server."""
        if tool_name == "execute_sql":
            sql = tool_input.get("sql", "")
            typer.secho(f"📊 Executing SQL: {sql[:80]}...", fg=typer.colors.BLUE)
            # Import here to avoid circular imports
            from server.db import Database
            from server.sql_guard import ensure_limit, ensure_read_only

            db = Database(self.settings)
            await db.init()
            ensure_read_only(sql)
            limited = ensure_limit(sql, self.settings.max_result_rows)
            rows = await db.fetch_rows(limited)
            await db.close()
            result = {"sql": limited, "row_count": len(rows), "rows": rows}
            return json.dumps(result)
        elif tool_name == "answer_question":
            question = tool_input.get("question", "")
            typer.secho(f"❓ Question: {question}", fg=typer.colors.BLUE)
            # Import here to avoid circular imports
            from server.db import Database
            from server.sql_guard import ensure_limit, ensure_read_only
            from server.openrouter_client import OpenRouterClient

            db = Database(self.settings)
            await db.init()
            llm = OpenRouterClient(self.settings)
            schema_text = await db.fetch_schema_snapshot()
            sql_first = await llm.generate_sql(question, schema_text)
            typer.secho(f"🔍 Generated SQL: {sql_first[:100]}...", fg=typer.colors.YELLOW)
            try:
                ensure_read_only(sql_first)
                limited = ensure_limit(sql_first, self.settings.max_result_rows)
                rows = await db.fetch_rows(limited)
                result = {"sql": limited, "row_count": len(rows), "rows": rows}
                await db.close()
                return json.dumps(result)
            except Exception as first_error:
                typer.secho(f"⚠️  First SQL attempt failed: {first_error}", fg=typer.colors.YELLOW)
                sql_second = await llm.generate_sql(question, schema_text, previous_error=str(first_error))
                typer.secho(f"🔄 Retrying with revised SQL: {sql_second[:100]}...", fg=typer.colors.YELLOW)
                ensure_read_only(sql_second)
                limited = ensure_limit(sql_second, self.settings.max_result_rows)
                rows = await db.fetch_rows(limited)
                result = {"sql": limited, "row_count": len(rows), "rows": rows}
                await db.close()
                return json.dumps(result)
        else:
            return json.dumps({"error": f"Unknown tool: {tool_name}"})

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
            messages.append({"role": "assistant", "content": response.choices[0].message.content or ""})
            messages[-1]["tool_calls"] = tool_calls

            # Process all tool calls
            tool_results = []
            for tool_call in tool_calls:
                tool_name = tool_call.function.name
                tool_input = json.loads(tool_call.function.arguments)
                typer.secho(f"\n🔧 Calling tool: {tool_name}", fg=typer.colors.MAGENTA)
                result = await self.call_mcp_tool(tool_name, tool_input)
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": tool_call.id,
                        "content": result,
                    }
                )

            messages.append({"role": "user", "content": tool_results})

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
    app()
