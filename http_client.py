"""
HTTP-based MCP client for testing via OpenRouter.
"""
import asyncio
import json
import logging
from typing import Any, Dict, List, Optional

import httpx
import typer
from dotenv import load_dotenv
from openai import AsyncOpenAI

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
        
        response = await self.http_client.post(
            f"{self.mcp_base_url}/mcp/v1/tools/execute",
            json={"name": tool_name, "arguments": arguments},
        )
        response.raise_for_status()
        result = response.json()
        logger.info("tool response", extra={"tool": tool_name, "result_preview": json.dumps(result)[:400]})
        
        # Extract text from MCP response format
        if "content" in result and len(result["content"]) > 0:
            return result["content"][0].get("text", str(result))
        return str(result)

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

        # Tool use loop
        while response.choices[0].finish_reason == "tool_calls":
            tool_calls = response.choices[0].message.tool_calls
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

        # Extract final response
        final_response = response.choices[0].message.content or ""
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

    try:
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
    finally:
        await client.close()


if __name__ == "__main__":
    app()
