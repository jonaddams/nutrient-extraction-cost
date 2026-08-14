"""Answer keys, and the schemas derived from them.

A key is evidence. Every bundled value carries the line it was read off the
document, because "verified" with no source is indistinguishable from a guess
one session later. Nothing here is ever populated from a model's output: this
whole feature exists to catch models being wrong.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_BUNDLED = Path(__file__).with_name("corpus") / "answers.json"


@dataclass(frozen=True)
class AnswerKey:
    checked_on: str
    documents: dict[str, dict[str, dict[str, Any]]]
    note: str = ""

    def fields_for(self, doc_id: str) -> dict[str, dict[str, Any]]:
        return self.documents.get(doc_id, {})


def load_answers(path: str | Path | None = None) -> AnswerKey:
    data = json.loads(Path(path or _BUNDLED).read_text())
    return AnswerKey(
        checked_on=data.get("checkedOn", ""),
        documents=data.get("documents", {}),
        note=data.get("note", ""),
    )


def field_type(value: Any) -> str:
    """The `type_` argument `compare_field` expects for a key value.

    Booleans map to "string" rather than "boolean" on purpose: no bundled key
    field is a boolean, and claiming a type the key does not contain would add
    an untested comparator path. If a prospect's key needs booleans, add the
    mapping AND the golden cases together.
    """
    if isinstance(value, bool):
        return "string"
    if isinstance(value, (int, float)):
        return "number"
    return "string"


def schema_for(key: AnswerKey, doc_id: str) -> dict[str, Any] | None:
    """A JSON schema covering exactly the key's fields for one document.

    None — not an empty schema — when the key has no entry. An empty schema
    extracts nothing and would score every field as a mismatch, reporting a
    provider as completely wrong when the truth is that we never asked it
    anything.
    """
    fields = key.fields_for(doc_id)
    if not fields:
        return None
    properties = {
        name: {
            "type": "number" if field_type(entry.get("value")) == "number" else "string",
            "description": name,
        }
        for name, entry in fields.items()
    }
    return {
        "type": "object",
        "properties": properties,
        "required": sorted(properties),
        # Required by Anthropic, which rejects an object schema without it.
        "additionalProperties": False,
    }
