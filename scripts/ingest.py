import csv
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional

import psycopg
import typer
from psycopg import sql
from dotenv import load_dotenv

from server.config import Settings

load_dotenv()
app = typer.Typer(help="Ingest CSV datasets into Postgres for the MCP server.")


@dataclass
class ColumnSpec:
    name: str
    type: str


BOOL_VALUES = {"true", "false", "t", "f", "yes", "no"}


def _looks_int(value: str) -> bool:
    try:
        int(value)
        return True
    except Exception:
        return False


def _looks_float(value: str) -> bool:
    try:
        float(value)
        return True
    except Exception:
        return False


def _looks_bool(value: str) -> bool:
    return value.lower() in BOOL_VALUES


def _looks_date(value: str) -> bool:
    try:
        datetime.fromisoformat(value)
        return True
    except Exception:
        return False


def infer_columns(csv_path: Path, sample_rows: int) -> List[ColumnSpec]:
    with csv_path.open("r", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        columns = reader.fieldnames or []
        samples = list(row for _, row in zip(range(sample_rows), reader))
    specs: List[ColumnSpec] = []
    for col in columns:
        values = [row[col] for row in samples if row[col] not in ("", None)]
        if values and all(_looks_int(v) for v in values):
            pg_type = "integer"
        elif values and all(_looks_float(v) for v in values):
            pg_type = "double precision"
        elif values and all(_looks_bool(v) for v in values):
            pg_type = "boolean"
        elif values and all(_looks_date(v) for v in values):
            pg_type = "timestamp"
        else:
            pg_type = "text"
        specs.append(ColumnSpec(name=col, type=pg_type))
    return specs


def read_descriptor(descriptor: Path) -> tuple[str, Optional[List[ColumnSpec]]]:
    data = json.loads(descriptor.read_text(encoding="utf-8"))
    table = data.get("table") or data.get("name")
    if not table:
        raise typer.BadParameter("Descriptor must include 'table' or 'name'.")
    cols = data.get("columns")
    if cols:
        return table, [ColumnSpec(name=c["name"], type=c["type"]) for c in cols]
    return table, None


def create_table(conn: psycopg.Connection, schema: str, table: str, columns: List[ColumnSpec], replace: bool) -> None:
    with conn.cursor() as cur:
        if replace:
            cur.execute(
                sql.SQL("DROP TABLE IF EXISTS {}.{} CASCADE;").format(
                    sql.Identifier(schema), sql.Identifier(table)
                )
            )
        columns_sql = [sql.SQL("{} {}").format(sql.Identifier(c.name), sql.SQL(c.type)) for c in columns]
        create_stmt = sql.SQL("CREATE TABLE IF NOT EXISTS {}.{} ({})").format(
            sql.Identifier(schema), sql.Identifier(table), sql.SQL(", ").join(columns_sql)
        )
        cur.execute(create_stmt)
        conn.commit()


def copy_csv(conn: psycopg.Connection, schema: str, table: str, csv_path: Path) -> None:
    with conn.cursor() as cur:
        copy_sql = sql.SQL("COPY {}.{} FROM STDIN WITH CSV HEADER").format(
            sql.Identifier(schema), sql.Identifier(table)
        )
        with cur.copy(copy_sql) as copy, csv_path.open("r", encoding="utf-8") as fh:
            copy.write(fh.read())
        conn.commit()


@app.command()
def load(
    descriptor: Path = typer.Argument(..., help="JSON descriptor with table metadata."),
    csv_file: Path = typer.Argument(..., help="CSV file to ingest."),
    schema: str = typer.Option("public", help="Target schema."),
    replace: bool = typer.Option(True, help="Drop and recreate the table before loading."),
    sample_rows: int = typer.Option(1000, help="Rows to sample for type inference if columns missing."),
):
    settings = Settings.load()
    conninfo = psycopg.conninfo.make_conninfo(
        host=settings.db_host,
        port=settings.db_port,
        dbname=settings.db_name,
        user=settings.db_user,
        password=settings.db_password,
    )
    table, columns = read_descriptor(descriptor)
    if columns is None:
        columns = infer_columns(csv_file, sample_rows)
    conn = psycopg.connect(conninfo)
    create_table(conn, schema, table, columns, replace)
    copy_csv(conn, schema, table, csv_file)
    conn.close()
    typer.echo(f"Loaded {csv_file} into {schema}.{table}")


if __name__ == "__main__":
    app()
