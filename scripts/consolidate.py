"""
Consolidate yearly CSV datasets into single files.

This script:
1. Scans a dataset folder for yearly CSV files
2. Checks for existing data dictionary JSON
3. Generates dictionary using LLM (OpenRouter) if missing
4. Consolidates all CSVs into a single file with unified schema
5. Saves consolidated CSV to datasets/consolidated/
"""

import csv
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import List, Dict, Optional, Set

import typer
from dotenv import load_dotenv
from openai import OpenAI
from braintrust import current_span, init_logger, traced

from server.config import Settings

load_dotenv()

app = typer.Typer(help="Consolidate CSV datasets and generate data dictionaries.")


@dataclass
class CSVFile:
    """Represents a CSV file with its metadata."""
    path: Path
    year: Optional[int]
    columns: List[str]
    row_count: int
    delimiter: str = ";"  # Track the delimiter used in this file


def fix_multiline_header(csv_path: Path, delimiter: str) -> List[str]:
    """
    Fix CSV files with:
    1. Lines wrapped entirely in quotes (entire line is one quoted string)
    2. Misaligned columns (header columns don't match data columns)
    3. Year as first column instead of Regional
    """
    with csv_path.open("r", encoding="utf-8") as f:
        lines = f.readlines()
    
    if len(lines) < 2:
        return lines
    
    # Check if entire lines are wrapped in quotes (e.g., "col1,col2,col3")
    first_line_raw = lines[0].strip()
    if (first_line_raw.startswith('"') and first_line_raw.endswith('"') and 
        first_line_raw.count('"') == 2):
        # This looks like the line is quoted - remove quotes and split
        typer.echo(f"⚠️  Detected quoted CSV format in {csv_path.name} - fixing", err=True)
        
        corrected_lines = []
        for line in lines:
            line = line.rstrip('\r\n')
            if line.startswith('"') and line.endswith('"') and line.count('"') == 2:
                # Remove surrounding quotes
                line = line[1:-1]
            corrected_lines.append(line + "\n")
        
        lines = corrected_lines
    
    # Parse first line as header
    reader = csv.reader([lines[0]], delimiter=delimiter)
    header = next(reader)
    
    # Check if header and first data row are misaligned
    reader_data = csv.reader([lines[1]], delimiter=delimiter)
    first_data = next(reader_data)
    
    # Note: Files 2015, 2019, 2020, 2022 have already been fixed in the source files
    # They now have year as the value of Regional column, not missing it
    # No need to add empty columns here
    
    return lines


def detect_csv_files(dataset_dir: Path) -> List[CSVFile]:
    """Detect all CSV files in the dataset directory."""
    csv_files: List[CSVFile] = []
    
    for csv_path in sorted(dataset_dir.glob("*.csv")):
        # Extract year from filename if present (e.g., atendimentos_2014.csv or situacaofinal2014.csv)
        year = None
        for part in csv_path.stem.replace("_", " ").replace("situacaofinal", "").split():
            if part.isdigit() and len(part) == 4:
                year = int(part)
                break
        
        # Read first line to get columns and count rows
        try:
            with csv_path.open("r", encoding="utf-8") as f:
                first_line = f.readline().strip()
                
                # Remove surrounding quotes if present (entire line quoted)
                if (first_line.startswith('"') and first_line.endswith('"') and 
                    first_line.count('"') == 2):
                    first_line = first_line[1:-1]
                
                # Detect delimiter by counting occurrences
                # The correct delimiter will produce the right number of columns
                delimiter = ";"
                
                if first_line.count(",") > first_line.count(";"):
                    # More commas than semicolons = use comma
                    delimiter = ","
                elif first_line.count(",") == 0 and first_line.count(";") > 0:
                    # Only semicolons
                    delimiter = ";"
                elif first_line.count(",") > 0 and first_line.count(";") == 0:
                    # Only commas
                    delimiter = ","
                
                # Now read the header with detected delimiter, handling special formats
                fixed_lines = fix_multiline_header(csv_path, delimiter)
                reader = csv.reader(fixed_lines, delimiter=delimiter)
                columns = next(reader)
                
                # Count remaining rows (for progress reporting)
                row_count = len(fixed_lines) - 1  # -1 for header
            
            csv_files.append(CSVFile(
                path=csv_path,
                year=year,
                columns=columns,
                row_count=row_count,
                delimiter=delimiter
            ))
        except Exception as e:
            typer.echo(f"⚠️  Warning: Could not read {csv_path.name}: {e}", err=True)
    
    return csv_files


def detect_schema_differences(csv_files: List[CSVFile]) -> Dict[str, any]:
    """Detect schema differences across CSV files and create unified schema."""
    if not csv_files:
        return {"unified_columns": [], "has_differences": False, "details": []}
    
    # Collect all unique columns (preserving order from first file)
    all_columns: List[str] = []
    seen_columns: Set[str] = set()
    
    for csv_file in csv_files:
        for col in csv_file.columns:
            if col not in seen_columns:
                all_columns.append(col)
                seen_columns.add(col)
    
    # Check for differences
    has_differences = False
    details = []
    
    for csv_file in csv_files:
        missing_cols = set(all_columns) - set(csv_file.columns)
        extra_cols = set(csv_file.columns) - set(all_columns)
        
        if missing_cols or extra_cols:
            has_differences = True
            details.append({
                "file": csv_file.path.name,
                "year": csv_file.year,
                "missing_columns": list(missing_cols),
                "extra_columns": list(extra_cols)
            })
    
    return {
        "unified_columns": all_columns,
        "has_differences": has_differences,
        "details": details
    }


@traced(type="llm", name="Generate Data Dictionary", notrace_io=True)
def generate_dictionary_with_llm(
    dataset_name: str,
    description: str,
    columns: List[str],
    sample_rows: List[Dict[str, str]],
    csv_files: List[CSVFile]
) -> Dict:
    """Generate a data dictionary using OpenRouter LLM."""
    settings = Settings.load()
    
    if not settings.openrouter_api_key or settings.openrouter_api_key == "replace-me":
        raise typer.BadParameter(
            "OPENROUTER_API_KEY not configured. Please set it in your .env file."
        )
    
    # Initialize Braintrust logger
    init_logger(
        project="Recife Open Data MCP",
        api_key=os.getenv("BRAINTRUST_API_KEY")
    )
    
    client = OpenAI(
        api_key=settings.openrouter_api_key,
        base_url="https://openrouter.ai/api/v1"
    )
    
    # Build prompt with dataset information
    sample_data_text = "\n".join([
        f"Row {i+1}: {row}" for i, row in enumerate(sample_rows[:5])
    ])
    
    years = [f.year for f in csv_files if f.year]
    year_range = f"{min(years)}-{max(years)}" if years else "unknown"
    
    prompt = f"""Generate a data dictionary in JSON format for the following Brazilian government dataset:

**Dataset Name**: {dataset_name}
**Description**: {description}
**Year Range**: {year_range}
**Number of Files**: {len(csv_files)}

**Columns**: {', '.join(columns)}

**Sample Data**:
{sample_data_text}

Create a JSON dictionary following this exact structure:
{{
  "metadados": {{
    "cabecalho": {{
      "titulo": "<dataset title>",
      "descricao": "<detailed description in Portuguese>",
      "categoria_vcge": "http://vocab.e.gov.br/2016/09/vcge#<category>",
      "fonte_dados": "http://dados.recife.pe.gov.br",
      "licenca": "Open Database License (ODbL)",
      "responsavel_dados": "<responsible department>",
      "frequencia_atualizacao": "Anual"
    }},
    "recursos": [
      {{
        "identificador": "http://dados.recife.pe.gov.br/dataset/<slug>",
        "titulo": "Consolidated {dataset_name}",
        "formato": "csv",
        "descricao": "Dados consolidados de {year_range}"
      }}
    ],
    "campos": [
      {{
        "codigo": "<column_name>",
        "descricao": "<description in Portuguese>",
        "tipo": "<Num|Texto|Data|Boolean>",
        "tamanho": <size>,
        "valores_permitidos": "<allowed values or empty>"
      }}
    ]
  }}
}}

For each column in "campos", provide:
- codigo: exact column name from the dataset
- descricao: clear description in Portuguese
- tipo: "Num" for numbers, "Texto" for text, "Data" for dates, "Boolean" for true/false
- tamanho: estimated size
- valores_permitidos: list possible values if it's a categorical field, or leave empty

Return ONLY the JSON without any markdown formatting or explanation."""

    typer.echo("🤖 Generating data dictionary with LLM...")
    
    try:
        messages = [
            {"role": "system", "content": "You are a data documentation expert. Generate accurate, well-structured data dictionaries in Portuguese for Brazilian government datasets."},
            {"role": "user", "content": prompt}
        ]
        
        response = client.chat.completions.create(
            model=settings.openrouter_model,
            messages=messages,
            temperature=0.3,
        )
        
        response_text = response.choices[0].message.content.strip()
        
        # Remove markdown code blocks if present
        if response_text.startswith("```json"):
            response_text = response_text[7:]
        if response_text.startswith("```"):
            response_text = response_text[3:]
        if response_text.endswith("```"):
            response_text = response_text[:-3]
        
        result = json.loads(response_text.strip())
        
        # Log to Braintrust with structured input/output
        usage = response.usage or None
        current_span().log(
            input=messages,
            output=result,
            metrics={
                "prompt_tokens": usage.prompt_tokens if usage else 0,
                "completion_tokens": usage.completion_tokens if usage else 0,
                "total_tokens": usage.total_tokens if usage else 0,
            },
            metadata={
                "model": settings.openrouter_model,
                "temperature": 0.3,
                "dataset_name": dataset_name,
                "num_columns": len(columns),
                "num_files": len(csv_files),
            }
        )
        
        return result
    
    except Exception as e:
        typer.echo(f"❌ Error generating dictionary: {e}", err=True)
        raise


def consolidate_csvs(
    csv_files: List[CSVFile],
    output_path: Path,
    unified_columns: List[str]
) -> int:
    """Consolidate multiple CSV files into one with auto-aligned schema."""
    total_rows = 0
    
    with output_path.open("w", newline="", encoding="utf-8") as outfile:
        writer = csv.DictWriter(outfile, fieldnames=unified_columns, delimiter=";")
        writer.writeheader()
        
        for csv_file in csv_files:
            typer.echo(f"  📄 Processing {csv_file.path.name} ({csv_file.row_count} rows, delimiter: '{csv_file.delimiter}')...")
            
            # Fix multiline header before reading
            fixed_lines = fix_multiline_header(csv_file.path, csv_file.delimiter)
            
            # Parse fixed lines
            reader = csv.DictReader(fixed_lines, delimiter=csv_file.delimiter)
            
            for row in reader:
                # Auto-align: fill missing columns with empty strings
                aligned_row = {col: row.get(col, "") for col in unified_columns}
                writer.writerow(aligned_row)
                total_rows += 1
    
    return total_rows


@app.command()
def consolidate(
    dataset_dir: Path = typer.Argument(
        ..., 
        help="Path to dataset directory containing yearly CSV files"
    ),
    description: str = typer.Argument(
        ..., 
        help="Brief description of the dataset (used for LLM dictionary generation)"
    ),
    output_name: Optional[str] = typer.Option(
        None,
        help="Output filename (without .csv). Defaults to dataset directory name + '_consolidated'"
    ),
    force_regenerate: bool = typer.Option(
        False,
        "--force",
        help="Force regenerate dictionary even if it exists"
    ),
):
    """
    Consolidate yearly CSV files into a single dataset.
    
    Example:
        python -m scripts.consolidate datasets/atendimentos-defesa-civil \
            "Registro de atendimentos da Defesa Civil do Recife"
    """
    
    # Validate dataset directory
    if not dataset_dir.exists() or not dataset_dir.is_dir():
        raise typer.BadParameter(f"Dataset directory not found: {dataset_dir}")
    
    dataset_name = dataset_dir.name
    typer.echo(f"\n🔍 Analyzing dataset: {dataset_name}")
    typer.echo(f"📁 Source: {dataset_dir}")
    
    # Step 1: Detect CSV files
    csv_files = detect_csv_files(dataset_dir)
    
    if not csv_files:
        typer.echo("❌ No CSV files found in directory", err=True)
        raise typer.Exit(1)
    
    typer.echo(f"\n✅ Found {len(csv_files)} CSV files:")
    for f in csv_files:
        year_str = f.year if f.year else "unknown year"
        typer.echo(f"   - {f.path.name} ({year_str}, {f.row_count} rows, {len(f.columns)} columns)")
    
    # Step 2: Detect schema differences
    schema_info = detect_schema_differences(csv_files)
    
    if schema_info["has_differences"]:
        typer.echo("\n⚠️  Schema differences detected (will auto-align):")
        for detail in schema_info["details"]:
            typer.echo(f"   - {detail['file']}:")
            if detail["missing_columns"]:
                typer.echo(f"     Missing: {', '.join(detail['missing_columns'])}")
            if detail["extra_columns"]:
                typer.echo(f"     Extra: {', '.join(detail['extra_columns'])}")
    else:
        typer.echo("\n✅ All files have consistent schemas")
    
    unified_columns = schema_info["unified_columns"]
    typer.echo(f"\n📋 Unified schema: {len(unified_columns)} columns")
    
    # Step 3: Check for existing dictionary
    dict_filename = f"dicionario-{dataset_name}.json"
    dict_path = dataset_dir / dict_filename
    
    dictionary = None
    
    if dict_path.exists() and not force_regenerate:
        typer.echo(f"\n📖 Found existing dictionary: {dict_filename}")
        try:
            dictionary = json.loads(dict_path.read_text(encoding="utf-8"))
        except Exception as e:
            typer.echo(f"⚠️  Warning: Could not read existing dictionary: {e}", err=True)
    
    # Step 4: Generate dictionary if needed
    if dictionary is None:
        typer.echo(f"\n🤖 Generating dictionary with LLM...")
        
        # Read sample rows from first file
        sample_rows = []
        with csv_files[0].path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f, delimiter=";")
            sample_rows = [row for _, row in zip(range(10), reader)]
        
        dictionary = generate_dictionary_with_llm(
            dataset_name=dataset_name,
            description=description,
            columns=unified_columns,
            sample_rows=sample_rows,
            csv_files=csv_files
        )
        
        # Save dictionary
        dict_path.write_text(
            json.dumps(dictionary, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )
        typer.echo(f"✅ Dictionary saved: {dict_path}")
    
    # Step 5: Consolidate CSVs
    consolidated_dir = Path("datasets/consolidated")
    consolidated_dir.mkdir(exist_ok=True)
    
    output_filename = output_name or f"{dataset_name}_consolidated"
    output_path = consolidated_dir / f"{output_filename}.csv"
    
    typer.echo(f"\n📦 Consolidating CSVs...")
    total_rows = consolidate_csvs(csv_files, output_path, unified_columns)
    
    typer.echo(f"\n✅ Consolidation complete!")
    typer.echo(f"   📊 Total rows: {total_rows:,}")
    typer.echo(f"   💾 Output: {output_path}")
    typer.echo(f"   📖 Dictionary: {dict_path}")
    
    # Step 6: Create descriptor JSON for ingest.py
    descriptor_path = consolidated_dir / f"{output_filename}.json"
    
    # Use VARCHAR for all columns to avoid type conversion issues
    # DuckDB will handle type inference during queries
    columns_spec = [{"name": col, "type": "VARCHAR"} for col in unified_columns]
    
    descriptor = {
        "table": output_filename,
        "description": description,
        "columns": columns_spec
    }
    
    descriptor_path.write_text(
        json.dumps(descriptor, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )
    typer.echo(f"   📄 Descriptor: {descriptor_path}")
    
    typer.echo(f"\n🎯 Next step: Ingest into DuckDB")
    typer.echo(f"   python -m scripts.ingest {descriptor_path} {output_path}")


if __name__ == "__main__":
    app()
