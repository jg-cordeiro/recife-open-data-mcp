import duckdb
from pathlib import Path
from typing import Any, Dict, List, Optional
from .config import Settings


class Database:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._conn: Optional[duckdb.DuckDBPyConnection] = None

    async def init(self) -> None:
        if self._conn is not None:
            return

        db_path = Path(self.settings.db_path)

        def _connect(path: Path):
            # Using read_only=False after copying to a writable location to avoid lock issues
            return duckdb.connect(str(path), read_only=False)

        try:
            self._conn = _connect(db_path)
        except Exception as exc:  # pragma: no cover - runtime fallback
            # Fallback for read-only filesystems (e.g., FastMCP/Lambda layers)
            if "Read-only file system" in str(exc) or "read-only" in str(exc).lower():
                fallback_dir = Path("/tmp/recife-duckdb")
                fallback_dir.mkdir(parents=True, exist_ok=True)
                fallback_path = fallback_dir / "recife.duckdb"
                if db_path.exists():
                    import shutil
                    shutil.copyfile(db_path, fallback_path)
                self.settings.db_path = str(fallback_path)
                self._conn = _connect(fallback_path)
            else:
                raise

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
        # Validação de schema: EXPLAIN detecta tabela/coluna inexistente antes de executar
        try:
            self._conn.execute(f"EXPLAIN {sql}")
        except Exception as exc:
            raise ValueError(f"SQL inválido (tabela/coluna não encontrada). Use list_tables/describe_table e corrija os nomes. Erro: {exc}") from exc

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

    async def list_tables(self) -> List[Dict[str, str]]:
        """List all tables with their schema."""
        if self._conn is None:
            await self.init()
        assert self._conn is not None
        query = """
        SELECT table_schema, table_name
        FROM information_schema.tables
        WHERE table_schema NOT IN ('information_schema', 'pg_catalog', 'memory')
        ORDER BY table_schema, table_name;
        """
        rows = self._conn.execute(query).fetchall()
        return [{"schema": row[0], "table": row[1], "full_name": f'"{row[0]}"."{row[1]}"'} for row in rows]

    async def describe_table(self, table_name: str) -> List[Dict[str, str]]:
        """Get detailed column information for a specific table."""
        if self._conn is None:
            await self.init()
        assert self._conn is not None
        query = """
        SELECT column_name, data_type, is_nullable
        FROM information_schema.columns
        WHERE table_name = ?
        AND table_schema NOT IN ('information_schema', 'pg_catalog', 'memory')
        ORDER BY ordinal_position;
        """
        rows = self._conn.execute(query, [table_name]).fetchall()
        return [{"column": row[0], "type": row[1], "nullable": row[2]} for row in rows]

    async def search_schema(self, search_term: str) -> List[Dict[str, str]]:
        """Search for tables or columns matching a term."""
        if self._conn is None:
            await self.init()
        assert self._conn is not None
        query = """
        SELECT table_schema, table_name, column_name, data_type
        FROM information_schema.columns
        WHERE table_schema NOT IN ('information_schema', 'pg_catalog', 'memory')
        AND (LOWER(table_name) LIKE ? OR LOWER(column_name) LIKE ?)
        ORDER BY table_schema, table_name, ordinal_position;
        """
        search_pattern = f"%{search_term.lower()}%"
        rows = self._conn.execute(query, [search_pattern, search_pattern]).fetchall()
        return [
            {
                "schema": row[0],
                "table": row[1],
                "column": row[2],
                "type": row[3],
                "full_reference": f'"{row[0]}"."{row[1]}"."{row[2]}"'
            }
            for row in rows
        ]

    async def list_databases(self) -> List[str]:
        """List all database schemas."""
        if self._conn is None:
            await self.init()
        assert self._conn is not None
        query = """
        SELECT DISTINCT table_schema
        FROM information_schema.tables
        WHERE table_schema NOT IN ('information_schema', 'pg_catalog', 'memory')
        ORDER BY table_schema;
        """
        rows = self._conn.execute(query).fetchall()
        return [row[0] for row in rows]
