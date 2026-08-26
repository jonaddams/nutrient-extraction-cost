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
    how many rows contributed nothing. `unverifiedFields` counts individual
    FIELDS *within scoreable records* that came back "unverified" — these are
    fields the key DOES cover (score_records only ever builds a verdict for a
    field the key has an entry for), but the comparison could not be made
    confidently: an ambiguous date format, a number that would not parse. The
    key having no entry at all for a field is a different case entirely — that
    field is simply never asked about here, so it never reaches this count.
    Mislabeling this as "fields the key doesn't cover" would send a reader off
    to add key entries that already exist, instead of fixing the ambiguous
    format that is the actual, fixable cause. Without surfacing this count at
    all, a report could show a high accuracy computed over far fewer fields
    than the key actually covers, with nothing saying why some were excluded.
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


# Ascending order of what a rung costs you and what it makes you concede. This
# ordering IS the argument the report makes: a self-hosted model landing near a
# frontier one is only legible as a finding if the rungs descend from the
# most expensive, least private option to the cheapest, most private one.
_RUNG_ORDER = {"frontier": 0, "hosted": 1, "self-hosted": 2}


def rung(provider: Any) -> str:
    """Which tier of the cost-and-control trade-off a provider sits on.

    Derived from what a provider already declares rather than from a second
    hand-kept list: a frontier model says so in `kind`, and among open-weight
    models the one that needs no credential is by definition the one running on
    hardware you control. A provider added later therefore lands on the right
    rung without anyone remembering to update a mapping — the failure mode of a
    parallel list is that it goes stale silently, and this ordering is load
    bearing for the report's whole argument.
    """
    if provider is None:
        return "hosted"
    if provider.kind == "frontier":
        return "frontier"
    return "hosted" if provider.credential_env else "self-hosted"


def accuracy_by_model(
    rows: list[dict[str, Any]],
    providers: dict[str, Any],
    models: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """`score_summary`'s per-half rows, paired onto one row per model.

    Same numbers, regrouped. The two halves stay separate dicts carrying their
    own denominators, because they are routinely computed over different
    document counts — the harness skips a direct cell whose SDK cell failed —
    and a single shared denominator would render that difference invisible while
    inviting exactly the like-for-like reading the data does not support.

    A half with no records at all is `None`, distinct from a half that ran and
    had nothing scoreable (present, with `accuracy` of `None`). Collapsing those
    two is the shape of three separate defects in this project's history.

    Each row carries the resolved model id as well as the provider label,
    because two of the four labels are not model names — "OpenAI" is a vendor
    and "Local runtime" is a place. In a band organised by model, a label that
    names neither the weights nor anything a reader could re-run is the same
    true-label-around-an-unsupported-claim shape as the twelfth defect.
    """
    models = models or {}
    paired: dict[str, dict[str, Any]] = {}
    for row in rows:
        entry = paired.setdefault(
            row["providerId"],
            {
                "providerId": row["providerId"],
                "label": (
                    providers[row["providerId"]].label
                    if row["providerId"] in providers
                    else row["providerId"]
                ),
                "model": models.get(row["providerId"], ""),
                "rung": rung(providers.get(row["providerId"])),
                "direct": None,
                "sdk": None,
            },
        )
        half = {k: v for k, v in row.items() if k not in ("providerId", "withNutrient")}
        entry["sdk" if row["withNutrient"] else "direct"] = half

    return sorted(
        paired.values(), key=lambda r: (_RUNG_ORDER[r["rung"]], r["label"])
    )


def annotate_agreement(
    rows: list[dict[str, Any]], key: AnswerKey | None
) -> list[dict[str, Any]]:
    """Each agreement row, plus the answer key's value and a verdict per
    configuration.

    Appendix C could only print what each configuration returned, which leaves a
    reader looking at eight strings with no way to tell which is right -- the
    very sentence that appendix uses to explain what the grounded half buys. The
    key holds the value and `compare_field` already decides the verdict; neither
    reached the page.

    Returns NEW rows. The agreement rate is computed off the originals, so
    mutating them would move a published number as a side effect of adding a
    column.

    Three verdict states, not two, and the third is the reason a bare tick/cross
    column would be a downgrade: "unverified" is a comparison the comparator
    declined to make -- an ambiguous slash date, a number it could not parse --
    and calling that a mismatch marks a provider wrong for our own uncertainty.
    A field the key does not cover gets NO verdict at all, which is different
    again: it is not unverified, it is unasked.
    """
    out = []
    for row in rows:
        fields = key.fields_for(row["docId"]) if key else {}
        entry = fields.get(row["field"])
        verdicts: dict[str, str] = {}
        if entry is not None:
            type_ = field_type(entry.get("value"))
            verdicts = {
                config: compare_field(value, entry, type_)
                for config, value in row["values"].items()
            }
        out.append({
            **row,
            # The key's value verbatim, not normalised: this is the reference a
            # reader checks the others against, so it must read as the document
            # prints it rather than as the comparator sees it.
            "expected": entry.get("value") if entry is not None else None,
            "expectedSource": entry.get("source") if entry is not None else None,
            # Carried so the page can explain a column of non-committal marks.
            # A reader shown an expected value and eight tildes, with no reason
            # given, will assume the tool failed rather than that the key
            # declined.
            "expectedReconstructed": (
                bool(entry.get("reconstructed")) if entry is not None else False
            ),
            "expectedReconstructedWhy": (
                entry.get("reconstructedWhy") if entry is not None else None
            ),
            "verdicts": verdicts,
        })
    return out
