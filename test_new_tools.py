#!/usr/bin/env python3
"""Test script for new MCP schema exploration tools."""
import asyncio
from server.config import Settings
from server.db import Database


async def main():
    settings = Settings.load()
    db = Database(settings)
    await db.init()
    
    print("=" * 60)
    print("Testing list_databases()")
    print("=" * 60)
    schemas = await db.list_databases()
    print(f"Found {len(schemas)} schemas:")
    for schema in schemas:
        print(f"  - {schema}")
    
    print("\n" + "=" * 60)
    print("Testing list_tables()")
    print("=" * 60)
    tables = await db.list_tables()
    print(f"Found {len(tables)} tables:")
    for table in tables:
        print(f"  - {table['full_name']} (schema: {table['schema']}, table: {table['table']})")
    
    print("\n" + "=" * 60)
    print("Testing describe_table('atendimentos-defesa-civil_consolidated')")
    print("=" * 60)
    columns = await db.describe_table('atendimentos-defesa-civil_consolidated')
    print(f"Found {len(columns)} columns:")
    for col in columns:
        print(f"  - {col['column']}: {col['type']} (nullable: {col['nullable']})")
    
    print("\n" + "=" * 60)
    print("Testing search_schema('ano')")
    print("=" * 60)
    results = await db.search_schema('ano')
    print(f"Found {len(results)} matches:")
    for result in results[:5]:  # Show first 5
        print(f"  - {result['full_reference']}")
    
    print("\n" + "=" * 60)
    print("Testing search_schema('defesa')")
    print("=" * 60)
    results = await db.search_schema('defesa')
    print(f"Found {len(results)} matches:")
    for result in results[:5]:  # Show first 5
        print(f"  - {result['full_reference']}")
    
    print("\n" + "=" * 60)
    print("Testing actual query with proper quoting")
    print("=" * 60)
    sql = 'SELECT COUNT(DISTINCT "Ano") AS distinct_years FROM "public"."atendimentos-defesa-civil_consolidated"'
    rows = await db.fetch_rows(sql)
    print(f"Query: {sql}")
    print(f"Result: {rows}")
    
    await db.close()
    print("\n✅ All tests completed successfully!")


if __name__ == "__main__":
    asyncio.run(main())
