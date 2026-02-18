# db_migrator — SQLite Explorer & Exporter

An interactive terminal tool for exploring SQLite databases, inspecting schemas,
running ad-hoc queries, and exporting data to CSV, JSON, or Parquet.

Built as a learning project while exploring Claude Code
for data engineering workflows.

---

## Features

- **Browse** — list all tables and views with live row counts
- **Inspect** — view column types, constraints, foreign keys, and indexes
- **Analyse** — per-column statistics (min/max/mean/median/mode) powered by pandas
- **Query** — run arbitrary SQL and see results in a formatted table
- **Export** — dump any table (or every table) to CSV, JSON, or Parquet
- **Zero-config** — only stdlib (`sqlite3`, `csv`, `json`) required for core features

---

## Installation

### Requirements

| Dependency | Version | Purpose |
|---|---|---|
| Python | 3.7+ | runtime |
| pandas | optional | table statistics |
| pyarrow | optional | Parquet export |

### Setup

```bash
# Clone the repo
git clone <repo-url>
cd db

# (Optional) create a virtual environment
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

# Install optional dependencies
pip install pandas pyarrow
```

No package installation is required — the script runs directly.

---

## Usage

### Interactive mode

```bash
python db_migrator.py sample.db
```

```
╔══════════════════════════════════════════════╗
║          DB Migrator / Explorer              ║
╚══════════════════════════════════════════════╝
  Database: sample.db

  1. List tables & views
  2. Inspect table structure
  3. Show table statistics
  4. Export table
  5. Run SQL query

  q. Quit

  Choice:
```

### Non-interactive modes

```bash
# Run a one-off SQL query and exit
python db_migrator.py sample.db --query "SELECT * FROM users LIMIT 5"

# Export a single table to CSV (default format)
python db_migrator.py sample.db --export orders --out ./exports

# Export a single table to JSON
python db_migrator.py sample.db --export orders --format json --out ./exports

# Export all tables to Parquet
python db_migrator.py sample.db --export-all --format parquet --out ./exports
```

### Example: listing tables

```
────────────────────────────────────────────────────────────
  Tables & Views
────────────────────────────────────────────────────────────
┌──────────┬───────┬───────────┐
│ Name     │ Type  │ Row count │
├──────────┼───────┼───────────┤
│ orders   │ table │ 1 042     │
│ products │ table │ 250       │
│ users    │ table │ 5 000     │
└──────────┴───────┴───────────┘

  • 3 table(s), 0 view(s)
```

### Example: inspecting a table

```
────────────────────────────────────────────────────────────
  Structure: users
────────────────────────────────────────────────────────────
┌───┬────────────┬─────────┬────────────────┐
│ # │ Column     │ Type    │ Constraints    │
├───┼────────────┼─────────┼────────────────┤
│ 0 │ id         │ INTEGER │ PK, NOT NULL   │
│ 1 │ name       │ TEXT    │ NOT NULL       │
│ 2 │ email      │ TEXT    │                │
│ 3 │ created_at │ TEXT    │ DEFAULT NOW()  │
└───┴────────────┴─────────┴────────────────┘
```

---

## CLI Reference

```
usage: db_migrator [-h] [--query SQL] [--export TABLE] [--export-all]
                   [--format {csv,json,parquet}] [--out DIR]
                   database

positional arguments:
  database              Path to the SQLite database file

options:
  -h, --help            show this help message and exit
  --query SQL, -q SQL   Run a SQL query and print results, then exit
  --export TABLE, -e TABLE
                        Export a specific table (use with --format)
  --export-all, -E      Export all tables (use with --format)
  --format {csv,json,parquet}, -f {csv,json,parquet}
                        Export format (default: csv)
  --out DIR, -o DIR     Output directory for exports (default: current dir)
```

---

## API Documentation

The script exposes a set of reusable functions that can be imported:

### Database helpers

| Function | Description |
|---|---|
| `get_tables(conn)` | Return sorted list of table names |
| `get_views(conn)` | Return sorted list of view names |
| `get_row_count(conn, table)` | Return row count for a table |
| `get_schema(conn, table)` | Return column metadata via `PRAGMA table_info` |
| `get_foreign_keys(conn, table)` | Return FK relationships via `PRAGMA foreign_key_list` |
| `get_indexes(conn, table)` | Return index definitions via `PRAGMA index_list` |
| `fetch_all(conn, sql, params)` | Execute SQL and return `(columns, rows)` |

### Feature functions

| Function | Description |
|---|---|
| `show_tables(conn)` | Print all tables/views with row counts |
| `show_structure(conn, table)` | Print schema, FKs, and indexes for a table |
| `show_statistics(conn, table)` | Print per-column statistics (requires pandas) |
| `export_table(conn, table, fmt, out_dir)` | Export one table to CSV/JSON/Parquet |
| `export_all_tables(conn, fmt, out_dir)` | Export every table |
| `run_query(conn, sql)` | Execute SQL and render results |

### Rendering helpers

| Function | Description |
|---|---|
| `print_table(headers, rows, max_rows)` | Render a Unicode box-drawing table |
| `c(text, colour)` | Wrap text with an ANSI colour code |
| `header(text)` | Print a cyan section header |
| `success/error/info/warn(msg)` | Print a styled status message |

---

## Project Structure

```
db/
├── db_migrator.py   # main script — all logic lives here
├── sample.db        # example SQLite database for testing
├── README.md
└── CHANGELOG.md
```

---

## Running Tests

There is no automated test suite yet. To verify the tool manually:

```bash
# Smoke-test interactive mode against the bundled sample database
python db_migrator.py sample.db

# Smoke-test non-interactive query mode
python db_migrator.py sample.db --query "SELECT name FROM sqlite_master WHERE type='table'"

# Test CSV export
python db_migrator.py sample.db --export-all --format csv --out /tmp/test_export
ls /tmp/test_export
```

---

## License

MIT 
