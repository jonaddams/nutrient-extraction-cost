"""Where the providers disagree — the one accuracy mode needing no ground truth.

This is the default for a prospect's own corpus, and it is also the tool's
argument in miniature: where two providers return different answers, a reader
cannot tell which is right without a citation to check. That is precisely what
the grounded half buys and the direct half does not.

Values are compared with compare_field rather than string equality, so
"$345,015.00" and 345015 agree. A pair the comparator cannot judge counts as
neither agreement nor disagreement: an ambiguous comparison is not evidence of a
difference, and inflating the disagreement rate with ambiguity would overstate
the case this tool is making.
"""

from __future__ import annotations

from typing import Any

from .answers import field_type
from .compare import compare_field


def _label(record: dict[str, Any]) -> str:
    half = "sdk" if record.get("withNutrient") else "direct"
    return f"{record['providerId']}:{half}"


def agreement(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_doc: dict[str, dict[str, dict[str, Any]]] = {}
    for record in records:
        extracted = record.get("extracted")
        if not extracted:
            continue
        for field, value in extracted.items():
            by_doc.setdefault(record["docId"], {}).setdefault(field, {})[
                _label(record)
            ] = value

    rows: list[dict[str, Any]] = []
    for doc_id in sorted(by_doc):
        for field in sorted(by_doc[doc_id]):
            values = by_doc[doc_id][field]
            # One opinion is not a conflict. Counting it as one would inflate
            # the disagreement rate with fields nobody contested.
            if len(values) < 2:
                continue
            labels = sorted(values)
            reference = values[labels[0]]
            verdicts = [
                compare_field(
                    values[label], {"value": reference}, field_type(reference)
                )
                for label in labels[1:]
            ]
            disagreed = any(v == "mismatch" for v in verdicts)
            distinct = 1 + sum(1 for v in verdicts if v == "mismatch")
            rows.append(
                {
                    "docId": doc_id,
                    "field": field,
                    "values": values,
                    "agree": not disagreed,
                    "distinct": distinct,
                }
            )
    return rows


def agreement_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    agreed = sum(1 for r in rows if r["agree"])
    return {
        "fields": len(rows),
        "agreed": agreed,
        "disagreed": len(rows) - agreed,
        # None, never 0.0: nothing comparable is not total disagreement.
        "rate": agreed / len(rows) if rows else None,
    }
