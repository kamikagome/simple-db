#!/usr/bin/env python3
"""
db_migrator.py — Interactive SQLite database explorer and exporter.

Provides a terminal-based menu for inspecting SQLite databases, viewing table
schemas and statistics, running ad-hoc SQL queries, and exporting data to CSV,
JSON, or Parquet.

Usage:
    python db_migrator.py <database.db>
    python db_migrator.py <database.db> --query "SELECT * FROM users LIMIT 5"
    python db_migrator.py <database.db> --export <table> --format csv --out ./output
    python db_migrator.py <database.db> --export-all --format parquet --out ./output

Dependencies:
    Required : Python 3.7+, sqlite3 (stdlib)
    Optional : pandas  — table statistics (pip install pandas)
               pyarrow — Parquet export   (pip install pyarrow)
"""

import argparse
import csv
import json
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

try:
    import pandas as pd
    HAS_PANDAS = True
except ImportError:
    HAS_PANDAS = False

try:
    import pyarrow as pa          # noqa: F401  (imported for side-effects check)
    import pyarrow.parquet as pq  # noqa: F401
    HAS_PARQUET = True
except ImportError:
    HAS_PARQUET = False

# ─── ANSI colours ─────────────────────────────────────────────────────────────

RESET  = "\033[0m"
BOLD   = "\033[1m"
DIM    = "\033[2m"
RED    = "\033[91m"
GREEN  = "\033[92m"
YELLOW = "\033[93m"
BLUE   = "\033[94m"  # noqa: F841
CYAN   = "\033[96m"
WHITE  = "\033[97m"
GREY   = "\033[90m"


def c(text, colour):
    """Wrap *text* with an ANSI *colour* code followed by a reset sequence.

    Args:
        text:   The string to colour.
        colour: An ANSI escape sequence string (e.g. ``CYAN``, ``BOLD + RED``).

    Returns:
        str: The coloured string, safe to print to a terminal.
    """
    return f"{colour}{text}{RESET}"


def header(text):
    """Print a cyan section header with horizontal rules above and below.

    Args:
        text: The heading string to display.
    """
    width = 60
    print()
    print(c("─" * width, CYAN))
    print(c(f"  {text}", BOLD + CYAN))
    print(c("─" * width, CYAN))


def success(msg):
    """Print a green success message prefixed with a check-mark.

    Args:
        msg: The message to display.
    """
    print(c(f"  ✓  {msg}", GREEN))


def error(msg):
    """Print a red error message prefixed with a cross.

    Args:
        msg: The message to display.
    """
    print(c(f"  ✗  {msg}", RED))


def info(msg):
    """Print a grey informational message prefixed with a bullet.

    Args:
        msg: The message to display.
    """
    print(c(f"  •  {msg}", GREY))


def warn(msg):
    """Print a yellow warning message prefixed with an exclamation mark.

    Args:
        msg: The message to display.
    """
    print(c(f"  !  {msg}", YELLOW))


# ─── Table / box rendering ─────────────────────────────────────────────────────

def col_widths(headers, rows):
    """Calculate the maximum display width required for each column.

    Compares header label lengths against every cell value in *rows* and
    returns the element-wise maximum so that the table box fits snugly.

    Args:
        headers: Sequence of column header strings.
        rows:    Iterable of row tuples/lists whose length matches *headers*.

    Returns:
        list[int]: Per-column maximum character widths.
    """
    widths = [len(str(h)) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(str(cell)))
    return widths


def print_table(headers, rows, max_rows=200):
    """Render a list of rows as a Unicode box-drawing table to stdout.

    Columns are sized automatically to fit the widest cell. If *rows* exceeds
    *max_rows*, a warning is printed and the surplus rows are omitted.

    Args:
        headers:  Sequence of column header strings.
        rows:     Iterable of row tuples/lists to display.
        max_rows: Maximum number of data rows to render (default: 200).
    """
    if not rows:
        info("(no rows)")
        return
    display = rows[:max_rows]
    widths = col_widths(headers, display)
    sep = "┼".join("─" * (w + 2) for w in widths)
    top = "┬".join("─" * (w + 2) for w in widths)
    bot = "┴".join("─" * (w + 2) for w in widths)

    print(c("┌" + top + "┐", DIM))
    head_cells = " │ ".join(c(str(h).ljust(widths[i]), BOLD + WHITE) for i, h in enumerate(headers))
    print(c("│ ", DIM) + head_cells + c(" │", DIM))
    print(c("├" + sep + "┤", DIM))
    for row in display:
        cells = " │ ".join(str(cell).ljust(widths[i]) for i, cell in enumerate(row))
        print(c("│ ", DIM) + cells + c(" │", DIM))
    print(c("└" + bot + "┘", DIM))
    if len(rows) > max_rows:
        warn(f"Showing first {max_rows} of {len(rows)} rows")


# ─── Database helpers ──────────────────────────────────────────────────────────

def get_tables(conn):
    """Return a sorted list of user-defined table names in the database.

    System tables (e.g. ``sqlite_sequence``) are included because they appear
    in ``sqlite_master``.  Views are excluded.

    Args:
        conn: An open :class:`sqlite3.Connection`.

    Returns:
        list[str]: Table names in alphabetical order.
    """
    cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    return [r[0] for r in cur.fetchall()]


def get_views(conn):
    """Return a sorted list of view names defined in the database.

    Args:
        conn: An open :class:`sqlite3.Connection`.

    Returns:
        list[str]: View names in alphabetical order.
    """
    cur = conn.execute("SELECT name FROM sqlite_master WHERE type='view' ORDER BY name")
    return [r[0] for r in cur.fetchall()]


def get_row_count(conn, table):
    """Return the number of rows in *table*, or ``"?"`` on error.

    Uses a simple ``SELECT COUNT(*)`` so it may be slow on very large tables
    without a covering index.

    Args:
        conn:  An open :class:`sqlite3.Connection`.
        table: Table name (will be double-quoted to handle spaces/keywords).

    Returns:
        int | str: Row count, or the string ``"?"`` if the query fails.
    """
    try:
        cur = conn.execute(f'SELECT COUNT(*) FROM "{table}"')
        return cur.fetchone()[0]
    except Exception:
        return "?"


def get_schema(conn, table):
    """Return column metadata for *table* via ``PRAGMA table_info``.

    Each row is a 6-tuple: ``(cid, name, type, notnull, dflt_value, pk)``.

    Args:
        conn:  An open :class:`sqlite3.Connection`.
        table: Table or view name.

    Returns:
        list[tuple]: One tuple per column as returned by SQLite's PRAGMA.
    """
    cur = conn.execute(f'PRAGMA table_info("{table}")')
    return cur.fetchall()


def get_foreign_keys(conn, table):
    """Return foreign-key relationships for *table* via ``PRAGMA foreign_key_list``.

    Args:
        conn:  An open :class:`sqlite3.Connection`.
        table: Table name.

    Returns:
        list[tuple]: PRAGMA rows describing each FK constraint.
    """
    cur = conn.execute(f'PRAGMA foreign_key_list("{table}")')
    return cur.fetchall()


def get_indexes(conn, table):
    """Return index definitions for *table* via ``PRAGMA index_list``.

    Args:
        conn:  An open :class:`sqlite3.Connection`.
        table: Table name.

    Returns:
        list[tuple]: PRAGMA rows describing each index.
    """
    cur = conn.execute(f'PRAGMA index_list("{table}")')
    return cur.fetchall()


def fetch_all(conn, sql, params=()):
    """Execute *sql* and return all results as ``(columns, rows)``.

    Works for both SELECT statements (returns column names and data rows) and
    DML statements (returns empty lists).

    Args:
        conn:   An open :class:`sqlite3.Connection`.
        sql:    SQL statement string.
        params: Optional sequence of bind parameters (default: empty tuple).

    Returns:
        tuple[list[str], list[tuple]]: ``(column_names, data_rows)``.
    """
    cur = conn.execute(sql, params)
    cols = [d[0] for d in cur.description] if cur.description else []
    rows = cur.fetchall()
    return cols, rows


# ─── Feature functions ─────────────────────────────────────────────────────────

def show_tables(conn):
    """Display all tables and views with their row counts.

    Prints a formatted table listing every table (with live row count) and every
    view (with a dash for count, as views are virtual) in the connected database.

    Args:
        conn: An open :class:`sqlite3.Connection`.
    """
    header("Tables & Views")
    tables = get_tables(conn)
    views  = get_views(conn)

    if not tables and not views:
        warn("Database is empty — no tables or views found.")
        return

    rows = []
    for t in tables:
        rows.append((t, "table", get_row_count(conn, t)))
    for v in views:
        rows.append((v, "view", "—"))

    print_table(["Name", "Type", "Row count"], rows)
    print()
    info(f"{len(tables)} table(s), {len(views)} view(s)")


def show_structure(conn, table=None):
    """Display the schema of a table or view.

    Shows column names, types, and constraints (PK, NOT NULL, DEFAULT).
    Also renders foreign-key relationships and index definitions when present.

    If *table* is ``None`` the user is prompted to choose from a list.

    Args:
        conn:  An open :class:`sqlite3.Connection`.
        table: Name of the table or view to inspect, or ``None`` to prompt.
    """
    tables = get_tables(conn) + get_views(conn)
    if not tables:
        warn("No tables found.")
        return

    if table is None:
        table = choose_table(tables, "Inspect structure of")
        if table is None:
            return

    header(f"Structure: {table}")

    cols = get_schema(conn, table)
    rows = []
    for col in cols:
        cid, name, ctype, notnull, dflt, pk = col
        flags = []
        if pk:       flags.append("PK")
        if notnull:  flags.append("NOT NULL")
        if dflt is not None: flags.append(f"DEFAULT {dflt}")
        rows.append((cid, name, ctype or "ANY", ", ".join(flags)))
    print_table(["#", "Column", "Type", "Constraints"], rows)

    fks = get_foreign_keys(conn, table)
    if fks:
        print()
        print(c("  Foreign keys:", BOLD))
        fk_rows = [(f[3], f[2], f[4]) for f in fks]  # from_col, to_table, to_col
        print_table(["Column", "References table", "References column"], fk_rows)

    idxs = get_indexes(conn, table)
    if idxs:
        print()
        print(c("  Indexes:", BOLD))
        idx_rows = [(i[1], "UNIQUE" if i[2] else "") for i in idxs]
        print_table(["Index name", "Unique"], idx_rows)


def show_statistics(conn, table=None):
    """Display per-column statistics for a table using pandas.

    For numeric columns: non-null count, null count, unique values, min, max,
    mean, and median.  For text columns: non-null count, null count, unique
    values, and the most frequent (mode) value.

    Requires ``pandas``; prints an error and returns early if unavailable.

    If *table* is ``None`` the user is prompted to choose from a list.

    Args:
        conn:  An open :class:`sqlite3.Connection`.
        table: Table name to analyse, or ``None`` to prompt.
    """
    if not HAS_PANDAS:
        error("pandas is required for statistics. Install with: pip install pandas")
        return

    tables = get_tables(conn)
    if not tables:
        warn("No tables found.")
        return

    if table is None:
        table = choose_table(tables, "Show statistics for")
        if table is None:
            return

    header(f"Statistics: {table}")

    df = pd.read_sql_query(f'SELECT * FROM "{table}"', conn)
    total = len(df)
    info(f"Total rows: {total}  |  Columns: {len(df.columns)}")
    print()

    stats_rows = []
    for col in df.columns:
        s = df[col]
        nulls = int(s.isna().sum())
        uniq  = int(s.nunique(dropna=True))
        dtype = str(s.dtype)

        if pd.api.types.is_numeric_dtype(s):
            numeric = s.dropna()
            mn   = f"{numeric.min():.4g}" if len(numeric) else "—"
            mx   = f"{numeric.max():.4g}" if len(numeric) else "—"
            mean = f"{numeric.mean():.4g}" if len(numeric) else "—"
            med  = f"{numeric.median():.4g}" if len(numeric) else "—"
            stats_rows.append((col, dtype, total - nulls, nulls, uniq, mn, mx, mean, med))
        else:
            top = s.dropna().mode()
            top_val = str(top.iloc[0])[:20] if len(top) else "—"
            stats_rows.append((col, dtype, total - nulls, nulls, uniq, "—", "—", "—", top_val))

    print_table(
        ["Column", "Type", "Non-null", "Null", "Unique", "Min", "Max", "Mean", "Median/Top"],
        stats_rows
    )


def export_table(conn, table=None, fmt=None, out_dir=None):
    """Export a single table to CSV, JSON, or Parquet.

    The output file is named ``<table>_<YYYYMMDD_HHMMSS>.<ext>`` and written
    to *out_dir* (created automatically if it does not exist).

    If *table*, *fmt*, or *out_dir* are ``None`` the user is prompted
    interactively.  Parquet export requires ``pyarrow``.

    Args:
        conn:    An open :class:`sqlite3.Connection`.
        table:   Table name to export, or ``None`` to prompt.
        fmt:     One of ``"csv"``, ``"json"``, ``"parquet"``, or ``None`` to prompt.
        out_dir: Destination directory path string, or ``None`` to prompt.
    """
    tables = get_tables(conn)
    if not tables:
        warn("No tables found.")
        return

    if table is None:
        table = choose_table(tables, "Export")
        if table is None:
            return

    if fmt is None:
        formats = ["csv", "json"]
        if HAS_PARQUET:
            formats.append("parquet")
        fmt = choose_option("Export format", formats)
        if fmt is None:
            return

    if fmt == "parquet" and not HAS_PARQUET:
        error("pyarrow is required for Parquet export. Install with: pip install pyarrow")
        return

    if out_dir is None:
        out_dir = input(c("  Output directory (default: current dir): ", CYAN)).strip() or "."

    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename  = out_path / f"{table}_{timestamp}.{fmt}"

    header(f"Exporting '{table}' → {fmt.upper()}")
    info(f"Reading data...")

    cols, rows = fetch_all(conn, f'SELECT * FROM "{table}"')
    info(f"Rows: {len(rows)}  |  Columns: {len(cols)}")

    if fmt == "csv":
        with open(filename, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(cols)
            writer.writerows(rows)

    elif fmt == "json":
        data = [dict(zip(cols, row)) for row in rows]
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, default=str)

    elif fmt == "parquet":
        df = pd.read_sql_query(f'SELECT * FROM "{table}"', conn)
        df.to_parquet(filename, index=False)

    size = os.path.getsize(filename)
    success(f"Saved: {filename}  ({_human_size(size)})")


def run_query(conn, sql=None):
    """Execute a SQL statement and display the results as a formatted table.

    In interactive mode (``sql=None``), prompts for multi-line SQL input; an
    empty line signals end-of-input.  DML statements (INSERT/UPDATE/DELETE) are
    committed automatically and the affected-row count is shown.

    Args:
        conn: An open :class:`sqlite3.Connection`.
        sql:  SQL string to execute, or ``None`` to prompt the user.
    """
    header("SQL Query")
    if sql is None:
        print(c("  Enter SQL (empty line to cancel):", CYAN))
        lines = []
        while True:
            try:
                line = input(c("  sql> ", BOLD + YELLOW))
            except (EOFError, KeyboardInterrupt):
                print()
                return
            if not line.strip():
                if lines:
                    break
                return
            lines.append(line)
        sql = " ".join(lines)

    if not sql.strip():
        return

    print()
    try:
        cols, rows = fetch_all(conn, sql)
        if cols:
            print_table(cols, rows)
            info(f"{len(rows)} row(s) returned")
        else:
            # DML statement — commit and report affected rows
            conn.commit()
            success(f"Query OK  ({conn.execute('SELECT changes()').fetchone()[0]} row(s) affected)")
    except sqlite3.Error as e:
        error(f"SQL error: {e}")


def export_all_tables(conn, fmt, out_dir):
    """Export every table in the database to the specified format.

    Iterates over all user-defined tables returned by :func:`get_tables` and
    calls :func:`export_table` for each one.  Views are not exported.

    Args:
        conn:    An open :class:`sqlite3.Connection`.
        fmt:     One of ``"csv"``, ``"json"``, or ``"parquet"``.
        out_dir: Destination directory path string.
    """
    tables = get_tables(conn)
    if not tables:
        warn("No tables found.")
        return
    for t in tables:
        export_table(conn, table=t, fmt=fmt, out_dir=out_dir)


# ─── UI helpers ───────────────────────────────────────────────────────────────

def choose_table(tables, action="Select"):
    """Prompt the user to pick a table from a numbered list.

    Displays the list with 1-based indices and reads a single line of input.
    Returns ``None`` if the user enters ``0``, an empty string, or presses
    ``Ctrl-C`` / ``Ctrl-D``.

    Args:
        tables: Sequence of table name strings to display.
        action: Verb used in the prompt label (default: ``"Select"``).

    Returns:
        str | None: The chosen table name, or ``None`` to cancel.
    """
    if not tables:
        warn("No tables available.")
        return None
    print()
    for i, t in enumerate(tables, 1):
        print(f"  {c(str(i), YELLOW)}. {t}")
    print(f"  {c('0', GREY)}. Cancel")
    while True:
        try:
            raw = input(c(f"\n  {action} (number): ", CYAN)).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return None
        if raw == "0" or raw == "":
            return None
        if raw.isdigit() and 1 <= int(raw) <= len(tables):
            return tables[int(raw) - 1]
        error("Invalid choice.")


def choose_option(prompt, options):
    """Prompt the user to select one item from a numbered list of options.

    Displays the options with 1-based indices and reads a single line of input.
    Returns ``None`` if the user enters ``0``, an empty string, or presses
    ``Ctrl-C`` / ``Ctrl-D``.

    Args:
        prompt:  Label displayed in the input prompt.
        options: Sequence of option strings to display.

    Returns:
        str | None: The chosen option string, or ``None`` to cancel.
    """
    print()
    for i, o in enumerate(options, 1):
        print(f"  {c(str(i), YELLOW)}. {o}")
    print(f"  {c('0', GREY)}. Cancel")
    while True:
        try:
            raw = input(c(f"\n  {prompt} (number): ", CYAN)).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return None
        if raw == "0" or raw == "":
            return None
        if raw.isdigit() and 1 <= int(raw) <= len(options):
            return options[int(raw) - 1]
        error("Invalid choice.")


def _human_size(n):
    """Convert a byte count to a human-readable string (e.g. ``"1.4 MB"``).

    Args:
        n: Size in bytes.

    Returns:
        str: Formatted size string with the most appropriate unit.
    """
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


# ─── Main menu ─────────────────────────────────────────────────────────────────

MENU = [
    ("List tables & views",         show_tables),
    ("Inspect table structure",     show_structure),
    ("Show table statistics",       show_statistics),
    ("Export table",                export_table),
    ("Run SQL query",               run_query),
]


def print_menu(db_path):
    """Print the main navigation menu with the active database path.

    Args:
        db_path: :class:`pathlib.Path` or string of the open database file.
    """
    print()
    print(c("╔══════════════════════════════════════════════╗", CYAN))
    print(c("║", CYAN) + c("          DB Migrator / Explorer              ", BOLD + WHITE) + c("║", CYAN))
    print(c("╚══════════════════════════════════════════════╝", CYAN))
    print(c(f"  Database: {db_path}", DIM))
    print()
    for i, (label, _) in enumerate(MENU, 1):
        print(f"  {c(str(i), YELLOW + BOLD)}. {label}")
    print()
    print(f"  {c('q', RED)}. Quit")
    print()


def interactive_loop(conn, db_path):
    """Run the interactive menu loop until the user chooses to quit.

    Continuously prints the main menu, reads a single character choice, and
    dispatches to the corresponding feature function.  ``KeyboardInterrupt``
    inside a feature is caught gracefully so the loop can continue.

    Args:
        conn:    An open :class:`sqlite3.Connection`.
        db_path: Path displayed in the menu header.
    """
    while True:
        print_menu(db_path)
        try:
            raw = input(c("  Choice: ", BOLD + CYAN)).strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if raw in ("q", "quit", "exit"):
            break

        if raw.isdigit() and 1 <= int(raw) <= len(MENU):
            label, fn = MENU[int(raw) - 1]
            try:
                fn(conn)
            except KeyboardInterrupt:
                print()
                info("Interrupted.")
            input(c("\n  Press Enter to continue…", DIM))
        else:
            error("Invalid choice — enter a number or 'q'.")

    print(c("\n  Bye!\n", GREY))


# ─── Entry point ───────────────────────────────────────────────────────────────

def build_parser():
    """Build and return the CLI argument parser.

    Returns:
        argparse.ArgumentParser: Configured parser with all supported flags.
    """
    p = argparse.ArgumentParser(
        prog="db_migrator",
        description="Interactive SQLite explorer and exporter",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python db_migrator.py data.db
  python db_migrator.py data.db --query "SELECT * FROM users LIMIT 10"
  python db_migrator.py data.db --export users --format json --out ./exports
  python db_migrator.py data.db --export-all --format parquet --out ./exports
        """,
    )
    p.add_argument("database", help="Path to the SQLite database file")
    p.add_argument("--query", "-q", metavar="SQL",
                   help="Run a SQL query and print results, then exit")
    p.add_argument("--export", "-e", metavar="TABLE",
                   help="Export a specific table (use with --format)")
    p.add_argument("--export-all", "-E", action="store_true",
                   help="Export all tables (use with --format)")
    p.add_argument("--format", "-f", choices=["csv", "json", "parquet"], default="csv",
                   help="Export format (default: csv)")
    p.add_argument("--out", "-o", metavar="DIR", default=".",
                   help="Output directory for exports (default: current dir)")
    return p


def main():
    """Parse CLI arguments and dispatch to interactive or non-interactive mode.

    Non-interactive modes (``--query``, ``--export``, ``--export-all``) run the
    requested operation and exit.  When no mode flag is given, the interactive
    terminal menu is launched instead.

    Exits with code 1 if the database file does not exist or cannot be opened.
    """
    parser = build_parser()
    args   = parser.parse_args()

    db_path = Path(args.database)
    if not db_path.exists():
        print(c(f"Error: file not found: {db_path}", RED), file=sys.stderr)
        sys.exit(1)

    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
    except sqlite3.Error as e:
        print(c(f"Error opening database: {e}", RED), file=sys.stderr)
        sys.exit(1)

    # ── Non-interactive modes ──
    if args.query:
        conn.row_factory = None
        run_query(conn, sql=args.query)
        conn.close()
        return

    if args.export:
        conn.row_factory = None
        export_table(conn, table=args.export, fmt=args.format, out_dir=args.out)
        conn.close()
        return

    if args.export_all:
        conn.row_factory = None
        export_all_tables(conn, fmt=args.format, out_dir=args.out)
        conn.close()
        return

    # ── Interactive mode ──
    conn.row_factory = None
    interactive_loop(conn, db_path)
    conn.close()


if __name__ == "__main__":
    main()
