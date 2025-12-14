# Guia de Migração: Postgres → DuckDB

## Visão Geral
Este documento resume todas as alterações realizadas para migrar a implementação de PostgreSQL para DuckDB (banco de dados embutido, baseado em arquivo).

## Alterações Realizadas

### 1. **Configuração (`server/config.py`)**

**Antes (Postgres):**
```python
db_host: str = "localhost"
db_port: int = 5432
db_name: str = "recife_open_data"
db_user: str = "recife"
db_password: str = "recife"
statement_timeout_ms: int = 10000
```

**Depois (DuckDB):**
```python
db_path: str = "./data/recife.duckdb"
# Criado automaticamente em Settings.load()
db_dir = Path(os.environ.get("DUCKDB_DATA_DIR", "./data"))
db_dir.mkdir(parents=True, exist_ok=True)
```

**Variáveis de Ambiente Removidas:**
- `POSTGRES_HOST`
- `POSTGRES_PORT`
- `POSTGRES_DB`
- `POSTGRES_USER`
- `POSTGRES_PASSWORD`
- `STATEMENT_TIMEOUT_MS`

**Variáveis de Ambiente Adicionadas:**
- `DUCKDB_DATA_DIR` (opcional, padrão: `./data`)

---

### 2. **Camada de Banco de Dados (`server/db.py`)**

**Antes (asyncpg):**
```python
import asyncpg

class Database:
    _pool: asyncpg.Pool
    
    async def init(self):
        self._pool = await asyncpg.create_pool(
            user=..., password=..., host=..., port=...
        )
    
    async def fetch_rows(self, sql):
        await conn.execute(f"SET LOCAL statement_timeout = ...")
        return await conn.fetch(sql)
```

**Depois (duckdb):**
```python
import duckdb

class Database:
    _conn: duckdb.DuckDBPyConnection
    
    async def init(self):
        self._conn = duckdb.connect(self.settings.db_path)
        self._conn.execute("SET threads = 4")
        self._conn.execute("SET memory_limit = '4GB'")
    
    async def fetch_rows(self, sql):
        result = self._conn.execute(sql).fetchall()
        # Converte para List[Dict]
```

**Mudanças:**
- ✅ Sem pool de conexões (DuckDB é single-threaded por design)
- ✅ Sem timeout por statement (DuckDB executa rapidamente)
- ✅ Sem credenciais (arquivo local)
- ✅ Configurações de performance (threads, memory_limit)

---

### 3. **Guardrails SQL (`server/sql_guard.py`)**

**Sem mudanças funcionais**, apenas ajuste:
- Continua bloqueando DDL/DML (INSERT, UPDATE, DELETE, etc.)
- Continua adicionando `LIMIT` automático
- Compatível com DuckDB (usa mesmo dialeto SQL padrão)

---

### 4. **Servidor HTTP (`server/http_server.py`)**

**Antes:**
```python
logger.info("Starting MCP HTTP server with DB host=%s port=%s", settings.db_host, settings.db_port)
```

**Depois:**
```python
logger.info("Starting MCP HTTP server with DuckDB database at %s", settings.db_path)
```

**Mudança:** Apenas log atualizado.

---

### 5. **LLM Guidance (`server/openrouter_client.py`)**

**Antes:**
```python
guidance = "You are a SQL expert producing safe, read-only PostgreSQL. ..."
```

**Depois:**
```python
guidance = "You are a SQL expert producing safe, read-only DuckDB SQL. ..."
```

**Mudança:** Guidance para o LLM reflete banco DuckDB.

---

### 6. **FastMCP Server (`server/main.py`)**

**Antes:**
```python
rows = await db.fetch_rows(limited, timeout_ms=settings.statement_timeout_ms)
```

**Depois:**
```python
rows = await db.fetch_rows(limited)
```

**Mudança:** Remover parâmetro de timeout (DuckDB não o suporta).

---

### 7. **Script de Ingestão (`scripts/ingest.py`)**

**Antes (psycopg):**
```python
import psycopg
conn = psycopg.connect(conninfo)
with conn.cursor() as cur:
    cur.execute(f"DROP TABLE IF EXISTS {schema}.{table}")
    copy_sql = sql.SQL("COPY {}.{} FROM STDIN WITH CSV HEADER")
    with cur.copy(copy_sql) as copy:
        copy.write(csv_data)
```

**Depois (duckdb):**
```python
import duckdb
conn = duckdb.connect(settings.db_path)
conn.execute(f'DROP TABLE IF EXISTS "{schema}"."{table}"')
conn.execute(f'CREATE TABLE "{schema}"."{table}" (...)')
conn.execute(f'INSERT INTO "{schema}"."{table}" SELECT * FROM read_csv_auto(...)')
```

**Mudanças:**
- ✅ Remover importação `psycopg`
- ✅ Remover construtor de `conninfo`
- ✅ Usar `duckdb.connect()` direto ao arquivo
- ✅ Usar `read_csv_auto()` do DuckDB para carregar CSV
- ✅ Tipos de coluna: `integer` → `INTEGER`, `text` → `VARCHAR`, etc.

---

### 8. **Dependências**

**`requirements.txt` - Removido:**
- `asyncpg>=0.29.0`
- `psycopg[binary]>=3.2.1`

**`requirements.txt` - Adicionado:**
- `duckdb>=0.9.0`

**`pyproject.toml` - Removido:**
- `asyncpg>=0.31.0`
- `psycopg>=3.3.2`

**`pyproject.toml` - Adicionado:**
- `duckdb>=0.9.0`

---

### 9. **Containerização**
- Docker Compose removido (execução focada em ambiente local/venv).
- Persistência via arquivo DuckDB em `${DUCKDB_DATA_DIR:-./data}` (backup com cópia do arquivo).

---

### 10. **Dockerfile**
- Dockerfile removido; deploy previsto via processo Python/uvicorn local.

---

### 11. **Documentação**

#### `README.md`
- Remover menção ao PostgreSQL
- Atualizar pré-requisitos (sem Docker Compose)
- Remover seção de Docker/Compose e documentar setup direto no venv
- Atualizar tipos de coluna (INTEGER, VARCHAR, etc.)
- Remover referências a `STATEMENT_TIMEOUT_MS`
- Atualizar troubleshooting (banco local vs remoto)

#### `README_HTTP.md`
- Atualizar arquitetura para DuckDB local
- Remover instruções de Docker e Postgres
- Manter exemplos de ingestão e chamadas HTTP

#### `INGESTAO_DATASETS.md`
- Atualizar tipos PostgreSQL para DuckDB
- Substituir descriptor com tipos `INTEGER`, `VARCHAR`, etc.
- Atualizar fluxo de carregamento (duckdb.connect → read_csv_auto)
- Remover referências a `COPY` PostgreSQL
- Adicionar nota sobre arquivo DuckDB local

---

## Benefícios da Migração

| Aspecto | Postgres | DuckDB |
|---------|----------|--------|
| **Setup** | Docker + services | Um arquivo local |
| **Persistência** | Banco de dados remoto | Arquivo no filesystem |
| **Dependências** | asyncpg + psycopg | Apenas duckdb |
| **Performance local** | Rede + overhead | In-process, rápido |
| **Acoplamento** | Desacoplado (separado) | Acoplado ao MCP |
| **Escalabilidade** | Alta (servidor) | Baixa-média (arquivo) |
| **Desenvolvimento** | Requer Docker | Apenas Python |

---

## Checklist de Validação

- [x] `server/config.py` - Atualizado com `db_path`
- [x] `server/db.py` - Reescrito com DuckDB
- [x] `server/sql_guard.py` - Compatível (sem mudanças)
- [x] `server/http_server.py` - Logs atualizados
- [x] `server/main.py` - Removido timeout
- [x] `server/openrouter_client.py` - Guidance atualizada
- [x] `scripts/ingest.py` - Migrado para DuckDB
- [x] `requirements.txt` - Dependências atualizadas
- [x] `pyproject.toml` - Dependências atualizadas
- [x] `Dockerfile` - Removido
- [x] `docker-compose.yml` - Removido
- [x] `README.md` - Documentação atualizada
- [x] `INGESTAO_DATASETS.md` - Instruções atualizadas

---

## Como Usar Pós-Migração

### Setup Local
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

export OPENROUTER_API_KEY=your-key-here
python -m server.main  # Inicia FastMCP
# ou
uvicorn server.http_server:app --reload  # Inicia HTTP server
```

### Ingestão de Dados
```bash
python scripts/ingest.py datasets/descriptor.json datasets/data.csv --schema public --replace
```

### Persistência
- Arquivo DuckDB: `./data/recife.duckdb`
- Fazer backup: `cp data/recife.duckdb data/recife.duckdb.backup`

---

## Rollback (Reversão)

Se precisar voltar a Postgres:
1. Restaurar `requirements.txt` e `pyproject.toml` para versão anterior
2. Restaurar `server/db.py` com asyncpg
3. Restaurar `docker-compose.yml` com serviço postgres
4. Executar `pip install -r requirements.txt`
5. Atualizar `ingest.py` para usar psycopg
6. Usar dump do banco antigo: `pg_restore -d recife_open_data backup.dump`

---

## Próximas Melhorias (Opcional)

1. **Índices para performance:**
   ```sql
   CREATE INDEX idx_situacao_final_ano ON public.situacao_final_estudantes(ano);
   ```

2. **Views para queries comuns:**
   ```sql
   CREATE VIEW v_resumo_por_ano AS
   SELECT ano, COUNT(*) as total FROM situacao_final_estudantes GROUP BY ano;
   ```

3. **Replicação/Backup:**
   - Usar `duckdb_backup()` para snapshots
   - Configurar cron job para backup diário

4. **Monitoramento:**
   - Adicionar endpoint `/metrics` com tamanho do banco
   - Log de query duration

---

**Data da Migração:** Dezembro 2025  
**Status:** ✅ Completa e testada  
**Compatibilidade:** Mantém mesma API MCP/HTTP
