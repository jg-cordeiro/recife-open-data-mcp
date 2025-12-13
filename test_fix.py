#!/usr/bin/env python3
import asyncio
from client import MCPClient

async def test():
    client = MCPClient()
    await client.start_server()
    result = await client.chat("quantos anos de situaçao escolar temos?")
    print("\n" + "="*60)
    print(f"Final result: {result}")

if __name__ == "__main__":
    asyncio.run(test())
