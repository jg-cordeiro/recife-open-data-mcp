import re
import sqlparse

PROHIBITED = {"INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "TRUNCATE", "CREATE", "REPLACE", "GRANT", "REVOKE"}


def ensure_read_only(sql: str) -> None:
    statements = [stmt for stmt in sqlparse.parse(sql) if stmt.tokens]
    if not statements:
        raise ValueError("SQL is empty.")
    
    # Allow only single statements
    if len(statements) > 1:
        raise ValueError("Only single SQL statements are allowed. Multiple statements detected.")
    
    for stmt in statements:
        first_token = stmt.token_first(skip_cm=True)
        normalized = first_token.normalized if first_token else ""
        if normalized not in {"SELECT", "WITH", "EXPLAIN"}:
            raise ValueError("Only SELECT statements are allowed.")
        text = stmt.value.upper()
        if any(keyword in text for keyword in PROHIBITED):
            raise ValueError("Destructive or mutating statements are not allowed.")


def ensure_limit(sql: str, max_rows: int) -> str:
    sql = sql.rstrip().rstrip(';')
    if re.search(r"\bLIMIT\b", sql, re.IGNORECASE):
        return sql
    return f"{sql} LIMIT {max_rows};"
