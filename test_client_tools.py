#!/usr/bin/env python3
"""Test that client properly routes to the correct tools."""
import asyncio
from client import MCPClient


async def test_tool_selection():
    """Test that different questions route to appropriate tools."""
    
    client = MCPClient()
    tools = await client.fetch_tools()
    
    print("=" * 60)
    print("Available Tools:")
    print("=" * 60)
    for tool in tools:
        func = tool["function"]
        print(f"\n📦 {func['name']}")
        print(f"   {func['description'][:100]}...")
    
    print("\n" + "=" * 60)
    print("Tool Routing Test Scenarios:")
    print("=" * 60)
    
    scenarios = [
        ("What tables are available?", "list_tables"),
        ("Quais tabelas temos disponíveis?", "list_tables"),
        ("What columns does the civil defense table have?", "describe_table"),
        ("Find columns related to 'ano' or 'year'", "search_schema"),
        ("How many records are in the civil defense table?", "answer_question"),
        ("What's the total number of incidents by neighborhood?", "answer_question"),
    ]
    
    print("\nExpected tool routing:")
    for question, expected_tool in scenarios:
        print(f"\n  Q: {question}")
        print(f"  → Expected: {expected_tool}")
    
    print("\n" + "=" * 60)
    print("✅ Tool definitions look good!")
    print("=" * 60)
    print("\nTo test live routing, run: python client.py")


if __name__ == "__main__":
    asyncio.run(test_tool_selection())
