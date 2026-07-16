"""Gemini (Vertex AI) client + Langfuse observability helpers.

All calls to Gemini go through this module so that:
  * the client is created once (singleton), authenticated via Vertex AI
    using Application Default Credentials (`gcloud auth application-default login`);
  * every generation is optionally traced in Langfuse.
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Optional

from google import genai

from src import config

_client: Optional[genai.Client] = None


def get_client() -> genai.Client:
    """Return a singleton Vertex-AI-backed Gemini client."""
    global _client
    if _client is None:
        _client = genai.Client(
            vertexai=True,
            project=config.GCP_PROJECT,
            location=config.GCP_LOCATION,
        )
    return _client


_langfuse = None


def get_langfuse():
    """Return a Langfuse client, or None if not configured."""
    global _langfuse
    if not config.LANGFUSE_ENABLED:
        return None
    if _langfuse is None:
        from langfuse import Langfuse

        _langfuse = Langfuse(
            public_key=config.LANGFUSE_PUBLIC_KEY,
            secret_key=config.LANGFUSE_SECRET_KEY,
            host=config.LANGFUSE_HOST,
        )
    return _langfuse


@contextmanager
def trace_generation(name: str, model_input: Any, temperature: float | None = None):
    """Context manager that records one LLM generation in Langfuse.

    Usage:
        with trace_generation("generate-specs", prompt, temperature=0.7) as record:
            resp = client.models.generate_content(...)
            record(resp.text)          # attach the output
    Works as a no-op when Langfuse is not configured.
    """
    lf = get_langfuse()
    output_holder: dict[str, Any] = {}

    def record(output: Any):
        output_holder["output"] = output

    if lf is None:
        yield record
        return

    trace = lf.trace(name=name)
    generation = trace.generation(
        name=name,
        model=config.GEMINI_MODEL,
        input=model_input,
        model_parameters={"temperature": temperature} if temperature is not None else {},
    )
    try:
        yield record
    finally:
        generation.end(output=output_holder.get("output"))
        lf.flush()
