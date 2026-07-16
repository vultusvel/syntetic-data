# Synthetic Data Studio

Conversational AI app for **synthetic data generation** and **natural-language
data querying** ("talk to your data"), built for the GridU GenAI practice.

- **LLM:** Gemini 2.5 Flash via **Vertex AI** (Google GenAI SDK) — using
  streaming, function calling and JSON/structured output.
- **UI:** Streamlit
- **DB:** PostgreSQL
- **Infra:** Docker (PostgreSQL + Langfuse)
- **Observability:** Langfuse

---

## Features

**Phase 1 — Data Generation**
- Upload a DDL schema (`.sql` / `.txt` / `.ddl`), up to 5–7 tables.
- Parses tables, columns, types, PK/FK/UNIQUE/NOT NULL constraints.
- Generates realistic, constraint-valid data (configurable rows/table, e.g. 1000),
  respecting **foreign keys** (parents generated before children, FKs sampled from
  real parent PKs).
- Free-text instructions + temperature control.
- Per-table preview, per-table edit via text feedback.
- Download each table as CSV or all as a ZIP; save to PostgreSQL.

**Phase 2 & 3 — Talk to your data**
- Ask questions in natural language.
- Gemini generates SQL via **function calling**, the query runs on PostgreSQL.
- Answer is **streamed** as text; results shown as a **table** and an
  auto-recommended **plot** (structured output → Plotly).

---

## Prerequisites (install once)

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

brew install python@3.12
brew install --cask google-cloud-sdk
brew install --cask docker   
```

## 1. Authenticate to GCP / Vertex AI

```bash
gcloud auth login
gcloud auth application-default login
gcloud config set project gd-gcp-gridu-genai
```

Make sure the **Vertex AI API** is enabled for the project.

## 2. Configure environment

```bash
cp .env.example .env
```

## 3. Start infrastructure (PostgreSQL + Langfuse)

```bash
docker compose up -d
```

- PostgreSQL → `localhost:5432`
- Langfuse UI → http://localhost:3000
  Open it, create an account + project, generate API keys, and paste
  `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` into `.env`
  (optional — the app runs without them; observability is just disabled).

## 4. Install Python dependencies

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## 5. Run the app

```bash
streamlit run app.py
```

Opens at http://localhost:8501

---

## How to use

1. **Data Generation** tab → upload `schemas/library_mgmt.ddl` (or your own),
   optionally add instructions, set rows + temperature → **Generate**.
2. Review each table, tweak with feedback, then **Save to database**.
3. **Talk to your data** tab → ask e.g.
   *"How many loans per genre?"*, *"Top 5 members by number of loans"*,
   *"Average salary per department"*.

---

## Project layout

```
.
├── app.py                  # Streamlit UI (2 tabs)
├── docker-compose.yml      # PostgreSQL + Langfuse
├── requirements.txt
├── .env.example
├── schemas/                # sample DDL schemas
└── src/
    ├── config.py           # env config
    ├── llm.py              # Gemini (Vertex AI) client + Langfuse tracing
    ├── ddl_parser.py       # DDL -> Schema (tables, cols, PK/FK)
    ├── db.py               # PostgreSQL access (SQLAlchemy + pandas)
    ├── data_generator.py   # Phase 1: specs (structured output) + row synthesis
    └── query_engine.py     # Phase 2/3: NL->SQL (function calling) + stream + chart
```

---

## Troubleshooting

- **`DefaultCredentialsError`** → run `gcloud auth application-default login`.
- **DB not reachable** → is `docker compose up -d` running? Is Docker Desktop open?
- **403 / permission on Vertex AI** → confirm you have the *Vertex AI User* role
  (`roles/aiplatform.user`) on `gd-gcp-gridu-genai` and the API is enabled.
- **404 model NOT_FOUND** → the model isn't available in your region. This project
  uses `gemini-2.5-flash` (set in `.env` as `GEMINI_MODEL`); adjust if needed.
- **Langfuse returns HTTP 500** → `ENCRYPTION_KEY` must be 64 hex chars; regenerate
  with `openssl rand -hex 32`, update `docker-compose.yml`, then
  `docker compose up -d langfuse`.
- **Langfuse shows nothing** → keys must be set in `.env` before starting Streamlit.




<img width="1912" height="1019" alt="Screenshot 2026-07-16 at 15 46 41" src="https://github.com/user-attachments/assets/2710245f-efb2-459f-849b-7c3d15a62e5a" />


<img width="1916" height="1032" alt="Screenshot 2026-07-16 at 15 48 34" src="https://github.com/user-attachments/assets/a51ae34d-d2d5-4223-b11f-77f559ab092f" />


<img width="1747" height="925" alt="Screenshot 2026-07-16 at 15 49 37" src="https://github.com/user-attachments/assets/1c79ee31-0612-49ad-807d-4af9f6409971" />


<img width="1920" height="1039" alt="Screenshot 2026-07-16 at 18 00 20" src="https://github.com/user-attachments/assets/b5d608b4-f89f-4c6a-96e2-664bb5addb1b" />




