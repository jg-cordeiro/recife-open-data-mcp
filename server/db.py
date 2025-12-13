import duckdb
from typing import Any, Dict, List, Optional
from .config import Settings


class Database:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._conn: Optional[duckdb.DuckDBPyConnection] = None

    async def init(self) -> None:
        if self._conn is None:
            self._conn = duckdb.connect(self.settings.db_path, read_only=False)
            # Enable execution in read-only context where needed
            self._conn.execute("SET threads = 4")
            self._conn.execute("SET memory_limit = '4GB'")

    async def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    async def fetch_rows(self, sql: str, timeout_ms: Optional[int] = None) -> List[Dict[str, Any]]:
        if self._conn is None:
            await self.init()
        assert self._conn is not None
        # DuckDB doesn't have per-statement timeout, so we just execute
        result = self._conn.execute(sql).fetchall()
        # Convert to list of dicts
        columns = [desc[0] for desc in self._conn.description] if self._conn.description else []
        rows = []
        for row in result:
            row_dict = {col: val for col, val in zip(columns, row)}
            rows.append(row_dict)
        return rows

    async def fetch_schema_snapshot(self) -> str:
        if self._conn is None:
            await self.init()
        assert self._conn is not None
        # Get all tables and their column info
        query = """
        SELECT table_schema, table_name, column_name, data_type
        FROM information_schema.columns
        WHERE table_schema NOT IN ('information_schema', 'pg_catalog', 'memory')
        ORDER BY table_schema, table_name, ordinal_position;
        """
        rows = self._conn.execute(query).fetchall()
        parts: List[str] = []
        for row in rows:
            table_schema, table_name, column_name, data_type = row
            parts.append(
                f"{table_schema}.{table_name} :: {column_name} ({data_type})"
            )
        return "\n".join(parts)
