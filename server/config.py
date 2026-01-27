import os
from dataclasses import dataclass
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()


@dataclass
class Settings:
    openrouter_api_key: str
    openrouter_model: str
    db_path: str
    max_result_rows: int
    http_port: int

    @classmethod
    def load(cls) -> "Settings":
        db_dir = Path(os.environ.get("DUCKDB_DATA_DIR", "./data"))
        try:
            db_dir.mkdir(parents=True, exist_ok=True)
        except PermissionError:
            # Read-only filesystems (e.g., managed runtimes) may block mkdir; continue using the path
            pass
        db_path = str(db_dir / "recife.duckdb")
        return cls(
            openrouter_api_key=os.environ.get("OPENROUTER_API_KEY", ""),
            openrouter_model=os.environ.get("OPENROUTER_MODEL", "google/gemini-2.5-flash"),
            db_path=db_path,
            max_result_rows=int(os.environ.get("MAX_RESULT_ROWS", "200")),
            http_port=int(os.environ.get("HTTP_PORT", "8000")),
        )

    def require_api_key(self) -> None:
        if not self.openrouter_api_key:
            raise RuntimeError("OPENROUTER_API_KEY is required to run the MCP server.")
