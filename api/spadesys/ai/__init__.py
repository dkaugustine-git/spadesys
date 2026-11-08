"""AI assistant hooks (not wired up yet).

The plan: deterministic code (infer.py, hashing, validation) stays the source
of truth; an LLM *proposes* improvements that a human approves. Candidate jobs:

  - review_schema:   better names, semantic types (email, currency, PII), keys
  - propose_mapping: source columns -> warehouse model
  - draft_ddl:       Doris tables, incl. ARRAY<STRUCT> nesting suggestions
  - nl_to_sql:       English question -> SQL, shown before it runs

Providers sit behind one interface so self-hosted installs can run fully local
(e.g. Ollama) while others use a hosted model such as Claude.
"""

from __future__ import annotations

from typing import Any, Protocol


class Assistant(Protocol):
    def review_schema(self, inferred_schema: dict[str, Any], sample_rows: list[dict]) -> dict[str, Any]: ...


class NullAssistant:
    """Default: no suggestions. Keeps the platform fully functional with AI disabled."""

    def review_schema(self, inferred_schema: dict[str, Any], sample_rows: list[dict]) -> dict[str, Any]:
        return {"suggestions": []}
