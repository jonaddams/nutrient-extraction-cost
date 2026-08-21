"""Combines saved runs into the records and provenance for one report.

Why this exists: the report's accuracy band compares models from frontier down
to self-hosted, and those measurements do not come from one run. The frontier
models need three hosted credentials; a self-hosted model needs a runtime on the
LAN and one model loaded at a time. Asking for all of it in a single invocation
is not something a reader could reproduce.

What it refuses is the point. `providerId` is not a model — it is a route. Every
LM Studio model in this project ran as `local`, so merging two local runs
without checking would sum two different sets of weights into one row and label
it with whichever provenance happened to win. That row would be wrong in the
most expensive way available: plausible, specific, and unfalsifiable from the
page. So a provider appearing in more than one run must be provably the same
model, and "provably" excludes "probably" — a run that did not record its models
cannot vouch for itself.
"""

from __future__ import annotations

from typing import Any

# Appended by `summarise` when provenance carries more than one source run. The
# figures are each honest about their own run; what a reader must not assume is
# that they were gathered under one set of conditions at one moment.
JOINED_RUNS_CAVEAT = (
    "This report combines measurements from more than one separate run, listed "
    "under Run above. Each figure is exact for the run it came from, but the "
    "runs happened at different times and may have used different credentials "
    "or a different machine, so treat a comparison ACROSS models as close to "
    "like-for-like rather than exactly so."
)


def _models_of(run: dict[str, Any]) -> dict[str, str] | None:
    """Provider to model for one run, or None when the run did not record it."""
    provenance = run.get("provenance") or {}
    if "models" not in provenance:
        return None
    return {m["providerId"]: m["model"] for m in provenance["models"]}


def _providers_of(run: dict[str, Any]) -> set[str]:
    return {r["providerId"] for r in run["records"]}


def merge_runs(runs: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Records and provenance for a report built from several runs.

    Each run is `{"name": str, "records": [...], "provenance": {...}}`.

    Raises ValueError when one provider id carries different models across runs,
    or when a run sharing a provider id did not record which model it used.
    """
    if not runs:
        raise ValueError("no runs to merge")

    # Every claim collected BEFORE any is judged. An earlier version walked the
    # runs in order and only looked backwards, so a run with no recorded models
    # escaped the check whenever it happened to be listed first — the same two
    # runs were refused or silently merged depending on the order typed on the
    # command line. A safety check an argument order can switch off is not one.
    claims: dict[str, list[tuple[str, str | None]]] = {}
    for run in runs:
        models = _models_of(run)
        for provider_id in sorted(_providers_of(run)):
            model = None if models is None else models.get(provider_id)
            claims.setdefault(provider_id, []).append((run["name"], model))

    for provider_id, entries in sorted(claims.items()):
        if len(entries) < 2:
            continue
        unrecorded = [name for name, model in entries if model is None]
        if unrecorded:
            known = {model for _, model in entries if model is not None}
            raise ValueError(
                f"{provider_id!r} appears in {len(entries)} of these runs, but "
                f"{', '.join(repr(n) for n in unrecorded)} did not record which "
                f"model it used"
                + (f" (the others used {', '.join(sorted(map(repr, known)))})"
                   if known else "")
                + ". A provider id is a route, not a model — refusing to assume "
                "these are the same weights."
            )
        distinct = {model for _, model in entries}
        if len(distinct) > 1:
            detail = ", ".join(
                f"{model!r} in run {name!r}" for name, model in entries
            )
            raise ValueError(
                f"{provider_id!r} ran different models across these runs: "
                f"{detail}. Merging would present two models as one row. Report "
                f"them separately, or give them distinct provider ids."
            )

    records = [record for run in runs for record in run["records"]]

    def _joined(field: str) -> str:
        """One value if every run agrees, else all of them.

        Silently picking the first would state something false about the rest.
        """
        values = []
        for run in runs:
            value = (run.get("provenance") or {}).get(field)
            if value and value not in values:
                values.append(value)
        return " · ".join(values)

    models: list[dict[str, str]] = []
    key_sources: list[str] = []
    for run in runs:
        provenance = run.get("provenance") or {}
        for entry in provenance.get("models", []):
            if entry not in models:
                models.append(entry)
        for source in provenance.get("keySources", []):
            if source not in key_sources:
                key_sources.append(source)

    provenance = {
        "corpusName": _joined("corpusName"),
        # Counted from the merged records rather than summed from the runs: two
        # runs over the same seventeen documents cover seventeen, not
        # thirty-four, and adding them would inflate the headline scope.
        "documentCount": len({r["docId"] for r in records}),
        "models": sorted(models, key=lambda m: m["providerId"]),
        "keySources": key_sources or ["not recorded"],
        "runDate": _joined("runDate"),
        "priceTableDate": _joined("priceTableDate"),
        "toolVersion": _joined("toolVersion"),
        "sourceRuns": [
            {
                "name": run["name"],
                "runDate": (run.get("provenance") or {}).get("runDate", ""),
                "providers": sorted(_providers_of(run)),
            }
            for run in runs
        ],
    }
    return records, provenance
