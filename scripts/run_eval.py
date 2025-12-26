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
    reference_sql: str
    comparison: ComparisonSpec


def load_cases(cases_path: Path) -> List[EvalCase]:
    data = json.loads(cases_path.read_text(encoding="utf-8"))
    cases: List[EvalCase] = []
    for item in data.get("cases", []):
        comp = ComparisonSpec(**item["comparison"])
        reference_sql = item.get("reference_sql") or item.get("gold_sql")
        if not reference_sql:
            raise ValueError(f"Caso {item.get('id')} sem reference_sql")
        cases.append(
            EvalCase(
                id=item["id"],
                question=item["question"],
                reference_sql=reference_sql,
                comparison=comp,
            )
        )
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
            # sem valor numérico; aceita ordem apenas pelas chaves
            continue
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
        "| Caso | Status | Pergunta | SQL Referência | SQL Gerado | Comparação | Duração (ms) | Linhas retornadas | Detalhes |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in results:
        lines.append(
            "| {id} | {status} | {question} | `{reference}` | `{sql}` | {cmp} | {duration} | {row_count} | {details} |".format(
                id=r["id"],
                status="✅" if r["passed"] else "❌",
                question=r["question"].replace("|", "\\|"),
                reference=r["reference_sql"].replace("|", "\\|"),
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
        lines.append(f"- SQL referência: `{r['reference_sql']}`")
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
        "reference_sql": case.reference_sql,
    }
    # Gold result é fixo; compute uma vez
    ensure_read_only(case.reference_sql)
    reference_sql_limited = ensure_limit(case.reference_sql, max_rows)
    reference_rows = await db.fetch_rows(reference_sql_limited)

    async def _run_with_tool_calls() -> Tuple[Optional[str], List[Dict[str, Any]], List[str]]:
        tools_called: List[str] = []
        last_sql: Optional[str] = None
        last_rows: List[Dict[str, Any]] = []
        # Definição das ferramentas alinhadas ao MCP
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "list_tables",
                    "description": "List all available tables in the database with their schemas.",
                    "parameters": {"type": "object", "properties": {}, "required": []},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "describe_table",
                    "description": "Get detailed column information for a specific table (without schema).",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "table_name": {"type": "string", "description": "Table name without schema"}
                        },
                        "required": ["table_name"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "search_schema",
                    "description": "Search for tables or columns matching a keyword.",
                    "parameters": {
                        "type": "object",
                        "properties": {"search_term": {"type": "string", "description": "Term to search"}},
                        "required": ["search_term"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "execute_sql",
                    "description": "Execute a read-only SQL query with automatic LIMIT.",
                    "parameters": {
                        "type": "object",
                        "properties": {"sql": {"type": "string", "description": "SQL to execute"}},
                        "required": ["sql"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "create_sql",
                    "description": "Generate read-only SQL for a natural language question.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "question": {"type": "string"},
                            "schema_context": {"type": "string"},
                        },
                        "required": ["question"],
                    },
                },
            },
        ]

        system_prompt = (
            "Você é um agente MCP que deve usar ferramentas para descobrir schema e executar SQL em DuckDB.\n"
            "- SEMPRE chame list_tables e, para cada tabela que pretende usar, chame describe_table antes de qualquer execute_sql.\n"
            "- Use search_schema se precisar achar um campo.\n"
            "- Para situacao_nome, use UPPER(...) = 'APROVADO' ou LIKE 'RETIDO%' (case-insensitive).\n"
            "- Para datas (dataInfracao, dataimplantacao, data_naufragio), use regexp_extract para ano/data; nunca use SUBSTRING; filtre blanks/NULL antes de agrupar/contar.\n"
            "- Para profundidade_maxima, extraia dígitos com regexp_extract e try_cast; não faça CAST direto do texto.\n"
            "- Evite COUNT(DISTINCT ...) salvo se a pergunta pedir; prefira COUNT(*).\n"
            "- Para percentuais, devolva a fração salvo pedido explícito de multiplicar por 100.\n"
            "- Quando o SQL estiver pronto, chame execute_sql (read-only, com LIMIT automático).\n"
            "- Responda apenas quando terminar; não invente colunas/tabelas."
        )

        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": case.question},
        ]
        if schema_text:
            messages.append({"role": "user", "content": f"Schema snapshot:\n{schema_text}"})

        for _ in range(10):
            resp = await llm.client.chat.completions.create(
                model=llm.model,
                temperature=0,
                messages=messages,
                tools=tools,
                tool_choice="auto",
            )
            choice = resp.choices[0]
            msg = choice.message

            if msg.tool_calls:
                messages.append(
                    {
                        "role": "assistant",
                        "content": msg.content,
                        "tool_calls": msg.tool_calls,
                    }
                )
                for tc in msg.tool_calls:
                    name = tc.function.name
                    args = json.loads(tc.function.arguments or "{}")
                    tools_called.append(name)
                    if name == "list_tables":
                        payload = await db.list_tables()
                    elif name == "describe_table":
                        table_name = args.get("table_name") or ""
                        payload = await db.describe_table(table_name)
                    elif name == "search_schema":
                        term = args.get("search_term") or ""
                        payload = await db.search_schema(term)
                    elif name == "execute_sql":
                        sql_arg = args.get("sql") or ""
                        try:
                            ensure_read_only(sql_arg)
                            limited_sql = ensure_limit(sql_arg, max_rows)
                            rows = await db.fetch_rows(limited_sql)
                            last_sql = limited_sql
                            last_rows = rows
                            payload = {
                                "sql": limited_sql,
                                "row_count": len(rows),
                                "rows": rows,
                            }
                        except Exception as exc:  # pylint: disable=broad-except
                            payload = {"error": str(exc)}
                    elif name == "create_sql":
                        question_arg = args.get("question") or case.question
                        schema_ctx = args.get("schema_context") or schema_text
                        sql = await llm.generate_sql(question_arg, schema_ctx)
                        ensure_read_only(sql)
                        limited_sql = ensure_limit(sql, max_rows)
                        payload = {"sql": limited_sql}
                    else:  # pragma: no cover - defensive
                        payload = {"error": f"Unknown tool {name}"}

                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": json.dumps(payload, ensure_ascii=False),
                        }
                    )
                continue

            # final response (no tool calls)
            break

        return last_sql, last_rows, tools_called

    last_sql, rows, tools_used = await _run_with_tool_calls()

    result["generated_sql"] = last_sql
    result["attempts"] = len([t for t in tools_used if t == "execute_sql"])
    result.update(
        {
            "rows": rows or [],
            "reference_rows": reference_rows,
            "tools_called": tools_used,
        }
    )

    spec = case.comparison
    if spec.type == "numeric":
        passed, cmp_msg = compare_numeric(rows or [], reference_rows, spec)
    elif spec.type == "ranking":
        passed, cmp_msg = compare_ranking(rows or [], reference_rows, spec)
    elif spec.type == "list":
        passed, cmp_msg = compare_list(rows or [], reference_rows, spec)
    else:
        passed, cmp_msg = False, f"Tipo de comparação desconhecido: {spec.type}"
    result["passed"] = passed
    result["comparison_result"] = cmp_msg
    if not passed and not rows:
        result["error"] = result.get("comparison_result", "Falha desconhecida")

    result["duration_ms"] = int((time.time() - start) * 1000)
    return result


@app.command()
def run(
    cases_path: Path = typer.Option(Path("eval_cases.json"), help="Caminho para o arquivo de casos."),
    output_dir: Path = typer.Option(Path("eval_runs"), help="Diretório para salvar relatórios."),
    run_prefix: str = typer.Option("prod-", help="Prefixo para o run_id (por ex. prod-)"),
):
    """Executa os casos de avaliação e gera um relatório em Markdown."""
    settings = Settings.load()
    db = Database(settings)
    llm = OpenRouterClient(settings)
    cases = load_cases(cases_path)

    # Preparar diretório de saída
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    run_id = f"{run_prefix}{timestamp}" if run_prefix else timestamp
    run_dir = output_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    typer.secho(f"🏁 Rodando {len(cases)} casos (run_id={run_id})", fg=typer.colors.CYAN)

    async def _run_all() -> List[Dict[str, Any]]:
        await db.init()
        schema_text = await db.fetch_schema_snapshot()  # fornece snapshot do schema para evitar toolcalls inválidos
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
