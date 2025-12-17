# Ingestão e Organização do Banco

Guia para carregar CSVs do portal de dados abertos no DuckDB local preservando a estrutura original. A ingestão foi implementada por meio de um script que carrega arquivos CSV em tabelas do banco local, usando o descritor JSON fornecido no Portal de Dados Abertos do Recife para definir nome de tabela e esquema de colunas. O processo é não destrutivo em relação aos arquivos de origem: os CSVs são mantidos como foram obtidos, e a ingestão cria tabelas e insere registros no banco conforme o esquema descrito, sem remodelagens profundas no conteúdo.

## Conjuntos de dados utilizados
Foram selecionados três conjuntos de dados públicos para compor o estudo:
- Situação final dos alunos por período letivo (`situação_final_dos_alunos_por_período_letivo`)
- Registro das infrações de trânsito - CTTU (`registro_das_infrações_de_trânsito_-_cttu`)
- Naufrágios do Recife (`naufrágios_do_recife`)

Em todos os casos, o portal publica múltiplos CSVs por ano de referência, resultantes da mesma consulta e com estrutura homogênea. A estratégia adotada foi agregar todos os arquivos de um mesmo tema em uma única tabela, contendo o histórico completo disponível. Essa agregação é estritamente estrutural/temporal: os CSVs são concatenados mantendo o esquema original, sem fusão de atributos ou mudança de semântica, permitindo consultas longitudinais mantendo fidelidade à fonte.

## Princípios e desafios
- **Preservação**: manter cabeçalhos e formatos conforme a origem; apenas ajustes mínimos para viabilizar a leitura (encoding/delimitador).
- **Descritor como contrato**: o JSON do portal define o nome da tabela e as colunas. Quando o descritor não traz tipos, a tipagem é inferida amostrando o CSV.
- **Heterogeneidade controlada**: mesmo com arquivos anuais separados, a agregação exige que o esquema seja idêntico; divergências são tratadas antes da carga para manter a estrutura consistente.
- **DuckDB para o protótipo**: escolhido por ser embutido (arquivo único, sem servidor), rápido para leitura de CSV e suficientemente expressivo para SQL analítico local — ideal para um protótipo reprodutível em laboratório sem dependências externas.

## Fluxo de ingestão
1. Posicione os CSVs originais e o descritor JSON (obtido do portal) no diretório desejado.
2. Rode o script com modo individual ou em lote; os arquivos não são modificados.
3. Cada conjunto temático vira uma tabela única, agregando todos os arquivos daquele diretório.

### Ingestão individual
```bash
python -m scripts.ingest load <descriptor.json> <arquivo.csv> [--schema public] [--replace] [--sample-rows 1000]
```
- Usa o descritor para criar a tabela; com `--replace` recria antes de inserir.
- Se o descritor não trouxer colunas, infere tipos (`INTEGER`, `DOUBLE`, `BOOLEAN`, `TIMESTAMP`, `VARCHAR`) usando a amostra `--sample-rows`.

### Ingestão em lote
```bash
python -m scripts.ingest batch [--input-dir datasets] [--schema public] [--replace]
```
- **Descritor com `metadados`**: cria a tabela pelo descritor e insere todos os CSVs da pasta (primeiro recria, demais fazem append).
- **Descritor simples**: procura um CSV com o mesmo nome-base do JSON e carrega apenas esse arquivo.

O relatório final indica quantos arquivos foram carregados e eventuais falhas.

## Organização do banco e checagens
- O arquivo DuckDB padrão fica em `./data/recife.duckdb` (configurável via `DUCKDB_DATA_DIR`).
- Para recomeçar do zero, apague o arquivo do banco; não crie arquivos vazios, o DuckDB recria sozinho na próxima conexão.
- Verifique a carga com consultas simples:
  ```sql
  SELECT COUNT(*) FROM <schema>.<tabela>;
  SELECT * FROM <schema>.<tabela> LIMIT 5;
  ```

## Estrutura de diretórios sugerida
```
datasets/
├── situacao_final_alunos/
│   ├── 2023.csv
│   ├── 2024.csv
│   └── descriptor.json
├── infracoes_cttu/
│   ├── 2019.csv
│   ├── 2024.csv
│   └── descriptor.json
└── naufragios/
    ├── dados.csv
    └── descriptor.json
```
