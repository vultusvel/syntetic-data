"""Synthetic Data Generator + Talk-to-your-data (Streamlit UI)."""
from __future__ import annotations

import io
import zipfile

import pandas as pd
import plotly.express as px
import streamlit as st

from src import config, db
from src import data_generator as gen
from src import ddl_parser
from src import query_engine as qe

st.set_page_config(page_title="Synthetic Data Studio", page_icon="🧪", layout="wide")


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def parent_pks_from_generated(schema: ddl_parser.Schema,
                              generated: dict[str, pd.DataFrame]) -> dict[str, list]:
    pks: dict[str, list] = {}
    for table in schema.tables:
        df = generated.get(table.name)
        if df is not None and table.primary_keys:
            pk = table.primary_keys[0]
            if pk in df.columns:
                pks[table.name.lower()] = df[pk].dropna().tolist()
    return pks


def build_zip(generated: dict[str, pd.DataFrame]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, df in generated.items():
            zf.writestr(f"{name}.csv", df.to_csv(index=False))
    return buf.getvalue()


def render_chart(spec: qe.ChartSpec, df: pd.DataFrame):
    if spec.chart_type == "none" or not spec.x or not spec.y:
        return
    title = spec.title or f"{spec.y} by {spec.x}"
    try:
        if spec.chart_type == "bar":
            fig = px.bar(df, x=spec.x, y=spec.y, title=title)
        elif spec.chart_type == "line":
            fig = px.line(df, x=spec.x, y=spec.y, title=title)
        elif spec.chart_type == "pie":
            fig = px.pie(df, names=spec.x, values=spec.y, title=title)
        elif spec.chart_type == "scatter":
            fig = px.scatter(df, x=spec.x, y=spec.y, title=title)
        else:
            return
        st.plotly_chart(fig, use_container_width=True)
    except Exception as e:
        st.info(f"Could not render chart: {e}")


# --------------------------------------------------------------------------
# Sidebar
# --------------------------------------------------------------------------
st.sidebar.title("🧪 Synthetic Data Studio")
tab = st.sidebar.radio("Navigation", ["Data Generation", "Talk to your data"])

st.sidebar.divider()
st.sidebar.caption("**Environment**")
db_ok = db.test_connection()
st.sidebar.write("PostgreSQL:", "🟢 connected" if db_ok else "🔴 not reachable")
st.sidebar.write("Langfuse:", "🟢 enabled" if config.LANGFUSE_ENABLED else "⚪ off")
st.sidebar.write(f"Model: `{config.GEMINI_MODEL}`")
st.sidebar.write(f"GCP project: `{config.GCP_PROJECT}`")


# --------------------------------------------------------------------------
# TAB 1 - Data Generation
# --------------------------------------------------------------------------
if tab == "Data Generation":
    st.header("Data Generation")

    col1, col2 = st.columns([2, 1])
    with col1:
        uploaded = st.file_uploader(
            "Upload a DDL schema (.sql, .txt or .ddl)",
            type=["sql", "txt", "ddl"],
        )
        instructions = st.text_area(
            "Instructions for the data (optional)",
            placeholder="e.g. Users mostly from Europe; orders from the last 2 years; "
                        "realistic book titles.",
            height=120,
        )
    with col2:
        n_rows = st.number_input("Rows per table", min_value=10, max_value=10000,
                                 value=1000, step=50)
        temperature = st.slider("Temperature", 0.0, 1.0, 0.7, 0.05)

    if uploaded is not None:
        ddl_text = uploaded.read().decode("utf-8", errors="ignore")
        schema = ddl_parser.parse_ddl(ddl_text)
        st.session_state["ddl_text"] = ddl_text
        st.session_state["schema"] = schema

        with st.expander("Parsed schema", expanded=False):
            st.code(ddl_parser.schema_summary(schema), language="text")
            order = " → ".join(t.name for t in schema.generation_order())
            st.caption(f"Generation order (FK-safe): {order}")

        if st.button("🚀 Generate", type="primary"):
            if not schema.tables:
                st.error("No CREATE TABLE statements found in the file.")
            else:
                bar = st.progress(0.0, text="Starting...")

                def _progress(p, msg):
                    bar.progress(min(p, 1.0), text=msg)

                try:
                    generated = gen.generate_all(
                        schema, instructions, int(n_rows), temperature,
                        progress=_progress)
                    st.session_state["generated"] = generated
                    bar.empty()
                    st.success(f"Generated {len(generated)} tables "
                               f"× ~{n_rows} rows.")
                except Exception as e:
                    bar.empty()
                    st.error(f"Generation failed: {e}")

    # ---- Preview / edit / download / save ----
    generated = st.session_state.get("generated")
    schema = st.session_state.get("schema")
    if generated and schema:
        st.divider()
        st.subheader("Generated tables")

        table_tabs = st.tabs(list(generated.keys()))
        for tab_ui, (name, df) in zip(table_tabs, generated.items()):
            with tab_ui:
                st.dataframe(df, use_container_width=True, height=300)
                st.caption(f"{len(df)} rows × {df.shape[1]} columns")

                c1, c2 = st.columns([3, 1])
                with c1:
                    fb = st.text_input(
                        "Apply changes to this table",
                        key=f"fb_{name}",
                        placeholder="e.g. make all salaries between 40000 and 90000",
                    )
                with c2:
                    st.write("")
                    st.write("")
                    if st.button("Submit", key=f"submit_{name}"):
                        table_obj = schema.get_table(name)
                        pks = parent_pks_from_generated(schema, generated)
                        with st.spinner("Regenerating..."):
                            try:
                                new_df = gen.apply_feedback(
                                    table_obj, fb, len(df), temperature, pks)
                                generated[name] = new_df
                                st.session_state["generated"] = generated
                                st.rerun()
                            except Exception as e:
                                st.error(f"Failed: {e}")

                st.download_button(
                    f"⬇️ Download {name}.csv",
                    data=df.to_csv(index=False).encode("utf-8"),
                    file_name=f"{name}.csv",
                    mime="text/csv",
                    key=f"dl_{name}",
                )

        st.divider()
        d1, d2 = st.columns(2)
        with d1:
            st.download_button(
                "⬇️ Download all tables (ZIP)",
                data=build_zip(generated),
                file_name="synthetic_data.zip",
                mime="application/zip",
            )
        with d2:
            if st.button("💾 Save to database", type="primary"):
                if not db_ok:
                    st.error("Database not reachable. Is `docker compose up` running?")
                else:
                    with st.spinner("Writing to PostgreSQL..."):
                        try:
                            db.run_ddl(
                                st.session_state["ddl_text"],
                                drop_first=True,
                                table_names=[t.name for t in schema.tables],
                            )
                            for t in schema.generation_order():
                                db.insert_dataframe(t.name, generated[t.name])
                            st.success("Saved. Open the 'Talk to your data' tab.")
                        except Exception as e:
                            st.error(f"Save failed: {e}")

else:
    st.header("Talk to your data")

    if not db_ok:
        st.warning("PostgreSQL is not reachable. Start it with `docker compose up -d`.")
        st.stop()

    tables = db.list_tables()
    if not tables:
        st.info("No data in the database yet. Generate data and click "
                "**Save to database** in the Data Generation tab first.")
        st.stop()

    st.caption("Tables available: " + ", ".join(
        f"{t} ({db.table_row_count(t)})" for t in tables))

    if "chat" not in st.session_state:
        st.session_state["chat"] = []

    for msg in st.session_state["chat"]:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
            if msg.get("sql"):
                with st.expander("SQL"):
                    st.code(msg["sql"], language="sql")
            if msg.get("df") is not None:
                st.dataframe(msg["df"], use_container_width=True)
            if msg.get("chart") is not None:
                render_chart(msg["chart"], msg["df"])

    question = st.chat_input("Ask a question about your data...")
    if question:
        st.session_state["chat"].append({"role": "user", "content": question})
        with st.chat_message("user"):
            st.markdown(question)

        with st.chat_message("assistant"):
            try:
                with st.spinner("Writing SQL..."):
                    sql = qe.nl_to_sql(question)
                with st.expander("SQL", expanded=False):
                    st.code(sql, language="sql")

                result_df = db.run_query(sql)
                answer = st.write_stream(qe.stream_answer(question, sql, result_df))

                if not result_df.empty:
                    st.dataframe(result_df, use_container_width=True)
                chart = qe.recommend_chart(question, result_df)
                render_chart(chart, result_df)

                st.session_state["chat"].append({
                    "role": "assistant",
                    "content": answer,
                    "sql": sql,
                    "df": result_df,
                    "chart": chart,
                })
            except Exception as e:
                err = f"Sorry, something went wrong: {e}"
                st.error(err)
                st.session_state["chat"].append({"role": "assistant", "content": err})
