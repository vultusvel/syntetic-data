"""Parse SQL DDL (CREATE TABLE ...) into a structured schema.

Extracts tables, columns, data types, nullability, primary keys, unique
constraints and foreign keys, and computes a topological insert order so that
parent tables are generated before the children that reference them.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

import sqlparse


@dataclass
class Column:
    name: str
    data_type: str          
    raw_type: str          
    nullable: bool = True
    is_primary_key: bool = False
    is_unique: bool = False
    is_serial: bool = False
    default: Optional[str] = None
    fk_table: Optional[str] = None
    fk_column: Optional[str] = None
    length: Optional[int] = None
    precision: Optional[int] = None
    scale: Optional[int] = None


@dataclass
class Table:
    name: str
    columns: list[Column] = field(default_factory=list)

    @property
    def primary_keys(self) -> list[str]:
        return [c.name for c in self.columns if c.is_primary_key]

    @property
    def foreign_keys(self) -> list[Column]:
        return [c for c in self.columns if c.fk_table]

    def get_column(self, name: str) -> Optional[Column]:
        for c in self.columns:
            if c.name.lower() == name.lower():
                return c
        return None


@dataclass
class Schema:
    tables: list[Table] = field(default_factory=list)

    def get_table(self, name: str) -> Optional[Table]:
        for t in self.tables:
            if t.name.lower() == name.lower():
                return t
        return None

    def generation_order(self) -> list[Table]:
        """Topological order: parents before children (self-refs ignored)."""
        name_to_table = {t.name.lower(): t for t in self.tables}
        deps: dict[str, set[str]] = {}
        for t in self.tables:
            d = set()
            for fk in t.foreign_keys:
                ref = fk.fk_table.lower()
                if ref != t.name.lower() and ref in name_to_table:
                    d.add(ref)
            deps[t.name.lower()] = d

        ordered: list[str] = []
        while deps:
            ready = [n for n, d in deps.items() if not (d - set(ordered))]
            if not ready:  
                ready = list(deps.keys())
            for n in sorted(ready):
                ordered.append(n)
                deps.pop(n, None)
        return [name_to_table[n] for n in ordered]

_CONSTRAINT_KEYWORDS = ("primary", "foreign", "unique", "constraint", "check")


def _split_top_level(body: str) -> list[str]:
    """Split a CREATE TABLE body on commas that are not inside parentheses."""
    parts, depth, current = [], 0, []
    for ch in body:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append("".join(current).strip())
            current = []
        else:
            current.append(ch)
    if "".join(current).strip():
        parts.append("".join(current).strip())
    return parts


def _normalise_type(raw: str) -> tuple[str, Optional[int], Optional[int], Optional[int]]:
    """Return (base_type, length, precision, scale)."""
    raw = raw.strip()
    m = re.match(r"([a-zA-Z_ ]+)\s*(\(([^)]*)\))?", raw)
    base = (m.group(1) if m else raw).strip().lower()
    length = precision = scale = None
    if m and m.group(3):
        nums = [int(x) for x in re.findall(r"\d+", m.group(3))]
        if len(nums) == 1:
            length = precision = nums[0]
        elif len(nums) >= 2:
            precision, scale = nums[0], nums[1]
    base = re.sub(r"\s+", " ", base)
    return base, length, precision, scale


def _parse_column(defn: str) -> Optional[Column]:
    tokens = defn.strip()
    m = re.match(r'["`]?(\w+)["`]?\s+(.*)', tokens, re.DOTALL)
    if not m:
        return None
    name, rest = m.group(1), m.group(2).strip()

    kw = re.search(
        r"\b(NOT|NULL|PRIMARY|UNIQUE|DEFAULT|REFERENCES|CHECK|GENERATED|CONSTRAINT)\b",
        rest, re.IGNORECASE)
    raw_type = (rest[: kw.start()] if kw else rest).strip()
    base, length, precision, scale = _normalise_type(raw_type)

    col = Column(
        name=name,
        data_type=base,
        raw_type=raw_type,
        length=length,
        precision=precision,
        scale=scale,
    )
    upper = rest.upper()
    if base in ("serial", "bigserial", "smallserial"):
        col.is_serial = True
        col.nullable = False
    if "NOT NULL" in upper:
        col.nullable = False
    if "PRIMARY KEY" in upper:
        col.is_primary_key = True
        col.nullable = False
    if re.search(r"\bUNIQUE\b", upper):
        col.is_unique = True

    dm = re.search(r"DEFAULT\s+([^,]+?)(?:\s+(?:NOT|REFERENCES|UNIQUE|CHECK)\b|$)",
                   rest, re.IGNORECASE)
    if dm:
        col.default = dm.group(1).strip()

    fm = re.search(r'REFERENCES\s+["`]?(\w+)["`]?\s*\(\s*["`]?(\w+)["`]?\s*\)',
                   rest, re.IGNORECASE)
    if fm:
        col.fk_table, col.fk_column = fm.group(1), fm.group(2)
    return col


def _apply_table_constraint(defn: str, table: Table) -> None:
    upper = defn.upper()
    if upper.startswith("PRIMARY KEY"):
        for name in re.findall(r"\w+", defn[len("PRIMARY KEY"):]):
            col = table.get_column(name)
            if col:
                col.is_primary_key = True
                col.nullable = False
    elif upper.startswith("UNIQUE"):
        for name in re.findall(r"\w+", defn[len("UNIQUE"):]):
            col = table.get_column(name)
            if col:
                col.is_unique = True
    elif "FOREIGN KEY" in upper:
        m = re.search(
            r'FOREIGN\s+KEY\s*\(\s*["`]?(\w+)["`]?\s*\)\s*'
            r'REFERENCES\s+["`]?(\w+)["`]?\s*\(\s*["`]?(\w+)["`]?\s*\)',
            defn, re.IGNORECASE)
        if m:
            col = table.get_column(m.group(1))
            if col:
                col.fk_table, col.fk_column = m.group(2), m.group(3)


def parse_ddl(ddl_text: str) -> Schema:
    """Parse DDL text into a Schema object."""
    schema = Schema()
    statements = sqlparse.split(ddl_text)
    for stmt in statements:
        stmt = re.sub(r"^\s*--[^\n]*\n", "", stmt.strip(), flags=re.MULTILINE).strip()
        if not stmt or not re.search(r"CREATE\s+TABLE", stmt, re.IGNORECASE):
            continue
        m = re.search(
            r'CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?["`]?(\w+)["`]?\s*\((.*)\)',
            stmt, re.IGNORECASE | re.DOTALL)
        if not m:
            continue
        table = Table(name=m.group(1))
        body = m.group(2)
        body = body.rsplit(")", 0)[0] if body.endswith(");") else body

        for defn in _split_top_level(body):
            if not defn:
                continue
            first_word = defn.split()[0].lower()
            if first_word in _CONSTRAINT_KEYWORDS:
                _apply_table_constraint(defn, table)
            else:
                col = _parse_column(defn)
                if col:
                    table.columns.append(col)
        schema.tables.append(table)

    return schema


def schema_summary(schema: Schema) -> str:
    """Compact text description of the schema (fed to the LLM)."""
    lines = []
    for t in schema.tables:
        lines.append(f"TABLE {t.name}:")
        for c in t.columns:
            flags = []
            if c.is_primary_key:
                flags.append("PK")
            if c.is_serial:
                flags.append("SERIAL")
            if not c.nullable:
                flags.append("NOT NULL")
            if c.is_unique:
                flags.append("UNIQUE")
            if c.fk_table:
                flags.append(f"FK->{c.fk_table}.{c.fk_column}")
            flag_str = f" [{', '.join(flags)}]" if flags else ""
            lines.append(f"  - {c.name}: {c.raw_type}{flag_str}")
        lines.append("")
    return "\n".join(lines)
