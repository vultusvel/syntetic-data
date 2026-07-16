"""Phase 2 & 3 - Talk to your data.

Pipeline for a natural-language question:
  1. nl_to_sql()      - Gemini uses *function calling* to emit a SQL SELECT.
  2. db.run_query()   - the SQL is executed against PostgreSQL.
  3. stream_answer()  - Gemini *streams* a natural-language explanation.
  4. recommend_chart() - Gemini uses *structured output* to suggest a plot.
"""
from __future__ import annotations

from typing import Iterator, Literal, Optional

import pandas as pd
from pydantic import BaseModel

from src import config, db, llm


def nl_to_sql(question: str, temperature: float = 0.1) -> str:
    """Ask Gemini to produce a read-only SQL SELECT via a tool call."""
    from google.genai import types

    schema_text = db.introspect_schema()
    sql_tool = types.Tool(
        function_declarations=[
            types.FunctionDeclaration(
                name="execute_sql",
                description="Execute a single read-only SQL SELECT against the "
                            "PostgreSQL database and return the rows.",
                parameters=types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        "sql": types.Schema(
                            type=types.Type.STRING,
                            description="One read-only PostgreSQL SELECT statement.",
                        )
                    },
                    required=["sql"],
                ),
            )
        ]
    )

    prompt = f"""You are a data analyst. The PostgreSQL database has this schema:

{schema_text}

Answer the user's question by calling `execute_sql` with ONE valid, read-only
PostgreSQL SELECT statement. Never modify data. Use JOINs and aggregations as
needed. Quote identifiers only if necessary.

Question: {question}"""

    client = llm.get_client()
    with llm.trace_generation("nl_to_sql", question, temperature) as record:
        resp = client.models.generate_content(
            model=config.GEMINI_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=temperature,
                tools=[sql_tool],
            ),
        )
        record(str(resp.candidates[0].content if resp.candidates else resp))

    for part in resp.candidates[0].content.parts:
        fc = getattr(part, "function_call", None)
        if fc and fc.name == "execute_sql":
            args = dict(fc.args)
            return args.get("sql", "").strip()

    
    text = (resp.text or "").strip()
    return text.strip("`").replace("sql\n", "").strip()


def stream_answer(question: str, sql: str, df: pd.DataFrame,
                  temperature: float = 0.3) -> Iterator[str]:
    """Yield the answer text chunk-by-chunk (streaming)."""
    from google.genai import types

    preview = df.head(30).to_markdown(index=False) if not df.empty else "(no rows)"
    prompt = f"""User question: {question}

SQL executed:
{sql}

Query result (first rows):
{preview}

Total rows returned: {len(df)}

Write a concise, friendly answer to the user's question based ONLY on this
result. Mention the key numbers. Do not invent data."""

    client = llm.get_client()
    stream = client.models.generate_content_stream(
        model=config.GEMINI_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(temperature=temperature),
    )
    collected: list[str] = []
    for chunk in stream:
        if chunk.text:
            collected.append(chunk.text)
            yield chunk.text

    lf = llm.get_langfuse()
    if lf is not None:
        t = lf.trace(name="answer")
        t.generation(name="answer", model=config.GEMINI_MODEL,
                     input=prompt, output="".join(collected)).end()
        lf.flush()


class ChartSpec(BaseModel):
    chart_type: Literal["none", "bar", "line", "pie", "scatter"]
    x: Optional[str] = None
    y: Optional[str] = None
    title: Optional[str] = None
    reason: Optional[str] = None


def recommend_chart(question: str, df: pd.DataFrame,
                    temperature: float = 0.1) -> ChartSpec:
    """Suggest an appropriate plot for the result (or 'none')."""
    if df.empty or df.shape[1] < 2 or df.shape[0] < 2:
        return ChartSpec(chart_type="none")

    from google.genai import types

    cols = ", ".join(f"{c} ({df[c].dtype})" for c in df.columns)
    prompt = f"""Given this query result with columns: {cols}
and {len(df)} rows, for the question "{question}", recommend the single best
chart. Choose chart_type from none/bar/line/pie/scatter and set x and y to
actual column names. Use "none" if a chart would not help."""

    client = llm.get_client()
    try:
        with llm.trace_generation("chart", prompt, temperature) as record:
            resp = client.models.generate_content(
                model=config.GEMINI_MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=temperature,
                    response_mime_type="application/json",
                    response_schema=ChartSpec,
                ),
            )
            record(resp.text)
        spec = resp.parsed
        if spec.x and spec.x not in df.columns:
            spec.x = None
        if spec.y and spec.y not in df.columns:
            spec.y = None
        if spec.chart_type != "none" and (not spec.x or not spec.y):
            return ChartSpec(chart_type="none")
        return spec
    except Exception:
        return ChartSpec(chart_type="none")
