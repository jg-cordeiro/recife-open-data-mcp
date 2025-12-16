"""
Entry point for FastMCP deployments.

Exposes the FastMCP server instance using standard variable names
(`mcp`, `server`, `app`) so runtimes that inspect the module can find it.
"""
from server.main import app as mcp

# Aliases expected by runtimes
server = mcp
app = mcp

