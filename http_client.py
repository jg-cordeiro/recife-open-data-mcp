"""
HTTP-based MCP client for testing via OpenRouter.
"""
import asyncio
import json
import logging
import os
from typing import Any, Dict, List, Optional

import httpx
import typer
from dotenv import load_dotenv
from openai import AsyncOpenAI
from braintrust import current_span, init_logger, traced

from server.config import Settings

load_dotenv()

app = typer.Typer(help="HTTP MCP client for testing via OpenRouter.")
settings = Settings.load()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
logger = logging.getLogger("mcp.http_client")


class HTTPMCPClient:
    """Client that communicates with MCP server via HTTP."""

    def __init__(self, mcp_base_url: str = "http://localhost:8000"):
        self.mcp_base_url = mcp_base_url.rstrip("/")
        self.settings = settings
        self.client = AsyncOpenAI(
            api_key=settings.openrouter_api_key,
            base_url="https://openrouter.ai/api/v1",
        )
        self.model = settings.openrouter_model
        self.http_client = httpx.AsyncClient(timeout=60.0)
        
        # Initialize Braintrust logger
        init_logger(
            project="Recife Open Data MCP",
            api_key=os.getenv("BRAINTRUST_API_KEY")
        )

    async def close(self):
        """Close HTTP client."""
        await self.http_client.aclose()

    async def check_server_health(self) -> bool:
        """Check if MCP server is healthy."""
        try:
            response = await self.http_client.get(f"{self.mcp_base_url}/health")
            response.raise_for_status()
            data = response.json()
            logger.info("health ok", extra={"response": data})
            return data.get("status") == "healthy"
        except Exception as e:
            typer.secho(f"❌ MCP server health check failed: {e}", fg=typer.colors.RED)
            logger.exception("health check failed")
            return False

    async def list_tools(self) -> List[Dict[str, Any]]:
        """Fetch available tools from MCP server."""
        response = await self.http_client.get(f"{self.mcp_base_url}/mcp/v1/tools")
        response.raise_for_status()
        data = response.json()
        logger.info("tools fetched", extra={"tools": [t.get("name") for t in data.get("tools", [])]})
        return data.get("tools", [])

    async def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> str:
        """Call a tool on the MCP server via HTTP."""
        typer.secho(f"🔧 Calling tool: {tool_name}", fg=typer.colors.MAGENTA)
        # Use key 'tool_args' to avoid clashing with LogRecord 'args'
        logger.info("calling tool", extra={"tool": tool_name, "tool_args": arguments})
        
        try:
            response = await self.http_client.post(
                f"{self.mcp_base_url}/mcp/v1/tools/execute",
                json={"name": tool_name, "arguments": arguments},
            )
            response.raise_for_status()
            result = response.json()
            logger.info("tool response", extra={"tool": tool_name, "result_preview": json.dumps(result)[:400]})
            
            # Extract text from MCP response format
            if "content" in result and len(result["content"]) > 0:
                content = result["content"][0].get("text")
                if content:
                    return content
            
            # Fallback for empty or malformed responses
            logger.warning("empty tool response", extra={"tool": tool_name})
            return json.dumps({"message": "Tool executed but returned no data", "tool": tool_name})
        except Exception as e:
            logger.exception("tool call failed", extra={"tool": tool_name})
            return json.dumps({"error": str(e), "tool": tool_name})

    def _convert_tools_to_openai_format(self, mcp_tools: List[Dict]) -> List[Dict]:
        """Convert MCP tool format to OpenAI function calling format."""
        openai_tools = []
        for tool in mcp_tools:
            openai_tools.append({
                "type": "function",
                "function": {
                    "name": tool["name"],
                    "description": tool["description"],
                    "parameters": tool.get("inputSchema", {}),
                },
            })
        return openai_tools

    @traced(type="llm", name="HTTP MCP Client Chat", notrace_io=True)
    async def chat(self, user_message: str) -> str:
        """Send a message to LLM and handle tool calls via MCP server."""
        typer.secho(f"\n👤 User: {user_message}", fg=typer.colors.CYAN)
        logger.info("chat start", extra={"user_message": user_message})

        # Fetch available tools from MCP server
        mcp_tools = await self.list_tools()
        tools = self._convert_tools_to_openai_format(mcp_tools)

        messages = [{"role": "user", "content": user_message}]

        # First LLM request
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            tools=tools,
            tool_choice="auto",
        )
        logger.info("llm response", extra={"finish_reason": response.choices[0].finish_reason})
        
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
                logger.warning("no tool calls found")
                break
                
            logger.info("llm requested tools", extra={"tool_names": [tc.function.name for tc in tool_calls]})
            
            # Add assistant message with tool calls
            messages.append({
                "role": "assistant",
                "content": response.choices[0].message.content or "",
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                    for tc in tool_calls
                ],
            })

            # Execute all tool calls via HTTP MCP server
            for tool_call in tool_calls:
                tool_name = tool_call.function.name
                tool_args = json.loads(tool_call.function.arguments)
                
                typer.secho(f"📊 Executing: {tool_name}({list(tool_args.keys())})", fg=typer.colors.BLUE)
                # Avoid reserved LogRecord key 'args'
                logger.info("executing tool", extra={"tool": tool_name, "tool_args": tool_args})
                
                # Call MCP server via HTTP
                result = await self.call_tool(tool_name, tool_args)
                logger.info("tool result received", extra={"tool": tool_name, "result_preview": result[:400]})
                
                # Add tool result to messages
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": result,
                })

            # Next LLM request with tool results
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                tools=tools,
                tool_choice="auto",
            )
            logger.info("llm response", extra={"finish_reason": response.choices[0].finish_reason})
            
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
            logger.warning("max tool iterations reached", extra={"iterations": tool_call_count})
            final_response = "Desculpe, precisei usar muitas ferramentas e não consegui completar a resposta. Tente fazer uma pergunta mais específica."
        else:
            # Extract final response
            final_response = response.choices[0].message.content or ""
        
        # Handle empty final response
        if not final_response or final_response.strip() == "":
            final_response = "Desculpe, não consegui gerar uma resposta. Por favor, tente reformular sua pergunta."
            logger.warning("empty final response from llm")
        
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
        logger.info("chat done", extra={"final_response_preview": final_response[:400]})
        return final_response


@app.command()
def interactive(
    mcp_url: str = typer.Option(
        "http://localhost:8000",
        "--mcp-url",
        help="Base URL of the MCP HTTP server",
    )
):
    """Start interactive CLI client using HTTP transport."""
    asyncio.run(_interactive_async(mcp_url))


async def _interactive_async(mcp_url: str):
    """Async implementation of interactive mode."""
    client = HTTPMCPClient(mcp_url)

    # Check server health
    typer.secho(f"\n🔍 Checking MCP server at {mcp_url}...", fg=typer.colors.CYAN)
    if not await client.check_server_health():
        typer.secho("❌ MCP server is not available. Please start it first.", fg=typer.colors.RED)
        typer.secho(f"   Run: uvicorn server.http_server:app --reload --port 8000", fg=typer.colors.YELLOW)
        return

    typer.secho("✅ MCP server is healthy!", fg=typer.colors.GREEN)

    typer.secho("\n" + "=" * 60, fg=typer.colors.CYAN)
    typer.secho("🎯 Recife Open Data MCP - HTTP Client", fg=typer.colors.CYAN)
    typer.secho("=" * 60, fg=typer.colors.CYAN)
    typer.secho("Type your questions in natural language. Examples:", fg=typer.colors.CYAN)
    typer.secho("  - Quantas escolas existem?", fg=typer.colors.CYAN)
    typer.secho("  - Liste todas as escolas de Santo Amaro", fg=typer.colors.CYAN)
    typer.secho("  - Qual é o total de alunos?", fg=typer.colors.CYAN)
    typer.secho("Type 'exit' to quit.\n", fg=typer.colors.CYAN)
    typer.secho("Commands:", fg=typer.colors.CYAN)
    typer.secho("  :tools             - list available tools", fg=typer.colors.CYAN)
    typer.secho("  :tables            - list database tables", fg=typer.colors.CYAN)
    typer.secho("  :schemas           - list database schemas", fg=typer.colors.CYAN)
    typer.secho("  :describe <table>  - describe columns of a table", fg=typer.colors.CYAN)
    typer.secho("  :search <keyword>  - search tables/columns by keyword\n", fg=typer.colors.CYAN)

    try:
        while True:
            try:
                user_input = typer.prompt("You").strip()
                if user_input.lower() in ("exit", "quit", "q"):
                    typer.secho("\n👋 Goodbye!", fg=typer.colors.CYAN)
                    break
                if not user_input:
                    continue
                # Built-in commands to exercise HTTP tools directly
                if user_input.startswith(":"):
                    parts = user_input.split()
                    cmd = parts[0]
                    arg = " ".join(parts[1:]) if len(parts) > 1 else ""

                    if cmd == ":tools":
                        tools = await client.list_tools()
                        typer.echo(json.dumps({"tools": [t["name"] for t in tools]}, indent=2, ensure_ascii=False))
                        continue
                    if cmd == ":tables":
                        res = await client.call_tool("list_tables", {})
                        typer.echo(res)
                        continue
                    if cmd == ":schemas":
                        res = await client.call_tool("list_databases", {})
                        typer.echo(res)
                        continue
                    if cmd == ":describe":
                        if not arg:
                            typer.secho("Usage: :describe <table>", fg=typer.colors.YELLOW)
                        else:
                            res = await client.call_tool("describe_table", {"table_name": arg})
                            typer.echo(res)
                        continue
                    if cmd == ":search":
                        if not arg:
                            typer.secho("Usage: :search <keyword>", fg=typer.colors.YELLOW)
                        else:
                            res = await client.call_tool("search_schema", {"search_term": arg})
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
    finally:
        await client.close()


if __name__ == "__main__":
    app()
