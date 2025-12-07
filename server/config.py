import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


@dataclass
class Settings:
    openrouter_api_key: str
    openrouter_model: str
    db_host: str
    db_port: int
    db_name: str
    db_user: str
    db_password: str
    statement_timeout_ms: int
    max_result_rows: int
    http_port: int

    @classmethod
    def load(cls) -> "Settings":
        return cls(
            openrouter_api_key=os.environ.get("OPENROUTER_API_KEY", ""),
            openrouter_model=os.environ.get("OPENROUTER_MODEL", "openai/gpt-5.1-codex-max"),
            db_host=os.environ.get("POSTGRES_HOST", "localhost"),
            db_port=int(os.environ.get("POSTGRES_PORT", "5432")),
            db_name=os.environ.get("POSTGRES_DB", "recife_open_data"),
            db_user=os.environ.get("POSTGRES_USER", "recife"),
            db_password=os.environ.get("POSTGRES_PASSWORD", "recife"),
            statement_timeout_ms=int(os.environ.get("STATEMENT_TIMEOUT_MS", "10000")),
            max_result_rows=int(os.environ.get("MAX_RESULT_ROWS", "200")),
                    http_port=int(os.environ.get("HTTP_PORT", "8000")),
        )

    def require_api_key(self) -> None:
        if not self.openrouter_api_key:
            raise RuntimeError("OPENROUTER_API_KEY is required to run the MCP server.")
