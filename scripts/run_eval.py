import asyncio
import json
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import numbers

import typer
from dotenv import load_dotenv

from server.config import Settings
from server.db import Database
from server.openrouter_client import OpenRouterClient
from server.sql_guard import ensure_limit, ensure_read_only

load_dotenv()

app = typer.Typer(help="Executa casos de avaliação e registra relatório em Markdown.")


@dataclass
class ComparisonSpec:
    type: str
    field_name: Optional[str] = None  # campo preferencial para comparação numérica
    tolerance: float = 0  # tolerância para comparação numérica
    key_columns: List[str] = field(default_factory=list)  # colunas que definem a chave em rankings
    value_column: Optional[str] = None  # coluna de valor em rankings
    top_k: Optional[int] = None  # quantas linhas comparar em rankings
    sample_columns: Optional[List[str]] = None  # colunas relevantes para comparação de listas
    sample_size: int = 3  # número de linhas a comparar em listas


@dataclass
class EvalCase:
    id: str
    question: str
    gold_sql: str
    comparison: ComparisonSpec


def load_cases(cases_path: Path) -> List[EvalCase]:
    data = json.loads(cases_path.read_text(encoding="utf-8"))
    cases: List[EvalCase] = []
    for item in data.get("cases", []):
        comp = ComparisonSpec(**item["comparison"])
        cases.append(EvalCase(id=item["id"], question=item["question"], gold_sql=item["gold_sql"], comparison=comp))
    return cases


def _first_numeric(row: Dict[str, Any], preferred: Optional[str] = None, exclude: Optional[List[str]] = None) -> Tuple[Optional[str], Optional[float]]:
    exclude = set(exclude or [])
    if preferred and preferred in row and isinstance(row[preferred], numbers.Number):
        return preferred, float(row[preferred])
    for k, v in row.items():
        if k in exclude:
            continue
        if isinstance(v, numbers.Number):
            return k, float(v)
    return None, None


def compare_numeric(rows: List[Dict[str, Any]], gold_rows: List[Dict[str, Any]], spec: ComparisonSpec) -> Tuple[bool, str]:
    if not rows:
        return False, "Nenhuma linha retornada."
    if not gold_rows:
        return False, "Gold SQL não retornou linhas."
    got_field, got_val = _first_numeric(rows[0], preferred=spec.field_name)
    gold_field, gold_val = _first_numeric(gold_rows[0], preferred=spec.field_name)
    if got_val is None or gold_val is None:
        return False, f"Valor numérico não encontrado (got_field={got_field}, gold_field={gold_field})."
    tol = spec.tolerance or 0
    ok = abs(got_val - gold_val) <= tol
    return ok, f"obtido={got_val}, esperado={gold_val}, tolerancia={tol}"


def compare_ranking(rows: List[Dict[str, Any]], gold_rows: List[Dict[str, Any]], spec: ComparisonSpec) -> Tuple[bool, str]:
    if not spec.key_columns:
        return False, "key_columns não definidos."
    top_k = spec.top_k or min(len(rows), len(gold_rows))
    if len(rows) < top_k or len(gold_rows) < top_k:
        return False, f"Linhas insuficientes para top_k={top_k}."
    tol = spec.tolerance or 0
    for idx in range(top_k):
        got_row = rows[idx]
        gold_row = gold_rows[idx]
        for col in spec.key_columns:
            if got_row.get(col) != gold_row.get(col):
                return False, f"Posição {idx} coluna {col}: obtido={got_row.get(col)}, esperado={gold_row.get(col)}"
        _, got_val = _first_numeric(got_row, preferred=spec.value_column, exclude=spec.key_columns)
        _, gold_val = _first_numeric(gold_row, preferred=spec.value_column, exclude=spec.key_columns)
        if got_val is None or gold_val is None:
            return False, f"Posição {idx}: valor numérico ausente."
        if abs(got_val - gold_val) > tol:
            return False, f"Posição {idx} valor: obtido={got_val}, esperado={gold_val}, tolerancia={tol}"
    return True, f"Top-{top_k} bate com o gold."


def compare_list(rows: List[Dict[str, Any]], gold_rows: List[Dict[str, Any]], spec: ComparisonSpec) -> Tuple[bool, str]:
    if len(rows) != len(gold_rows):
        return False, f"Row count difere: obtido={len(rows)}, gold={len(gold_rows)}"
    sample_size = min(spec.sample_size or 3, len(rows))
    if sample_size == 0:
        return True, "Sem linhas para comparar."
    cols = spec.sample_columns
    if not cols:
        # usa interseção de colunas
        cols = list(set(rows[0].keys()) & set(gold_rows[0].keys()))
    for idx in range(sample_size):
        got_row = rows[idx]
        gold_row = gold_rows[idx]
        for col in cols:
            if got_row.get(col) != gold_row.get(col):
                return False, f"Amostra divergente na linha {idx}, coluna {col}: obtido={got_row.get(col)}, gold={gold_row.get(col)}"
    return True, "Row count e amostra conferem."


def format_markdown(run_id: str, model: str, results: List[Dict[str, Any]]) -> str:
    lines = [
        f"# Eval run {run_id}",
        "",
        f"- Modelo: `{model}`",
        f"- Data/Hora: {datetime.now(timezone.utc).isoformat()}",
        f"- Casos: {len(results)}",
        "",
        "| Caso | Status | Pergunta | Gold SQL | SQL Gerado | Comparação | Duração (ms) | Linhas retornadas | Detalhes |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in results:
        lines.append(
            "| {id} | {status} | {question} | `{gold}` | `{sql}` | {cmp} | {duration} | {row_count} | {details} |".format(
                id=r["id"],
                status="✅" if r["passed"] else "❌",
                question=r["question"].replace("|", "\\|"),
                gold=r["gold_sql"].replace("|", "\\|"),
                sql=(r.get("generated_sql") or "").replace("|", "\\|"),
                cmp=r.get("comparison_result", "").replace("|", "\\|"),
                duration=int(r.get("duration_ms", 0)),
                row_count=len(r.get("rows", [])),
                details=(r.get("error") or "").replace("|", "\\|"),
            )
        )

    lines.append("\n## Detalhes por caso\n")
    for r in results:
        lines.append(f"### {r['id']} ({'✅' if r['passed'] else '❌'})")
        lines.append(f"- Pergunta: {r['question']}")
        lines.append(f"- SQL gerado: `{r.get('generated_sql', '')}`")
        lines.append(f"- SQL esperado: `{r['gold_sql']}`")
        lines.append(f"- Comparação: {r.get('comparison_result', '')}")
        lines.append(f"- Linhas retornadas: {len(r.get('rows', []))}")
        lines.append(f"- Ferramentas chamadas: {', '.join(r.get('tools_called', [])) if r.get('tools_called') else 'N/A'}")
        lines.append(f"- Duração (ms): {int(r.get('duration_ms', 0))}")
        if r.get("error"):
            lines.append(f"- Erro: {r['error']}")
        sample_rows = r.get("rows", [])[:3]
        if sample_rows:
            lines.append("- Amostra de linhas:")
            lines.append("```json")
            lines.append(json.dumps(sample_rows, ensure_ascii=False, indent=2))
            lines.append("```")
        lines.append("")
    return "\n".join(lines)


async def evaluate_case(
    db: Database,
    llm: OpenRouterClient,
    schema_text: Optional[str],
    case: EvalCase,
    max_rows: int,
) -> Dict[str, Any]:
    start = time.time()
    result: Dict[str, Any] = {
        "id": case.id,
        "question": case.question,
        "gold_sql": case.gold_sql,
    }
    try:
        # Gold result
        ensure_read_only(case.gold_sql)
        gold_sql_limited = ensure_limit(case.gold_sql, max_rows)
        gold_rows = await db.fetch_rows(gold_sql_limited)

        generated_sql = await llm.generate_sql(case.question, schema_text)
        ensure_read_only(generated_sql)
        limited_sql = ensure_limit(generated_sql, max_rows)
        rows = await db.fetch_rows(limited_sql)
        result.update(
            {
                "generated_sql": limited_sql,
                "rows": rows,
                "gold_rows": gold_rows,
                "tools_called": [],  # sem toolcalls explícitos nesta via
            }
        )
        spec = case.comparison
        if spec.type == "numeric":
            passed, cmp_msg = compare_numeric(rows, gold_rows, spec)
        elif spec.type == "ranking":
            passed, cmp_msg = compare_ranking(rows, gold_rows, spec)
        elif spec.type == "list":
            passed, cmp_msg = compare_list(rows, gold_rows, spec)
        else:
            passed, cmp_msg = False, f"Tipo de comparação desconhecido: {spec.type}"
        result["passed"] = passed
        result["comparison_result"] = cmp_msg
    except Exception as exc:  # pylint: disable=broad-except
        result["passed"] = False
        result["error"] = str(exc)
    finally:
        result["duration_ms"] = int((time.time() - start) * 1000)
    return result


@app.command()
def run(
    cases_path: Path = typer.Option(Path("eval_cases.json"), help="Caminho para o arquivo de casos."),
    output_dir: Path = typer.Option(Path("eval_runs"), help="Diretório para salvar relatórios."),
):
    """Executa os casos de avaliação e gera um relatório em Markdown."""
    settings = Settings.load()
    db = Database(settings)
    llm = OpenRouterClient(settings)
    cases = load_cases(cases_path)

    # Preparar diretório de saída
    output_dir.mkdir(parents=True, exist_ok=True)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    run_dir = output_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    typer.secho(f"🏁 Rodando {len(cases)} casos (run_id={run_id})", fg=typer.colors.CYAN)

    async def _run_all() -> List[Dict[str, Any]]:
        await db.init()
        schema_text = None  # LLM deve descobrir schema via ferramentas MCP
        results: List[Dict[str, Any]] = []
        for case in cases:
            typer.secho(f"→ Caso {case.id}: {case.question}", fg=typer.colors.BLUE)
            res = await evaluate_case(db, llm, schema_text, case, settings.max_result_rows)
            status = "✅" if res.get("passed") else "❌"
            typer.secho(f"   {status} {res.get('comparison_result', res.get('error', ''))}", fg=typer.colors.GREEN if res.get("passed") else typer.colors.RED)
            results.append(res)
        await db.close()
        return results

    results = asyncio.run(_run_all())

    # Persistir JSON e Markdown
    json_path = run_dir / "results.json"
    md_path = run_dir / "report.md"
    json_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(format_markdown(run_id, settings.openrouter_model, results), encoding="utf-8")

    typer.secho(f"\n📄 Relatório salvo em {md_path}", fg=typer.colors.GREEN)
    typer.secho(f"🧪 Resultados detalhados em {json_path}", fg=typer.colors.GREEN)


if __name__ == "__main__":
    app()
