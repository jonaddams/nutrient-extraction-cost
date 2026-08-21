"""`costlab` with no arguments: four questions, then an explicit yes.

Whoever runs this tool supplies their own API keys, so they are technical and do
not need hand-holding. What they do need is the cost of the next keypress made
visible before it is spent, because every call this schedules is billed to them.
So the wizard states the exact call count, names every provider it is about to
bill and whether that provider can be priced at all, and then requires the word
yes.

What it deliberately does NOT do is quote a total. Spend depends on how long the
documents are, and nothing knows that until they have been read and tokenised by
each provider's own tokenizer. A confident "estimated total: $12.40" would be the
same unsupported figure this project has spent twelve defects removing from the
report — and it would be trusted precisely because it appeared right before the
money was spent. The honest version states what is known (the call count, the
list rates and the date they were checked) and names what is not.

Pure stdlib, and everything it touches is injected: input, output, environment,
price table, corpus loader. That is what lets the whole flow be tested without a
network.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from .providers import PROVIDERS, available

# Three states, not two. "No price" has two entirely different causes and only
# one of them is a warning: a hosted provider absent from our table is billing
# real money we cannot quote, while a self-hosted runtime has no per-token price
# because no vendor is billing at all. Collapsing them tells someone watching
# their spend to worry about the one line that cannot add to it. Neither is
# "$0.00", which would assert the calls are free.
_NO_PRICE = "no list price in the bundled table — spend cannot be quoted"
_SELF_HOSTED = "runs on your own hardware — no per-token charge"


def _cells_for(provider_ids: list[str]) -> int:
    """Calls per document: both halves where the grounded one is supported."""
    return sum(
        2 if PROVIDERS[pid].supports_nutrient_cell else 1 for pid in provider_ids
    )


def _rate_line(pid: str, table: Any) -> str:
    """One provider's per-token input rate, or which reason there isn't one."""
    provider = PROVIDERS[pid]
    # Priced off a nominal million input tokens: `cost` returns None when the
    # table has no entry, which is the distinction being drawn.
    million = table.cost(pid, provider.default_model, 1_000_000, 0)
    if million is not None:
        return f"${million:,.2f} per million input tokens"
    # Needing no credential is what makes a provider self-hosted — the same
    # signal the report's rungs are derived from, rather than a second list.
    return _NO_PRICE if provider.credential_env else _SELF_HOSTED


def run(
    *,
    ask: Callable[[str], str],
    emit: Callable[..., None],
    env: dict[str, str],
    table: Any,
    load_corpus: Callable[[Path], list[Any]],
    providers: list[Any] | None = None,
    default_corpus: str = "costlab/corpus",
) -> dict[str, Any] | None:
    """Ask, price, confirm. Returns the chosen settings, or None if cancelled.

    None always means "do not run" — a cancelled confirmation, no providers, or
    Ctrl-C. The caller must treat it as a full stop rather than a default.
    """
    detected = available(env) if providers is None else providers
    if not detected:
        emit(
            "No providers are configured: no credential is set and no local "
            "runtime is selectable."
        )
        emit(
            "Set one of "
            + ", ".join(
                p.credential_env for p in PROVIDERS.values() if p.credential_env
            )
            + ", or point LOCAL_BASE at a local runtime."
        )
        return None

    try:
        return _converse(
            ask=ask,
            emit=emit,
            table=table,
            load_corpus=load_corpus,
            detected=detected,
            default_corpus=default_corpus,
        )
    except (KeyboardInterrupt, EOFError):
        # Ctrl-C at "proceed?" must never read as consent.
        emit()
        emit("Cancelled. Nothing was called.")
        return None


def _converse(*, ask, emit, table, load_corpus, detected, default_corpus):
    detected_ids = [p.id for p in detected]

    emit("Providers detected:")
    for p in detected:
        how = "no credential needed" if not p.credential_env else f"{p.credential_env} is set"
        emit(f"  {p.id:12} {p.label:28} {how}")
    emit()

    chosen = _ask_providers(ask, emit, detected_ids)
    corpus_path, documents = _ask_corpus(ask, emit, load_corpus, default_corpus)

    per_document = _cells_for(chosen)
    calls = documents * per_document

    emit()
    emit(f"{documents} document(s) x {per_document} call(s) each = {calls} call(s)")
    emit("Each provider below will be billed for its share of those calls:")
    for pid in chosen:
        emit(f"  {PROVIDERS[pid].label:28} {_rate_line(pid, table)}")
    emit()
    emit(f"List prices checked {table.checked_on}.")
    # The sentence that keeps this honest. Stated every time, because the run it
    # precedes is the one that costs money.
    emit(
        "What this actually costs depends on how long your documents are, which "
        "is not known until each provider has read and tokenised them, so no "
        "total is quoted here."
    )
    emit()

    reply = ask("Proceed and spend against these providers? [y/N] ")
    if reply.strip().lower() not in ("y", "yes"):
        emit("Nothing was called.")
        return None

    return {
        "providers": chosen,
        "corpus": corpus_path,
        "documents": documents,
        "calls": calls,
        "confirmed": True,
    }


def _ask_providers(ask, emit, detected_ids: list[str]) -> list[str]:
    """Which of the detected providers to bill. Blank means all of them.

    A typo is re-asked rather than dropped: silently ignoring an unrecognised id
    would run a different, cheaper set than the reader asked for and then report
    it as though it were what they asked for.
    """
    prompt = (
        "Which providers? comma-separated, or blank for all "
        f"[{', '.join(detected_ids)}]: "
    )
    while True:
        reply = ask(prompt).strip()
        if not reply:
            return list(detected_ids)
        wanted = [w.strip() for w in reply.split(",") if w.strip()]
        unknown = [w for w in wanted if w not in detected_ids]
        if unknown:
            emit(
                f"Not detected: {', '.join(unknown)}. "
                f"Choose from {', '.join(detected_ids)}."
            )
            continue
        # Deduplicated, and ordered as detected rather than as typed, so the
        # count shown next matches the run.
        return [pid for pid in detected_ids if pid in wanted]


def _ask_corpus(ask, emit, load_corpus, default_corpus) -> tuple[str, int]:
    """Where the documents are, and how many there are. Blank means bundled."""
    prompt = f"Documents folder? blank for the bundled corpus [{default_corpus}]: "
    while True:
        reply = ask(prompt).strip() or default_corpus
        try:
            documents = len(load_corpus(Path(reply)))
        except (OSError, ValueError) as err:
            emit(f"Could not read {reply}: {err}")
            continue
        if not documents:
            emit(f"No documents found in {reply}.")
            continue
        return reply, documents
