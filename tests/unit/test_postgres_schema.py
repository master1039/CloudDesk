"""P2-2 structural tests for PostgreSQL DDL, RLS, and baseline migration."""

from __future__ import annotations

import re
from pathlib import Path

import app.models  # noqa: F401 -- registers every ORM table with Base.metadata
from app.core.database import Base
from sqlalchemy.dialects import postgresql

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATABASE_DIR = PROJECT_ROOT / "database"
SCHEMA_SQL = (DATABASE_DIR / "schema.sql").read_text(encoding="utf-8")
RLS_SQL = (DATABASE_DIR / "rls_policies.sql").read_text(encoding="utf-8")
MIGRATION_SQL = (DATABASE_DIR / "migrations" / "0001_initial_schema.sql").read_text(
    encoding="utf-8"
)


def _ddl_tables(sql: str) -> dict[str, str]:
    return {
        match.group("name"): match.group("body")
        for match in re.finditer(
            r"CREATE TABLE IF NOT EXISTS public\.(?P<name>\w+)\s*\((?P<body>.*?)\n\);",
            sql,
            flags=re.DOTALL,
        )
    }


def _ddl_columns(table_body: str) -> dict[str, str]:
    columns: dict[str, str] = {}
    type_pattern = re.compile(
        r"^(?P<name>[a-z_]+)\s+"
        r"(?P<type>VARCHAR\(\d+\)|NUMERIC\(\d+,\s*\d+\)|TIMESTAMPTZ|BIGINT|INTEGER|BOOLEAN|TEXT|JSON)"
        r"(?=\s|,|$)"
    )
    for raw_line in table_body.splitlines():
        match = type_pattern.match(raw_line.strip().rstrip(","))
        if match:
            columns[match.group("name")] = _normalize_type(match.group("type"))
    return columns


def _normalize_type(value: str) -> str:
    normalized = value.upper().replace("TIMESTAMPTZ", "TIMESTAMP WITH TIME ZONE")
    return re.sub(r"\s*,\s*", ", ", normalized)


def _first_table_array(sql: str) -> set[str]:
    match = re.search(
        r"FOREACH table_name IN ARRAY ARRAY\[(?P<tables>.*?)\]\s*LOOP",
        sql,
        flags=re.DOTALL,
    )
    assert match is not None
    return set(re.findall(r"'([a-z_]+)'", match.group("tables")))


def test_schema_tables_and_column_types_match_orm_metadata() -> None:
    ddl_tables = _ddl_tables(SCHEMA_SQL)

    assert set(ddl_tables) == set(Base.metadata.tables)
    dialect = postgresql.dialect()
    for table_name, orm_table in Base.metadata.tables.items():
        ddl_columns = _ddl_columns(ddl_tables[table_name])
        assert set(ddl_columns) == {column.name for column in orm_table.columns}
        for column in orm_table.columns:
            orm_type = _normalize_type(column.type.compile(dialect=dialect))
            assert ddl_columns[column.name] == orm_type, (
                f"{table_name}.{column.name}: SQL has {ddl_columns[column.name]}, ORM has {orm_type}"
            )


def test_schema_uses_portable_json_uuid_strings_and_all_update_triggers() -> None:
    sql_without_comments = re.sub(r"--.*$", "", SCHEMA_SQL, flags=re.MULTILINE)
    assert not re.search(r"\bJSONB\b", sql_without_comments, flags=re.IGNORECASE)
    for table_name, table_body in _ddl_tables(SCHEMA_SQL).items():
        columns = _ddl_columns(table_body)
        assert columns["id"] == "VARCHAR(36)", table_name
        assert columns["created_at"] == "TIMESTAMP WITH TIME ZONE", table_name
        assert columns["updated_at"] == "TIMESTAMP WITH TIME ZONE", table_name

    assert "CREATE OR REPLACE FUNCTION public.set_updated_at()" in SCHEMA_SQL
    assert "CREATE TRIGGER trg_%I_updated_at" in SCHEMA_SQL
    assert _first_table_array(SCHEMA_SQL) == set(Base.metadata.tables)


def test_schema_indexes_match_orm_metadata() -> None:
    orm_indexes = {index.name for table in Base.metadata.tables.values() for index in table.indexes}
    ddl_indexes = set(re.findall(r"CREATE (?:UNIQUE )?INDEX IF NOT EXISTS (\w+)", SCHEMA_SQL))

    assert ddl_indexes == orm_indexes


def test_rls_covers_every_table_and_keeps_browser_writes_closed() -> None:
    assert _first_table_array(RLS_SQL) == set(Base.metadata.tables)
    assert "ENABLE ROW LEVEL SECURITY" in RLS_SQL
    assert "CREATE POLICY service_role_all" in RLS_SQL
    assert "CREATE POLICY profile_self_read" in RLS_SQL
    assert "CREATE POLICY support_read" in RLS_SQL
    assert "SECURITY DEFINER" in RLS_SQL
    assert "SET search_path = public" in RLS_SQL
    assert not re.search(
        r"FOR\s+(?:INSERT|UPDATE|DELETE).*?TO\s+authenticated", RLS_SQL, flags=re.DOTALL
    )


def test_initial_migration_is_self_contained_and_matches_authoritative_sql() -> None:
    migrations = sorted((DATABASE_DIR / "migrations").glob("*.sql"))

    assert [migration.name for migration in migrations] == ["0001_initial_schema.sql"]
    assert SCHEMA_SQL.strip() in MIGRATION_SQL
    assert RLS_SQL.strip() in MIGRATION_SQL
    assert "\\i" not in MIGRATION_SQL
    assert "\\ir" not in MIGRATION_SQL
