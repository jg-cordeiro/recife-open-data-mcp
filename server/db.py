import asyncpg
from typing import Any, Dict, List, Optional
from .config import Settings


class Database:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._pool: Optional[asyncpg.Pool] = None

    async def init(self) -> None:
        if self._pool is None:
            self._pool = await asyncpg.create_pool(
                user=self.settings.db_user,
                password=self.settings.db_password,
                database=self.settings.db_name,
                host=self.settings.db_host,
                port=self.settings.db_port,
                min_size=1,
                max_size=10,
                command_timeout=self.settings.statement_timeout_ms / 1000,
                statement_cache_size=0,
            )

    async def close(self) -> None:
        if self._pool:
            await self._pool.close()
            self._pool = None

    async def fetch_rows(self, sql: str, timeout_ms: Optional[int] = None) -> List[Dict[str, Any]]:
        if self._pool is None:
            await self.init()
        assert self._pool is not None
        timeout_s = (timeout_ms or self.settings.statement_timeout_ms) / 1000
        async with self._pool.acquire() as conn:
            await conn.execute(f"SET LOCAL statement_timeout = {int(timeout_s * 1000)}")
            records = await conn.fetch(sql, timeout=timeout_s)
            return [dict(r) for r in records]

    async def fetch_schema_snapshot(self) -> str:
        if self._pool is None:
            await self.init()
        assert self._pool is not None
        query = """
        SELECT table_schema, table_name, column_name, data_type, is_nullable
        FROM information_schema.columns
        WHERE table_schema NOT IN ('pg_catalog', 'information_schema')
        ORDER BY table_schema, table_name, ordinal_position;
        """
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(query)
        parts: List[str] = []
        for row in rows:
            parts.append(
                f"{row['table_schema']}.{row['table_name']} :: {row['column_name']} ({row['data_type']}) null={row['is_nullable']}"
            )
        return "\n".join(parts)
