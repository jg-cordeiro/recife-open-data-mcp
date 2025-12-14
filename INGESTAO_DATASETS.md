# Processo de Ingestão de Novos Datasets

## Resumo

Este guia explica como carregar CSVs no DuckDB usando `scripts/ingest.py`, mantendo a estrutura original dos dados. O objetivo é evitar consolidações e remodelagens profundas: trabalhamos com os arquivos fornecidos pelos portais públicos, fazendo apenas ajustes pontuais (tipagem ou pequenos acertos de formato) para viabilizar a carga e a consulta.

---

## Princípios da metodologia
- **Preservar a estrutura e semântica originais**: não consolidar nem remodelar tabelas sem necessidade. Cada CSV é carregado como veio da fonte, respeitando colunas e nomes originais.
- **Ajustes mínimos e justificados**: apenas correções básicas (ex.: encoding, delimitador, tipos incoerentes no descritor) quando bloqueiam a ingestão.
- **Transparência**: use descritores explícitos para documentar a tabela e suas colunas; quando o descritor não traz colunas, a tipagem é inferida automaticamente.

---

## Padrões de descritores suportados

O script aceita dois formatos de descritor JSON:

1. **Formato de metadados (recomendado)**
   - Chave `metadados.cabecalho.titulo` define o nome da tabela (espaços viram `_`).
   - Colunas vêm de `metadados.campos` e são criadas como `VARCHAR`. Se ausentes, os tipos são inferidos amostrando o CSV.
   - Permite carregar **vários CSVs de um diretório** na mesma tabela (primeiro recria, demais fazem append).

2. **Formato simples (legado)**
   - Chave `table` ou `name` define a tabela.
   - Lista `columns` com `name` e `type` (tipos DuckDB).
   - Usa um par `<descriptor>.json` + `<descriptor>.csv` na mesma pasta.

---

## Reiniciar o banco DuckDB

Para recomeçar as cargas do zero:
- Remova o arquivo `data/recife.duckdb`. **Não** crie um arquivo vazio com `touch`: o DuckDB cria o arquivo automaticamente na próxima conexão.
- Se quiser trocar o diretório, defina `DUCKDB_DATA_DIR=/caminho` antes de rodar os comandos; o padrão é `./data`.

---

## Ingestão individual

Use para um único par descritor/CSV, preservando o arquivo original:

```bash
python -m scripts.ingest load <descriptor.json> <arquivo.csv> [--schema public] [--replace] [--sample-rows 1000]
```

- Se o descritor não declarar colunas, o comando amostra o CSV (`--sample-rows`) e infere `INTEGER`, `DOUBLE`, `BOOLEAN`, `TIMESTAMP` ou `VARCHAR`.
- O schema é criado se não existir. Com `--replace`, a tabela é derrubada e recriada antes da carga.

---

## Ingestão em lote

Use `batch` para percorrer um diretório de descritores e carregar todos os CSVs associados, sem consolidar arquivos:

```bash
python -m scripts.ingest batch [--input-dir datasets] [--schema public] [--replace]
```

Como o comando decide o que carregar:
1. **Descritor com `metadados`**: a tabela é criada a partir do descritor e **todos os CSVs na mesma pasta** são inseridos (o primeiro recria a tabela; os demais fazem append).
2. **Descritor simples**: procura um CSV com o mesmo nome-base do JSON e carrega apenas esse arquivo.

O relatório final mostra quantos arquivos foram carregados e se houve falhas.

---

## Preparação dos arquivos

Para manter fidelidade à fonte, antes de ingerir verifique apenas o essencial:
- **Delimitador e encoding**: ajuste somente se o arquivo estiver ilegível pelo DuckDB (`read_csv_auto` costuma resolver a maioria dos casos).
- **Cabeçalhos**: garanta que o CSV traga os nomes originais das colunas. Evite renomear ou reordenar.
- **Descritor**: documente a tabela usando o formato de metadados sempre que possível; use tipos `VARCHAR` por padrão e deixe a inferência resolver nuances de dados.

### Quando (raramente) consolidar
Se a fonte publica um mesmo dataset fragmentado por ano/mês com exatamente o mesmo esquema, você pode consolidar para agilizar a carga usando `scripts/consolidate.py`. Faça isso apenas quando não altera a semântica e documente claramente o resultado no descritor gerado.

---

## Estrutura de diretórios sugerida

```
datasets/
├── <dataset-a>/
│   ├── arquivo1.csv
│   ├── arquivo2.csv
│   └── descriptor.json   # contém metadados do dataset
├── <dataset-b>/
│   ├── dados.csv
│   └── descriptor.json
└── consolidated/         # apenas para casos excepcionais de consolidação
```

---

## Troubleshooting
- **"Column has X columns but Y values were supplied"**: verifique se o cabeçalho bate com as linhas do CSV e se o descritor lista todas as colunas. Se usar inferência, aumente `--sample-rows` para capturar mais casos.
- **CSV com delimitadores mistos ou aspas na linha inteira**: tente primeiro com `load` ou `batch`; o DuckDB costuma normalizar. Só ajuste o arquivo se o erro persistir.
- **Tipos incompatíveis**: prefira `VARCHAR` no descritor para preservar os dados; converta tipos apenas quando houver certeza sobre o domínio.
- **"not a valid DuckDB database file" logo ao conectar**: apague o arquivo `data/recife.duckdb` (se foi criado vazio) e rode o comando de ingestão novamente; o DuckDB recria o arquivo válido.

---

## Verificação rápida pós-carga

Após a ingestão, execute consultas simples para garantir que a tabela reflete o conteúdo original:

```sql
SELECT COUNT(*) FROM <schema>.<tabela>;
SELECT * FROM <schema>.<tabela> LIMIT 5;
```

Essas verificações devem confirmar a quantidade de registros esperada e a manutenção dos nomes de coluna fornecidos pelo portal de origem.
