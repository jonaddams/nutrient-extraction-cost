"""`costlab` with no arguments: a few questions, then an explicit yes.

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
price table, corpus loader, and the counter that says how much of a corpus an
answer key can score. That is what lets the whole flow be tested without a
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

# What a run can measure. "both" is not a third kind of run: it is a cost run
# and an accuracy run, joined. It is offered because the report that is worth
# reading carries both bands, and it is asked rather than assumed because it
# doubles the calls — the one decision in this flow that changes the bill.
_MODES = {
    "cost": "token cost, one shared schema across every document",
    "accuracy": "scored against an answer key, each document's own fields",
    "both": "two runs, joined into one report — costs the sum of the two",
}


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
    scoreable: Callable[[Path, str | None], int] | None = None,
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
            scoreable=scoreable,
        )
    except (KeyboardInterrupt, EOFError):
        # Ctrl-C at "proceed?" must never read as consent.
        emit()
        emit("Cancelled. Nothing was called.")
        return None


def _converse(
    *, ask, emit, table, load_corpus, detected, default_corpus, scoreable
):
    detected_ids = [p.id for p in detected]

    emit("Providers detected:")
    for p in detected:
        how = "no credential needed" if not p.credential_env else f"{p.credential_env} is set"
        emit(f"  {p.id:12} {p.label:28} {how}")
    emit()

    chosen = _ask_providers(ask, emit, detected_ids)
    corpus_path, documents = _ask_corpus(ask, emit, load_corpus, default_corpus)
    mode, answers, scored = _ask_mode(
        ask, emit, corpus_path, documents, scoreable
    )

    per_document = _cells_for(chosen)
    # Priced per run, because the two runs do not cover the same documents: an
    # accuracy run asks only about documents the key can score, and quoting the
    # whole corpus for it would overstate what is about to be authorised.
    runs = {
        "cost": [("cost run", documents)],
        "accuracy": [("accuracy run", scored)],
        "both": [("cost run", documents), ("accuracy run", scored)],
    }[mode]
    calls = sum(n * per_document for _, n in runs)

    emit()
    if mode == "both":
        emit(
            "This is two runs, one after the other, joined into one report — "
            "so it costs the sum of both."
        )
    for label, n in runs:
        line = f"{n} document(s) x {per_document} call(s) each = {n * per_document} call(s)"
        emit(f"  {label:14} {line}" if mode == "both" else line)
    if mode == "both":
        emit(f"  {'total':14} {calls} call(s)")
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
        "mode": mode,
        "answers": answers,
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


def _ask_mode(ask, emit, corpus_path, documents, scoreable):
    """What to measure, and — if it will be scored — against which key.

    Returns (mode, answers_path_or_None, scoreable_document_count).

    The loop exists for one reason beyond typos: an accuracy run is only as
    large as the documents the key has entries for, and a corpus the key cannot
    score at all is not a cheaper run, it is no run. A typed `--mode accuracy`
    finds that out by exiting 2 partway through, which for the wizard would mean
    quoting a call count and taking a yes for a run that cannot happen. Asking
    again is the honest place to find out.
    """
    prompt = (
        "Measure cost, accuracy, or both? blank for cost "
        f"[{', '.join(_MODES)}]: "
    )
    emit()
    for name, what in _MODES.items():
        emit(f"  {name:10} {what}")
    while True:
        reply = ask(prompt).strip().lower() or "cost"
        if reply not in _MODES:
            emit(f"Not a choice: {reply}. Choose from {', '.join(_MODES)}.")
            continue
        if reply == "cost":
            # Nothing is scored, so there is no key to ask about and no count
            # to take. Returning the corpus size keeps the caller from having
            # to special-case a None it would never read.
            return reply, None, documents

        answers = _ask_answers(ask)
        scored = _count_scoreable(scoreable, corpus_path, answers)
        if scored == 0:
            where = answers or "the bundled answer key"
            emit(
                f"None of the {documents} document(s) in {corpus_path} have an "
                f"entry in {where}, so there is nothing an accuracy run could "
                "score. Supply a key that covers them, or measure cost."
            )
            continue
        if scored < documents:
            # Stated before the yes, because it is the difference between the
            # run someone thinks they are authorising and the one they are.
            emit(
                f"{scored} of {documents} document(s) have answer-key entries; "
                "the rest are skipped, since asking a model about fields the "
                "key does not hold would score it against nothing."
            )
        return reply, answers, scored


def _ask_answers(ask):
    """Which key to score against. Blank means the bundled one.

    Blank returns None rather than the bundled path: `--mode accuracy` already
    loads that key by default, and naming its location here would put a second
    copy of that path in a second module.
    """
    reply = ask(
        "Answer key to score against? blank for the bundled one, or a path to "
        "JSON or CSV: "
    ).strip()
    return reply or None


def _count_scoreable(scoreable, corpus_path, answers):
    """How many documents the key can actually score.

    Injected like every other read this module does. A caller that offers
    accuracy without supplying it is a programming error, not a runtime
    condition, so it says so rather than guessing the whole corpus is covered —
    which would be the overstatement this question exists to prevent.
    """
    if scoreable is None:
        raise TypeError(
            "wizard.run needs `scoreable` to price an accuracy run: it is what "
            "counts the documents the answer key covers."
        )
    return scoreable(Path(corpus_path), answers)
