import csv
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional

import duckdb
import typer
from dotenv import load_dotenv

from server.config import Settings

load_dotenv()
app = typer.Typer(help="Ingest CSV datasets into DuckDB for the MCP server.")


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
            duck_type = "INTEGER"
        elif values and all(_looks_float(v) for v in values):
            duck_type = "DOUBLE"
        elif values and all(_looks_bool(v) for v in values):
            duck_type = "BOOLEAN"
        elif values and all(_looks_date(v) for v in values):
            duck_type = "TIMESTAMP"
        else:
            duck_type = "VARCHAR"
        specs.append(ColumnSpec(name=col, type=duck_type))
    return specs


def read_descriptor(descriptor: Path) -> tuple[str, Optional[List[ColumnSpec]]]:
    data = json.loads(descriptor.read_text(encoding="utf-8"))
    
    # Check if it's a metadata structure (new format with "metadados" key)
    if "metadados" in data:
        # New format: single descriptor for multiple CSVs
        metadata = data["metadados"]
        cabecalho = metadata.get("cabecalho", {})
        table = cabecalho.get("titulo", "").lower().replace(" ", "_")
        if not table:
            raise typer.BadParameter("Descriptor with 'metadados' must include 'cabecalho.titulo'.")
        
        # Extract columns from "campos" if available
        campos = metadata.get("campos", [])
        if campos:
            cols = [ColumnSpec(name=c["codigo"], type="VARCHAR") for c in campos]
            return table, cols
        return table, None
    
    # Old format: simple descriptor with "table" or "name"
    table = data.get("table") or data.get("name")
    if not table:
        raise typer.BadParameter("Descriptor must include 'table' or 'name' or 'metadados'.")
    cols = data.get("columns")
    if cols:
        return table, [ColumnSpec(name=c["name"], type=c["type"]) for c in cols]
    return table, None


def create_table(conn: duckdb.DuckDBPyConnection, schema: str, table: str, columns: List[ColumnSpec], replace: bool) -> None:
    if replace:
        try:
            conn.execute(f'DROP TABLE IF EXISTS "{schema}"."{table}"')
        except Exception:
            pass
    
    columns_sql = [f'"{c.name}" {c.type}' for c in columns]
    create_stmt = f'CREATE TABLE IF NOT EXISTS "{schema}"."{table}" ({", ".join(columns_sql)})'
    conn.execute(create_stmt)


def copy_csv(conn: duckdb.DuckDBPyConnection, schema: str, table: str, csv_path: Path) -> None:
    # Use DuckDB's read_csv_auto and insert
    csv_path_str = str(csv_path)
    try:
        conn.execute(f'INSERT INTO "{schema}"."{table}" SELECT * FROM read_csv_auto(\'{csv_path_str}\')')
    except Exception:
        # Fallback with explicit options
        try:
            conn.execute(
                f'''INSERT INTO "{schema}"."{table}"
                    SELECT * FROM read_csv_auto(
                        '{csv_path_str}',
                        header=True,
                        delim=',',
                        quote='"',
                        ignore_errors=True,
                        all_varchar=True,
                        sample_size=-1
                    )'''
            )
        except Exception:
            # Last resort: clean outer quotes and double quotes into a temp file, then load
            import tempfile
            tmp = Path(tempfile.mkstemp(suffix=csv_path.name)[1])
            with csv_path.open("r", encoding="utf-8", errors="ignore") as src, tmp.open("w", encoding="utf-8") as dst:
                for line in src:
                    stripped = line.strip()
                    if stripped.startswith('"') and stripped.endswith('"') and len(stripped) >= 2:
                        stripped = stripped[1:-1]
                    stripped = stripped.replace('""', '"')
                    dst.write(stripped + "\n")
            conn.execute(
                f'''INSERT INTO "{schema}"."{table}"
                    SELECT * FROM read_csv_auto(
                        '{tmp}',
                        header=True,
                        delim=',',
                        quote='"',
                        ignore_errors=True,
                        all_varchar=True,
                        sample_size=-1
                    )'''
            )


@app.command()
def load(
    descriptor: Path = typer.Argument(..., help="JSON descriptor with table metadata."),
    csv_file: Path = typer.Argument(..., help="CSV file to ingest."),
    schema: str = typer.Option("public", help="Target schema."),
    replace: bool = typer.Option(True, help="Drop and recreate the table before loading."),
    sample_rows: int = typer.Option(1000, help="Rows to sample for type inference if columns missing."),
):
    """Load a single CSV file into DuckDB based on a descriptor JSON."""
    settings = Settings.load()
    table, columns = read_descriptor(descriptor)
    if columns is None:
        columns = infer_columns(csv_file, sample_rows)
    
    conn = duckdb.connect(settings.db_path)
    
    # Ensure schema exists
    conn.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')
    
    create_table(conn, schema, table, columns, replace)
    copy_csv(conn, schema, table, csv_file)
    conn.close()
    typer.echo(f"✅ Loaded {csv_file} into {schema}.{table}")


@app.command()
def batch(
    input_dir: Path = typer.Option(
        Path("datasets"),
        help="Directory containing CSV files alongside their descriptors",
    ),
    schema: str = typer.Option("public", help="Target schema."),
    replace: bool = typer.Option(True, help="Drop and recreate tables before loading."),
):
    """
    Batch load CSVs using descriptors located in a directory.

    Supports two patterns:
    1. Matching pairs: descriptor.json + descriptor.csv (e.g., escolas.json + escolas.csv)
    2. Single descriptor for multiple CSVs: descriptor.json describes all *.csv in the directory
       (identified by 'metadados' key in the JSON)
    """
    if not input_dir.exists():
        typer.echo(f"❌ Input directory not found: {input_dir}", err=True)
        raise typer.Exit(1)

    # Find all descriptor JSON files
    descriptors = list(input_dir.glob("*.json"))

    if not descriptors:
        typer.echo(f"❌ No descriptor JSON files found in {input_dir}", err=True)
        raise typer.Exit(1)

    settings = Settings.load()
    conn = duckdb.connect(settings.db_path)

    # Ensure schema exists
    conn.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')

    typer.echo(f"\n📦 Batch ingestion from {input_dir}")
    typer.echo(f"   Found {len(descriptors)} descriptor(s)\n")

    success_count = 0
    failed_count = 0

    for descriptor_path in sorted(descriptors):
        try:
            descriptor_data = json.loads(descriptor_path.read_text(encoding="utf-8"))
            
            # Check if this is a "metadados" descriptor (describes multiple CSVs)
            if "metadados" in descriptor_data:
                typer.echo(f"📄 Processing metadata descriptor: {descriptor_path.name}")
                table, columns = read_descriptor(descriptor_path)
                
                if columns is None:
                    typer.echo(f"⚠️  Skipping {descriptor_path.name}: no columns defined", err=True)
                    failed_count += 1
                    continue
                
                # Find all CSV files in this directory
                csv_files = sorted(input_dir.glob("*.csv"))
                
                if not csv_files:
                    typer.echo(f"⚠️  Skipping {descriptor_path.name}: no CSV files found in directory", err=True)
                    failed_count += 1
                    continue
                
                for csv_path in csv_files:
                    try:
                        typer.echo(f"   📊 Loading {csv_path.name} into {table}...")
                        
                        # For the first CSV, create the table; for others, append
                        is_first = (csv_path == csv_files[0])
                        create_table(conn, schema, table, columns, replace and is_first)
                        copy_csv(conn, schema, table, csv_path)
                        
                        result = conn.execute(f'SELECT COUNT(*) FROM "{schema}"."{table}"').fetchone()
                        row_count = result[0] if result else 0
                        
                        typer.echo(f"      ✅ {csv_path.name}: {row_count:,} total rows in {schema}.{table}")
                        success_count += 1
                    except Exception as e:
                        typer.echo(f"      ❌ Error loading {csv_path.name}: {e}", err=True)
                        failed_count += 1
                
                typer.echo()
            
            else:
                # Old pattern: matching pairs
                csv_path = descriptor_path.with_suffix('.csv')
                
                if not csv_path.exists():
                    typer.echo(f"⚠️  Skipping {descriptor_path.name}: matching CSV not found", err=True)
                    failed_count += 1
                    continue
                
                table, columns = read_descriptor(descriptor_path)
                
                if columns is None:
                    typer.echo(f"⚠️  Skipping {descriptor_path.name}: no columns defined", err=True)
                    failed_count += 1
                    continue
                
                typer.echo(f"📄 Loading {table}...")
                typer.echo(f"   Descriptor: {descriptor_path.name}")
                typer.echo(f"   CSV: {csv_path.name}")
                
                create_table(conn, schema, table, columns, replace)
                copy_csv(conn, schema, table, csv_path)
                
                result = conn.execute(f'SELECT COUNT(*) FROM "{schema}"."{table}"').fetchone()
                row_count = result[0] if result else 0
                
                typer.echo(f"   ✅ Success: {row_count:,} rows loaded into {schema}.{table}\n")
                success_count += 1
        
        except Exception as e:
            typer.echo(f"❌ Error processing {descriptor_path.name}: {e}\n", err=True)
            failed_count += 1

    conn.close()

    typer.echo(f"\n📊 Batch ingestion complete:")
    typer.echo(f"   ✅ Successful: {success_count}")
    typer.echo(f"   ❌ Failed: {failed_count}")

    if failed_count > 0:
        raise typer.Exit(1)


if __name__ == "__main__":
    app()
