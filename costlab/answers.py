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


def load_answers_csv(path: str | Path) -> AnswerKey:
    """A prospect's key as a spreadsheet: docId, field, value, source.

    Required columns are checked up front, against the CSV's HEADER, and their
    absence raises. The header is read from the reader's own `fieldnames`
    rather than from the first data row: a file with a valid header and zero
    data rows has `fieldnames` populated but no rows, and reading the header
    from a row would misreport that file as missing every required column
    ("Found: nothing") when the real problem is that it has no data — sending
    a prospect to rename columns that are already correct. Genuinely missing
    columns (including a file with no header row at all, where `fieldnames`
    is None) still raise the column-name error, unchanged.

    Reading zero DATA rows is its own, separate failure, checked only once the
    header itself is confirmed correct: silently reporting zero rows would
    report every provider as unscoreable, which looks like a model problem and
    is not one.
    """
    import csv

    reader = csv.DictReader(Path(path).read_text().splitlines())
    required = {"docId", "field", "value"}
    present = set(reader.fieldnames or [])
    missing = required - present
    if missing:
        raise ValueError(
            f"answer key CSV is missing required column(s): {', '.join(sorted(missing))}. "
            f"Found: {', '.join(sorted(present)) or 'nothing'}"
        )

    rows = list(reader)
    if not rows:
        raise ValueError(
            "answer key CSV has a valid header but no data rows — add at least "
            "one docId,field,value row."
        )

    documents: dict[str, dict[str, dict[str, Any]]] = {}
    for row in rows:
        raw = (row.get("value") or "").strip()
        # A numeric-looking value becomes a number so it compares with tolerance
        # rather than as text: "345015.00" and 345015 are the same answer.
        try:
            value: Any = float(raw) if raw and raw.replace(".", "", 1).lstrip("-").isdigit() else raw
        except ValueError:
            value = raw
        if isinstance(value, float) and value.is_integer():
            value = int(value)
        documents.setdefault(row["docId"], {})[row["field"]] = {
            "value": value,
            "source": (row.get("source") or "supplied answer key").strip(),
        }
    return AnswerKey(checked_on="supplied", documents=documents)


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
