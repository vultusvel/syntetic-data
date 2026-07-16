"""Phase 1 - Synthetic data generation.

Strategy (hybrid, LLM-guided):
  1. For every "data" column (i.e. not a serial PK and not a foreign key) we ask
     Gemini - using structured / JSON output - for a *generation spec*: how that
     column should be filled (a Faker method, a categorical set, a numeric range,
     a date range, ...). This is where the LLM adds realism and honours the user's
     free-text instructions.
  2. Rows are then materialised in Python from those specs. Primary keys are
     sequences, foreign keys are sampled from the parent tables' real PK values,
     and UNIQUE columns are de-duplicated - so referential integrity and
     constraints are always respected, even for thousands of rows.
"""
from __future__ import annotations

import random
from datetime import date, datetime, timedelta
from typing import Literal, Optional

import pandas as pd
from faker import Faker
from pydantic import BaseModel

from src import config, llm
from src.ddl_parser import Column, Schema, Table, schema_summary

fake = Faker()

class ColumnSpec(BaseModel):
    column: str
    strategy: Literal[
        "faker", "categorical", "integer", "float",
        "date", "datetime", "boolean", "text", "constant",
    ]
    faker_method: Optional[str] = None      
    choices: Optional[list[str]] = None     
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    decimals: Optional[int] = None
    start_date: Optional[str] = None  
    end_date: Optional[str] = None
    true_probability: Optional[float] = None
    max_length: Optional[int] = None
    constant_value: Optional[str] = None


def _columns_needing_specs(table: Table) -> list[Column]:
    return [
        c for c in table.columns
        if not (c.is_serial and c.is_primary_key) and not c.fk_table
    ]

def generate_specs(
    table: Table,
    user_instructions: str,
    temperature: float,
) -> dict[str, ColumnSpec]:
    cols = _columns_needing_specs(table)
    if not cols:
        return {}

    col_desc = "\n".join(
        f"  - {c.name}: type={c.raw_type}"
        f"{' UNIQUE' if c.is_unique else ''}"
        f"{'' if c.nullable else ' NOT NULL'}"
        for c in cols
    )
    prompt = f"""You design realistic synthetic data. For the table below, return a
generation spec for EACH listed column.

Table: {table.name}
Columns:
{col_desc}

User instructions (may be empty): {user_instructions or "(none)"}

Rules for choosing a strategy per column:
- People names/emails/addresses/phones/companies/cities/countries -> "faker" with
  a matching faker_method (e.g. name, first_name, last_name, email, city, country,
  company, phone_number, street_address).
- A small fixed set of options (status, category, genre, cuisine, role) ->
  "categorical" with a sensible `choices` list.
- Names/titles of THINGS (book titles, product names, project names, restaurant
  names, menu items) -> "categorical" with a diverse, REALISTIC `choices` pool of
  25-40 believable domain-specific values that match the user's instructions.
  Do NOT use "text" for these - "text" produces meaningless lorem-ipsum.
- Reserve "text" ONLY for genuinely long free-form prose (descriptions, comments).
- Whole numbers -> "integer" with realistic, REAL-WORLD-SCALE min_value/max_value
  (e.g. a book's total_copies is 1-20, an age 18-90, a quantity 1-10 - never
  hundreds of thousands unless the column truly implies it).
- Money/decimals -> "float" with realistic min_value/max_value and `decimals`
  matching the column's scale.
- Dates -> "date"; timestamps -> "datetime". Provide start_date/end_date in
  YYYY-MM-DD form and keep them realistic (e.g. join dates in the past, birth
  dates 1940-2005).
- Booleans -> "boolean" with true_probability (0..1).
- Respect column length limits and the user's instructions.
Return one spec object per column, using the exact column names."""

    client = llm.get_client()
    from google.genai import types

    with llm.trace_generation(f"specs:{table.name}", prompt, temperature) as record:
        resp = client.models.generate_content(
            model=config.GEMINI_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=temperature,
                response_mime_type="application/json",
                response_schema=list[ColumnSpec],
            ),
        )
        record(resp.text)

    specs: list[ColumnSpec] = resp.parsed or []
    return {s.column: s for s in specs}


def _parse_date(s: Optional[str], default: date) -> date:
    if not s:
        return default
    try:
        return datetime.strptime(s[:10], "%Y-%m-%d").date()
    except ValueError:
        return default


def _value_from_spec(spec: ColumnSpec, col: Column, used: set):
    strat = spec.strategy
    if strat == "faker":
        method = spec.faker_method or "word"
        try:
            val = getattr(fake, method)()
        except Exception:
            val = fake.word()
        if col.length and isinstance(val, str):
            val = val[: col.length]
        # enforce UNIQUE by retrying / suffixing
        if col.is_unique:
            tries = 0
            while val in used and tries < 20:
                try:
                    val = getattr(fake, method)()
                except Exception:
                    val = fake.word()
                tries += 1
            if val in used and isinstance(val, str):
                val = f"{val[:(col.length - 6) if col.length else len(val)]}{random.randint(0, 99999)}"
        return val

    if strat == "categorical":
        return random.choice(spec.choices) if spec.choices else fake.word()

    if strat == "integer":
        lo = int(spec.min_value if spec.min_value is not None else 0)
        hi = int(spec.max_value if spec.max_value is not None else lo + 1000)
        return random.randint(min(lo, hi), max(lo, hi))

    if strat == "float":
        lo = spec.min_value if spec.min_value is not None else 0.0
        hi = spec.max_value if spec.max_value is not None else lo + 1000.0
        decimals = spec.decimals if spec.decimals is not None else (col.scale or 2)
        # clamp to the column's declared numeric range where possible
        val = random.uniform(min(lo, hi), max(lo, hi))
        return round(val, decimals)

    if strat == "date":
        start = _parse_date(spec.start_date, date.today() - timedelta(days=3650))
        end = _parse_date(spec.end_date, date.today())
        delta = max((end - start).days, 1)
        return start + timedelta(days=random.randint(0, delta))

    if strat == "datetime":
        start = _parse_date(spec.start_date, date.today() - timedelta(days=3650))
        end = _parse_date(spec.end_date, date.today())
        delta = max((end - start).days, 1)
        d = start + timedelta(days=random.randint(0, delta))
        return datetime(d.year, d.month, d.day,
                        random.randint(0, 23), random.randint(0, 59), random.randint(0, 59))

    if strat == "boolean":
        p = spec.true_probability if spec.true_probability is not None else 0.5
        return random.random() < p

    if strat == "text":
        max_len = spec.max_length or col.length or 200
        return fake.text(max_nb_chars=max(5, min(max_len, 500)))[:max_len]

    if strat == "constant":
        return spec.constant_value

    return fake.word()


def generate_table_data(
    table: Table,
    specs: dict[str, ColumnSpec],
    n_rows: int,
    parent_pks: dict[str, list],
) -> pd.DataFrame:
    """Build a DataFrame of n_rows for one table."""
    rows: list[dict] = []
    unique_tracker: dict[str, set] = {c.name: set() for c in table.columns if c.is_unique}
    self_pk_pool: list = []  # for self-referencing FKs (e.g. manager_id)

    pk_col = table.primary_keys[0] if table.primary_keys else None

    for i in range(1, n_rows + 1):
        row: dict = {}
        for col in table.columns:
            # 1) serial primary key -> sequence
            if col.is_primary_key and (col.is_serial or col.data_type in ("integer", "int", "bigint")) \
                    and len(table.primary_keys) == 1:
                row[col.name] = i
                continue
            # 2) foreign key -> sample from parent's real PKs
            if col.fk_table:
                pool = self_pk_pool if col.fk_table.lower() == table.name.lower() \
                    else parent_pks.get(col.fk_table.lower(), [])
                if not pool:
                    row[col.name] = None
                elif col.nullable and random.random() < 0.1:
                    row[col.name] = None
                else:
                    row[col.name] = random.choice(pool)
                continue
            spec = specs.get(col.name)

            if spec is None:
                row[col.name] = None if col.nullable else fake.word()
            else:
                used = unique_tracker.get(col.name, set())
                val = _value_from_spec(spec, col, used)
                if col.is_unique:
                    used.add(val)
                row[col.name] = val
        rows.append(row)

        if pk_col and pk_col in row and row[pk_col] is not None:
            self_pk_pool.append(row[pk_col])

    return pd.DataFrame(rows)


def generate_all(
    schema: Schema,
    user_instructions: str,
    n_rows: int,
    temperature: float,
    progress=None,
) -> dict[str, pd.DataFrame]:
    """Generate data for every table, respecting FK order and integrity."""
    result: dict[str, pd.DataFrame] = {}
    parent_pks: dict[str, list] = {}
    ordered = schema.generation_order()

    for idx, table in enumerate(ordered):
        if progress:
            progress(idx / len(ordered), f"Generating {table.name}...")
        specs = generate_specs(table, user_instructions, temperature)
        df = generate_table_data(table, specs, n_rows, parent_pks)
        result[table.name] = df
        
        if table.primary_keys:
            pk = table.primary_keys[0]
            if pk in df.columns:
                parent_pks[table.name.lower()] = df[pk].dropna().tolist()

    if progress:
        progress(1.0, "Done")
    return result


def apply_feedback(
    table: Table,
    feedback: str,
    n_rows: int,
    temperature: float,
    parent_pks: dict[str, list],
) -> pd.DataFrame:
    """Regenerate ONE table incorporating the user's free-text feedback."""
    specs = generate_specs(table, feedback, temperature)
    return generate_table_data(table, specs, n_rows, parent_pks)
