"""What produced this report — assembled from the run, never from a template.

The first version of the HTML report never said whose documents it measured:
a reader saw "$367.80 per 100k documents" with nothing to say the figure came
from our sample corpus rather than theirs. That is the whole argument of the
tool inverted, so provenance is built from the records and the run's own
configuration, and any field we do not actually know says so.

Note: documentCount is documents **attempted**, not documents measured. A run
can report 17 documents here while the per-model table shows 14, because records
include cells that produced no usage.
"""

from __future__ import annotations

from pathlib import PurePath
from typing import Any

UNKNOWN = "not recorded"

# The packaged corpus, however it was addressed on the command line. A run on
# our documents must never read as a run on the reader's.
_BUNDLED_LABEL = "Nutrient sample corpus"


def tool_version() -> str:
    try:
        from importlib.metadata import version

        return version("nutrient-extraction-cost")
    except Exception:  # noqa: BLE001 - version reporting must never break a run
        return UNKNOWN


def _corpus_name(corpus_dir: str | None, is_bundled: bool) -> str:
    """The corpus's NAME — never its path, which is the reader's business.

    Whether this is the packaged sample corpus is a fact the caller resolves by
    comparing paths, not something to infer from a directory name: a prospect
    with their own .../costlab/corpus would otherwise have their real run
    labelled as our demo.
    """
    if is_bundled:
        return _BUNDLED_LABEL
    if not corpus_dir:
        return UNKNOWN
    return PurePath(corpus_dir).name or UNKNOWN


def build(
    *,
    corpus_dir: str | None,
    records: list[dict[str, Any]],
    models: dict[str, str],
    credential_envs: list[str],
    run_started: str,
    checked_on: str | None,
    is_bundled: bool = False,
) -> dict[str, Any]:
    providers_in_run = sorted({r["providerId"] for r in records})
    return {
        "corpusName": _corpus_name(corpus_dir, is_bundled),
        "documentCount": len({r["docId"] for r in records}),
        "models": [
            {"providerId": pid, "model": models.get(pid, UNKNOWN)}
            for pid in providers_in_run
        ],
        "keySources": [f"{name} (set)" for name in credential_envs] or [UNKNOWN],
        "runDate": run_started or UNKNOWN,
        "priceTableDate": checked_on or UNKNOWN,
        "toolVersion": tool_version(),
    }
