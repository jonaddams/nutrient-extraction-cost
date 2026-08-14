"""Walks corpus x cell, drives both halves of the comparison, writes records.

The matrix has four cells: frontier and open-weight, each with and without the
Nutrient SDK. Every call — both halves — goes through the recording proxy, so
both sides produce one record format and neither is measured more generously
than the other.

Two rules the rest of this file exists to protect:

  1. An unmeasurable cell records `usage: None` and the run continues. It never
     invents a zero. A provider that reports no usage is a finding.
  2. A retry storm is one call. The SDK retries a failing request four times,
     and summing proxy records would report 4x the tokens for one document with
     nothing in the output looking wrong.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import prices, report
from .providers import PROVIDERS, Provider, available, direct_request
from .proxy import RecordingProxy

# One shared schema, so a payload difference between documents is attributable
# to the document rather than to a varying field count. Field count is its own
# experiment, and a steep one: truncation rises sharply with it.
DEFAULT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "documentTitle": {
            "type": "string",
            "description": "The document's title as printed",
        }
    },
    "required": ["documentTitle"],
    "additionalProperties": False,
}

_DOC_SUFFIXES = {".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".docx"}


@dataclass(frozen=True)
class Cell:
    provider_id: str
    with_nutrient: bool


@dataclass(frozen=True)
class Doc:
    id: str
    path: Path
    schema: dict[str, Any]


def plan_cells(providers: list[Provider]) -> list[Cell]:
    """The matrix, minus any with-Nutrient cell a spike marked unsupported.

    A provider whose endpoint override does not work loses its with-Nutrient
    cell only. Its direct cell is still a valid measurement, and dropping both
    would quietly shrink the comparison instead of reporting a gap in it.
    """
    cells: list[Cell] = []
    for p in providers:
        if p.supports_nutrient_cell:
            cells.append(Cell(p.id, True))
        cells.append(Cell(p.id, False))
    return cells


def load_corpus(corpus_dir: Path) -> list[Doc]:
    """Documents to run, from a manifest if there is one or the directory if not.

    A bare directory has to work: a prospect's first run points this at their
    own folder, and requiring them to author a manifest before seeing any number
    is a reason not to bother.
    """
    corpus_dir = Path(corpus_dir)
    manifest = corpus_dir / "manifest.json"
    if manifest.exists():
        # {"documents": {docId: {"file": ..., "category": ..., "schema": ...}}}
        # Keyed by id rather than a list so it joins directly against an answer
        # key of the same shape, which is what the accuracy layer will need.
        entries = json.loads(manifest.read_text())["documents"]
        return [
            Doc(
                id=doc_id,
                path=corpus_dir / entry["file"],
                schema=entry.get("schema", DEFAULT_SCHEMA),
            )
            for doc_id, entry in entries.items()
        ]
    return [
        Doc(id=p.stem, path=p, schema=DEFAULT_SCHEMA)
        for p in sorted(corpus_dir.iterdir())
        if p.suffix.lower() in _DOC_SUFFIXES
    ]


def summarise_attempts(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Fold every proxy record for one cell into one honest measurement.

    `attempts` is how many requests reached the proxy; `calls` is how many
    actually reported usage. They differ whenever the SDK retried, and a report
    that shows only the token total cannot distinguish a 4x overcount from a
    genuinely expensive document — so both travel with the numbers.

    Tokens are summed across successful calls rather than taken from the last
    one, because a call path that legitimately makes several requests per
    document would otherwise be undercounted. On the paths measured so far a
    successful extraction is exactly one request.
    """
    successful = [r for r in records if r.get("usage")]
    usage: dict[str, int] | None = None
    if successful:
        usage = {
            "inputTokens": sum(r["usage"]["inputTokens"] for r in successful),
            "outputTokens": sum(r["usage"]["outputTokens"] for r in successful),
            "cachedInputTokens": sum(
                r["usage"]["cachedInputTokens"] for r in successful
            ),
        }
    return {
        "usage": usage,
        "attempts": len(records),
        "calls": len(successful),
        "status": records[-1]["status"] if records else None,
        "latencyMs": round(sum(r.get("latencyMs", 0.0) for r in records), 1),
    }


def _document_text(body: dict[str, Any]) -> str:
    """The extracted document content out of a captured request.

    This is how the no-Nutrient half gets its document text: from whatever the
    SDK actually sent, not from a second extraction of our own. Holding the
    extracted content constant is what makes the delta attributable to the
    SDK's scaffolding rather than to two different text extractions.

    Only USER messages are considered, and that restriction is the whole point.
    A captured request carries the SDK's system prompt (~1,700 characters of
    instructions) plus a user message holding a short "Document content:" label
    and one part with the extracted content. Picking the largest text part
    across *all* messages silently picks the system prompt whenever a document
    extracts to less text than that — which is exactly what happens on
    handwritten images with no text layer.

    That failure is quiet and plausible-looking: the direct call receives the
    SDK's own instructions in place of the document, still returns a usage
    block, and the delta comes out slightly wrong rather than obviously broken.
    Two handwritten samples reported +517 and +658 against a +468 constant
    before this was restricted to user messages.
    """
    best = ""
    for message in body.get("messages") or []:
        if message.get("role") != "user":
            continue
        content = message.get("content")
        if isinstance(content, str):
            if len(content) > len(best):
                best = content
            continue
        for part in content or []:
            if isinstance(part, dict) and part.get("type") == "text":
                text = part.get("text") or ""
                if len(text) > len(best):
                    best = text
    return best


def extracted_values(payload: Any, *, with_nutrient: bool) -> dict[str, Any] | None:
    """The field values one cell produced, or None if none could be read.

    None and {} are different findings and must never be conflated. An empty
    dict scores every field as a mismatch, which reports the provider as
    catastrophically wrong; None records that the harness could not read the
    answer, which is a statement about the harness.

    The two halves genuinely differ in shape. The SDK returns an envelope with
    the values under "extraction" beside its own grounding metadata. A direct
    call returns a JSON string inside a chat completion (choices) or an
    Anthropic content block, and that string is model output: it may be fenced,
    prefaced with prose, or not be an object at all.
    """
    if payload is None:
        return None

    if isinstance(payload, str):
        parsed = _loads_or_none(payload)
    else:
        parsed = payload

    if parsed is None:
        return None

    if with_nutrient:
        if not isinstance(parsed, dict):
            return None
        values = parsed.get("extraction", parsed)
        return values if isinstance(values, dict) and values else None

    if not isinstance(parsed, dict):
        return None

    content: Any = None
    choices = parsed.get("choices")
    if isinstance(choices, list) and choices:
        content = ((choices[0] or {}).get("message") or {}).get("content")
    elif isinstance(parsed.get("content"), list):
        # Anthropic's /v1/messages dialect: content blocks, not choices.
        for block in parsed["content"]:
            if isinstance(block, dict) and block.get("type") == "text":
                content = block.get("text")
                break

    if not isinstance(content, str):
        return None
    values = _loads_or_none(content)
    return values if isinstance(values, dict) and values else None


def _loads_or_none(text: str) -> Any:
    """Parse JSON, tolerating a markdown fence around it.

    Models wrap JSON in ```json fences despite being told not to. Tolerating
    that is not the same as tolerating prose: anything that still will not parse
    returns None and is recorded as unreadable.
    """
    candidate = text.strip()
    if candidate.startswith("```"):
        candidate = re.sub(r"^```[a-zA-Z]*\s*", "", candidate)
        candidate = re.sub(r"\s*```$", "", candidate)
    try:
        return json.loads(candidate)
    except (ValueError, TypeError):
        return None


def _run_sdk_cell(
    provider: Provider, doc: Doc, proxy: RecordingProxy, port: int
) -> tuple[str, dict[str, Any] | None]:
    """Drive one extraction through the SDK, pointed at the proxy.

    Returns the document text the SDK sent (for the direct half to reuse) and
    the values it extracted (for scoring).
    """
    from nutrient_sdk import Document, StructuredExtractionRequest, Vision

    with Document.open(str(doc.path)) as document:
        ai = document.settings.ai_processing_settings
        ai.provider = provider.sdk_provider
        ai.model = provider.default_model
        if provider.credential_env:
            ai.api_key = os.environ.get(provider.credential_env, "")
        # The port is chosen by the OS at runtime, never fixed. If usage comes
        # back None on this path, this line is the first thing to check.
        ai.endpoint = f"http://127.0.0.1:{port}/v1"
        ai.include_confidence = True
        ai.include_source_locations = True
        ai.include_page_images = False
        ai.strict_structured_output = False
        request = StructuredExtractionRequest()
        # The SDK takes the schema wrapped; direct_request takes it bare.
        request.schema = json.dumps({"schema": doc.schema})
        request.instructions = ""
        raw = Vision.set(document).extract_structured(request)

    return (
        _document_text(proxy.last_request_body or {}),
        extracted_values(raw, with_nutrient=True),
    )


def _run_direct_cell(
    provider: Provider, doc: Doc, port: int, document_text: str, proxy: RecordingProxy
) -> dict[str, Any] | None:
    """POST the minimal no-Nutrient request through the same proxy."""
    body = direct_request(
        provider, provider.default_model, document_text, doc.schema
    )
    headers = {"Content-Type": "application/json"}
    if provider.credential_env:
        headers[provider.auth_header] = provider.auth_prefix + os.environ.get(
            provider.credential_env, ""
        )
    headers.update(dict(provider.extra_headers))
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{provider.chat_path}",
        data=json.dumps(body).encode(),
        headers=headers,
        method="POST",
    )
    try:
        urllib.request.urlopen(req, timeout=600).read()
    except urllib.error.HTTPError:
        # The proxy already recorded the status. A failed direct call is a
        # measurement outcome, not a reason to abandon the remaining documents.
        pass
    return extracted_values(proxy.last_response_body, with_nutrient=False)


def run(
    corpus: list[Doc],
    cells: list[Cell],
    out_dir: Path,
    capture_bodies: bool = True,
) -> list[dict[str, Any]]:
    """One record per document per cell.

    One proxy per provider, because each provider has a different upstream. The
    SDK cell for a document runs before its direct cell: the direct call reuses
    the text the SDK sent, so the order is a data dependency, not a preference.
    """
    out_dir = Path(out_dir)
    results: list[dict[str, Any]] = []

    by_provider: dict[str, list[Cell]] = {}
    for cell in cells:
        by_provider.setdefault(cell.provider_id, []).append(cell)

    for provider_id, provider_cells in by_provider.items():
        provider = PROVIDERS[provider_id]
        proxy = RecordingProxy(
            upstream_base=provider.upstream_base,
            out_dir=out_dir / provider_id,
            capture_bodies=capture_bodies,
        )
        port = proxy.start()
        try:
            for doc in corpus:
                document_text = ""
                # Sorted so with_nutrient=True comes first: the direct half
                # depends on what the SDK half captured.
                for cell in sorted(
                    provider_cells, key=lambda c: not c.with_nutrient
                ):
                    label = (
                        f"{doc.id}:{provider_id}:"
                        f"{'sdk' if cell.with_nutrient else 'direct'}"
                    )
                    proxy.label(label)
                    before = len(proxy.records)
                    note = None
                    extracted: dict[str, Any] | None = None
                    started = time.perf_counter()
                    try:
                        if cell.with_nutrient:
                            document_text, extracted = _run_sdk_cell(
                                provider, doc, proxy, port
                            )
                        elif document_text:
                            extracted = _run_direct_cell(
                                provider, doc, port, document_text, proxy
                            )
                        else:
                            # No SDK capture for this document, so there is no
                            # controlled document text to send. Extracting our
                            # own would compare two different extractions and
                            # call the difference SDK overhead.
                            note = "no captured document text"
                    except Exception as exc:  # noqa: BLE001
                        note = f"{type(exc).__name__}: {exc}"

                    summary = summarise_attempts(proxy.records[before:])
                    results.append(
                        {
                            "docId": doc.id,
                            "providerId": provider_id,
                            "withNutrient": cell.with_nutrient,
                            "wallMs": round(
                                (time.perf_counter() - started) * 1000, 1
                            ),
                            "extracted": extracted,
                            **summary,
                            **({"note": note} if note else {}),
                        }
                    )
                    state = (
                        "no usage" if summary["usage"] is None else "ok"
                    )
                    print(f"  {label}: {state}", flush=True)
        finally:
            proxy.stop()

    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="costlab",
        description=(
            "Measure what document extraction costs, with and without the "
            "Nutrient SDK, on your own documents."
        ),
    )
    parser.add_argument(
        "--corpus", default="costlab/corpus", help="directory of documents to run"
    )
    parser.add_argument("--out", default="out", help="where to write records")
    parser.add_argument(
        "--no-capture-bodies",
        action="store_true",
        help="do not write request or response bodies to disk",
    )
    parser.add_argument(
        "--providers",
        default="",
        help="comma-separated provider ids; default is every configured one",
    )
    parser.add_argument(
        "--yes", action="store_true", help="skip the confirmation prompt"
    )
    parser.add_argument(
        "--prices",
        default=None,
        help="price table to use instead of the bundled one, e.g. your negotiated rates",
    )
    args = parser.parse_args(argv)

    chosen = available()
    if args.providers:
        wanted = {p.strip() for p in args.providers.split(",") if p.strip()}
        unknown = wanted - set(PROVIDERS)
        if unknown:
            print(f"unknown provider(s): {', '.join(sorted(unknown))}", file=sys.stderr)
            return 2
        missing = wanted - {p.id for p in chosen}
        if missing:
            for pid in sorted(missing):
                env = PROVIDERS[pid].credential_env
                print(f"{pid}: {env} is not set", file=sys.stderr)
            return 2
        chosen = [p for p in chosen if p.id in wanted]

    if not chosen:
        print(
            "No providers configured. Set at least one credential, or run a "
            "local runtime.",
            file=sys.stderr,
        )
        return 2

    corpus = load_corpus(Path(args.corpus))
    if not corpus:
        print(f"No documents found in {args.corpus}", file=sys.stderr)
        return 2

    cells = plan_cells(chosen)
    print(f"{len(corpus)} document(s) x {len(cells)} cell(s) = "
          f"{len(corpus) * len(cells)} calls")
    for cell in cells:
        half = "with Nutrient" if cell.with_nutrient else "direct"
        print(f"  {PROVIDERS[cell.provider_id].label:32} {half}")
    skipped = [p.id for p in chosen if not p.supports_nutrient_cell]
    if skipped:
        print(f"with-Nutrient cell unsupported, direct only: {', '.join(skipped)}")

    if not args.yes:
        # A prospect pointing this at 500 documents should see the scale before
        # a single call is billed.
        reply = input("Proceed and spend against these providers? [y/N] ")
        if reply.strip().lower() not in ("y", "yes"):
            print("Nothing was called.")
            return 1

    license_key = os.environ.get("NUTRIENT_LICENSE_KEY", "").strip()
    if any(c.with_nutrient for c in cells):
        if not license_key:
            print(
                "NUTRIENT_LICENSE_KEY is not set, which the with-Nutrient half "
                "requires.",
                file=sys.stderr,
            )
            return 2
        from nutrient_sdk import License

        License.register_key(license_key)

    out_dir = Path(args.out)
    records = run(
        corpus, cells, out_dir, capture_bodies=not args.no_capture_bodies
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    records_path = out_dir / "records.json"
    records_path.write_text(json.dumps(records, indent=2))

    unmeasured = [r for r in records if r["usage"] is None]
    print(f"\n{len(records)} record(s) -> {records_path}")
    if unmeasured:
        print(f"{len(unmeasured)} cell(s) reported no usage and were not priced:")
        for r in unmeasured:
            half = "with Nutrient" if r["withNutrient"] else "direct"
            reason = r.get("note") or f"status {r['status']}"
            print(f"  {r['docId']} / {r['providerId']} / {half}: {reason}")

    table = prices.load(args.prices)
    summary = report.summarise(
        records, table, models={p.id: p.default_model for p in chosen}
    )
    (out_dir / "report.json").write_text(report.render_json(summary))
    (out_dir / "report.html").write_text(report.render_html(summary))
    print()
    print(report.render_terminal(summary))
    print(f"\nreport -> {out_dir / 'report.html'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
