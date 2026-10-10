"""Static guard: raw SQL in tests/test_migrations.py must match the models.

The Postgres integration job is the one suite that only runs in CI (it needs a
service container), so a typo in its hand-written SQL - a column that no longer
exists, say - ships red. These checks read the SQL out of the test file and
verify it against the SQLAlchemy metadata, which is available everywhere.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from sqlalchemy.schema import CreateTable

from app.db.base import Base

MIGRATION_TESTS = (
    Path(__file__).resolve().parent.parent.parent / "backend" / "tests" / "test_migrations.py"
)

# `alembic_version` is created and owned by Alembic itself, so it exists in the
# database but has no SQLAlchemy model. The integration tests legitimately
# query it to prove migration bookkeeping ran.
ALEMBIC_MANAGED_TABLES = {"alembic_version"}


@pytest.fixture(scope="module")
def table_columns() -> dict[str, set[str]]:
    """Import every model so the metadata is populated, then read it."""
    import app.models  # noqa: F401  (populates Base.metadata)

    return {
        table.name: {column.name for column in table.columns}
        for table in Base.metadata.sorted_tables
    }


def _sql_statements() -> list[tuple[int, str]]:
    """Every SQL string literal in the migration tests, with its line number."""
    source = MIGRATION_TESTS.read_text(encoding="utf-8")
    statements: list[tuple[int, str]] = []
    for match in re.finditer(
        r'text\(\s*("""(?P<block>.*?)"""|"(?P<single>[^"]*)")\)',
        source,
        re.DOTALL,
    ):
        sql = (match.group("block") or match.group("single") or "").strip()
        if sql:
            line = source.count("\n", 0, match.start()) + 1
            statements.append((line, sql))
    return statements


def test_migration_sql_only_names_columns_that_exist(table_columns: dict[str, set[str]]) -> None:
    """Every column in an INSERT / SELECT / DELETE must be a real column."""
    insert = re.compile(
        r"INSERT\s+INTO\s+(?P<table>\w+)\s*\((?P<cols>[^)]*)\)",
        re.IGNORECASE | re.DOTALL,
    )
    select = re.compile(r"SELECT\s+(?P<cols>[\w,\s.]+?)\s+FROM\s+(?P<table>\w+)", re.IGNORECASE)
    delete = re.compile(r"DELETE\s+FROM\s+(?P<table>\w+)", re.IGNORECASE)

    checked = 0
    for line, sql in _sql_statements():
        for match in insert.finditer(sql):
            table = match.group("table")
            assert table in table_columns, f"line {line}: unknown table {table!r}"
            for column in match.group("cols").split(","):
                column = column.strip()
                assert column in table_columns[table], (
                    f"line {line}: {table} has no column {column!r}; "
                    f"it has {sorted(table_columns[table])}"
                )
            checked += 1

        for match in select.finditer(sql):
            table = match.group("table")
            if table in ALEMBIC_MANAGED_TABLES:
                continue
            assert table in table_columns, f"line {line}: unknown table {table!r}"
            for column in match.group("cols").split(","):
                column = column.strip()
                if not column or column == "*":
                    continue
                assert column in table_columns[table], (
                    f"line {line}: {table} has no column {column!r}"
                )
            checked += 1

        for match in delete.finditer(sql):
            table = match.group("table")
            assert table in table_columns, f"line {line}: unknown table {table!r}"
            checked += 1

    # Five statements today (four business inserts plus the cascade delete). A
    # drop below that means the regex stopped matching, not that the SQL got
    # shorter - and a silently inert check is worse than a red one.
    assert checked >= 5, f"expected to verify several statements, only got {checked}"


def test_migration_tests_target_no_table_that_the_models_dropped(
    table_columns: dict[str, set[str]],
) -> None:
    """The integration tests must not assert on tables the models never define."""
    for table in (
        "users",
        "businesses",
        "user_business",
        "categories",
        "products",
        "customers",
        "suppliers",
        "purchases",
        "purchase_items",
        "sales",
        "sale_items",
        "inventory_transactions",
        "expenses",
        "audit_logs",
    ):
        assert table in table_columns, f"{table} is expected by the tests but not in the models"


def test_models_compile_to_ddl_without_error(table_columns: dict[str, set[str]]) -> None:
    """Sanity check on the fixture itself: the metadata must be non-trivial."""
    import app.models  # noqa: F401

    ddl = str(CreateTable(Base.metadata.sorted_tables[0]))
    assert "CREATE TABLE" in ddl
    assert len(table_columns) >= 14
