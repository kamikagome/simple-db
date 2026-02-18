# Changelog

All notable changes to this project will be documented in this file.

This project follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/) conventions.

> **Learning project** — this repo is a hands-on exercise in using
> [Claude Code](https://claude.ai/claude-code) for data engineering tasks.
> The goal is to learn how to build, document, and iterate on data tooling
> with an AI coding assistant.

---

## [Unreleased]

- Automated test suite
- Support for multiple simultaneous database connections
- Schema diff / migration generation

---

## [0.1.0] — 2026-02-17

### Added

- `db_migrator.py` — initial implementation of the interactive SQLite explorer
  - Interactive terminal menu (list tables, inspect schema, statistics, export, SQL query)
  - Non-interactive CLI flags: `--query`, `--export`, `--export-all`, `--format`, `--out`
  - Unicode box-drawing table renderer with auto-sized columns
  - ANSI colour output with helpers (`c`, `header`, `success`, `error`, `info`, `warn`)
  - Per-column statistics using pandas (numeric: min/max/mean/median; text: mode)
  - Export to CSV, JSON, and Parquet (Parquet requires `pyarrow`)
  - Foreign-key and index inspection via SQLite PRAGMA statements
  - Graceful handling of `Ctrl-C` / `Ctrl-D` in all interactive prompts
  - Full docstrings on every public function and class
- `sample.db` — bundled SQLite database for local testing
- `README.md` — project documentation with usage examples and API reference
- `CHANGELOG.md` — this file
