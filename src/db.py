"""PostgreSQL access layer (SQLAlchemy + pandas)."""
from __future__ import annotations

import pandas as pd
import sqlparse
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from src import config

_engine: Engine | None = None


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = create_engine(config.db_url(), pool_pre_ping=True)
    return _engine


def test_connection() -> bool:
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


def run_ddl(ddl_text: str, drop_first: bool = True, table_names: list[str] | None = None) -> None:
    """Create the tables described by `ddl_text`.

    If drop_first, existing tables with the same names are dropped (CASCADE)
    so the schema can be regenerated cleanly.
    """
    engine = get_engine()
    with engine.begin() as conn:
        if drop_first and table_names:
            for name in reversed(table_names):
                conn.execute(text(f'DROP TABLE IF EXISTS "{name}" CASCADE'))
        for stmt in sqlparse.split(ddl_text):
            stmt = stmt.strip().rstrip(";")
            if stmt:
                conn.execute(text(stmt))


def insert_dataframe(table: str, df: pd.DataFrame) -> None:
    """Append a DataFrame to an existing table."""
    if df is None or df.empty:
        return
    df.to_sql(table, get_engine(), if_exists="append", index=False, method="multi",
              chunksize=500)


def run_query(sql: str) -> pd.DataFrame:
    """Run a read-only SQL query and return the result as a DataFrame."""
    with get_engine().connect() as conn:
        return pd.read_sql(text(sql), conn)


def list_tables() -> list[str]:
    sql = """
        SELECT table_name FROM information_schema.tables
        WHERE table_schema = 'public'
        ORDER BY table_name
    """
    return run_query(sql)["table_name"].tolist()


def table_row_count(table: str) -> int:
    return int(run_query(f'SELECT COUNT(*) AS n FROM "{table}"')["n"].iloc[0])


def introspect_schema() -> str:
    """Return a text description of tables/columns currently in the DB.

    Used to ground the Talk-to-your-data SQL generation.
    """
    sql = """
        SELECT table_name, column_name, data_type
        FROM information_schema.columns
        WHERE table_schema = 'public'
        ORDER BY table_name, ordinal_position
    """
    df = run_query(sql)
    lines: list[str] = []
    for table_name, group in df.groupby("table_name"):
        cols = ", ".join(f"{r.column_name} {r.data_type}" for r in group.itertuples())
        lines.append(f"{table_name}({cols})")
    return "\n".join(lines)
