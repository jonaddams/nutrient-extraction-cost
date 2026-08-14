"""Joins what a cell extracted to what the answer key says, one field at a time.

Every judgement about a single field belongs to compare_field. This module only
decides which fields to ask about, and how to add up the answers.
"""

from __future__ import annotations

from typing import Any

from .answers import AnswerKey, field_type
from .compare import compare_field, summarise_verdicts


def score_records(
    records: list[dict[str, Any]], key: AnswerKey
) -> list[dict[str, Any]]:
    """Each record, plus a `score` — or a `score` of None when unscoreable.

    Unscoreable is a real outcome with two causes, and neither is the provider's
    fault: the key has no entry for the document, or the harness could not read
    what the cell answered. Both must stay distinguishable from "got everything
    wrong", which is what a zero would say.

    Only fields the key covers are scored. A provider that extracts extra fields
    is neither rewarded nor penalised for them — otherwise its score would
    depend on how complete our key happens to be.
    """
    out: list[dict[str, Any]] = []
    for record in records:
        fields = key.fields_for(record["docId"])
        extracted = record.get("extracted")
        if not fields or extracted is None:
            out.append({**record, "score": None})
            continue

        verdicts = {
            name: compare_field(
                extracted.get(name), entry, field_type(entry.get("value"))
            )
            for name, entry in fields.items()
        }
        out.append(
            {
                **record,
                "score": {**summarise_verdicts(list(verdicts.values())),
                          "verdicts": verdicts},
            }
        )
    return out


def score_summary(scored: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Per provider and half. The halves are never averaged together — whether
    the SDK's grounding buys accuracy is the entire question being asked.

    Two different counts of "not scored" live here, and they must stay
    distinct: `unscoreable` counts whole RECORDS the harness could not read at
    all or that the key has no document entry for (score is None) — it shows
    how many rows contributed nothing. `unverifiedFields` counts individual FIELDS
    within scoreable records that came back "unverified" — the key had no entry
    for that particular field, so summarise_verdicts already excluded it from
    the accuracy denominator. Without surfacing this count, a report could show
    a high accuracy computed over far fewer fields than the key actually
    contains, with nothing saying so.
    """
    buckets: dict[tuple[str, bool], dict[str, int]] = {}
    for record in scored:
        bucket = buckets.setdefault(
            (record["providerId"], bool(record["withNutrient"])),
            {"matched": 0, "verified": 0, "unscoreable": 0, "unverifiedFields": 0},
        )
        score = record.get("score")
        if score is None:
            bucket["unscoreable"] += 1
            continue
        bucket["matched"] += score["matched"]
        bucket["verified"] += score["verified"]
        bucket["unverifiedFields"] += sum(
            1 for v in score["verdicts"].values() if v == "unverified"
        )

    rows = []
    for (provider_id, with_nutrient), bucket in sorted(buckets.items()):
        rows.append(
            {
                "providerId": provider_id,
                "withNutrient": with_nutrient,
                "matched": bucket["matched"],
                "verified": bucket["verified"],
                # None, never 0.0. A provider with nothing scoreable has no
                # accuracy; 0.0 says it got everything wrong.
                "accuracy": (
                    bucket["matched"] / bucket["verified"]
                    if bucket["verified"]
                    else None
                ),
                "unscoreable": bucket["unscoreable"],
                "unverifiedFields": bucket["unverifiedFields"],
            }
        )
    return rows
