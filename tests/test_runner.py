import json

from costlab.providers import PROVIDERS
from costlab.runner import (
    Cell,
    _document_text,
    extracted_values,
    load_corpus,
    plan_cells,
    summarise_attempts,
)


def test_plan_cells_builds_both_halves_of_the_matrix():
    cells = plan_cells([PROVIDERS["anthropic"], PROVIDERS["bedrock"]])
    assert Cell("anthropic", True) in cells
    assert Cell("anthropic", False) in cells
    assert Cell("bedrock", True) in cells
    assert Cell("bedrock", False) in cells
    assert len(cells) == 4


def test_plan_cells_skips_unsupported_nutrient_cells_but_keeps_direct():
    # A provider whose endpoint override does not work cannot have its
    # with-Nutrient cell measured — but its direct cell is still valid, and
    # dropping both would silently shrink the comparison.
    import dataclasses

    broken = dataclasses.replace(PROVIDERS["openai"], supports_nutrient_cell=False)
    cells = plan_cells([broken])
    assert cells == [Cell("openai", False)]


# --- Beyond the plan. The retry rule is the one thing here that can silently
# --- corrupt a total, so it is a pure function with its own tests.


def test_summarise_attempts_counts_a_retry_storm_as_one_call():
    """Measured 2026-08-14: a single extract_structured() against a failing
    upstream produced FOUR proxy records. Summing every record would report 4x
    the tokens for one document, and nothing in the output would look wrong.
    """
    records = [
        {"status": 502, "usage": None, "latencyMs": 10.0},
        {"status": 502, "usage": None, "latencyMs": 10.0},
        {"status": 502, "usage": None, "latencyMs": 10.0},
        {
            "status": 200,
            "usage": {"inputTokens": 100, "outputTokens": 10, "cachedInputTokens": 0},
            "latencyMs": 20.0,
        },
    ]
    out = summarise_attempts(records)
    assert out["usage"] == {
        "inputTokens": 100,
        "outputTokens": 10,
        "cachedInputTokens": 0,
    }
    assert out["attempts"] == 4
    assert out["calls"] == 1
    assert out["status"] == 200


def test_summarise_attempts_reports_none_rather_than_zero_when_nothing_succeeded():
    """An unmeasurable cell is a finding, not a data point. A zero here would
    read as "this cost nothing", which is a claim the run cannot support."""
    records = [
        {"status": 502, "usage": None, "latencyMs": 5.0},
        {"status": 502, "usage": None, "latencyMs": 5.0},
    ]
    out = summarise_attempts(records)
    assert out["usage"] is None
    assert out["attempts"] == 2
    assert out["calls"] == 0
    assert out["status"] == 502


def test_summarise_attempts_handles_a_cell_that_never_reached_the_proxy():
    out = summarise_attempts([])
    assert out["usage"] is None
    assert out["attempts"] == 0
    assert out["status"] is None


def test_document_text_ignores_the_system_prompt_even_when_it_is_the_longest_part():
    """The exact shape of a captured request for a handwritten image, from a live
    run: the SDK's system prompt is 1,712 characters and the extracted document
    content is 853. Scanning every message for the largest text part picks the
    system prompt, so the direct call receives the SDK's own instructions in
    place of the document — and still returns a usage block, so the delta comes
    out quietly wrong rather than obviously broken.
    """
    body = {
        "messages": [
            {"role": "system", "content": "S" * 1712},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Document content:\n"},
                    {"type": "text", "text": "D" * 853},
                ],
            },
        ]
    }
    assert _document_text(body) == "D" * 853


def test_document_text_still_finds_content_longer_than_the_system_prompt():
    body = {
        "messages": [
            {"role": "system", "content": "S" * 1712},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Document content:\n"},
                    {"type": "text", "text": "D" * 2623},
                ],
            },
        ]
    }
    assert _document_text(body) == "D" * 2623


def test_document_text_is_empty_when_no_user_text_was_sent():
    """An empty result is the signal the runner turns into a recorded note
    rather than a comparison against nothing."""
    assert _document_text({"messages": [{"role": "system", "content": "S" * 99}]}) == ""
    assert _document_text({}) == ""


def test_load_corpus_without_a_manifest_uses_every_pdf_and_a_shared_schema(tmp_path):
    """Task 7 bundles a manifest. Until then — and for a prospect pointing this
    at their own folder — a bare directory of documents must just work."""
    (tmp_path / "a.pdf").write_bytes(b"%PDF-1.4 fake")
    (tmp_path / "b.pdf").write_bytes(b"%PDF-1.4 fake")
    (tmp_path / "notes.txt").write_text("ignored")

    docs = load_corpus(tmp_path)
    assert {d.id for d in docs} == {"a", "b"}
    # One shared schema, so a payload difference is attributable to the document
    # and not to a varying field count.
    assert len({json.dumps(d.schema, sort_keys=True) for d in docs}) == 1
    assert "documentTitle" in docs[0].schema["properties"]


def test_load_corpus_reads_a_manifest_when_present(tmp_path):
    (tmp_path / "inv.pdf").write_bytes(b"%PDF-1.4 fake")
    (tmp_path / "manifest.json").write_text(
        json.dumps(
            {
                "documents": {
                    "invoice": {
                        "file": "inv.pdf",
                        "category": "invoices",
                        "schema": {
                            "type": "object",
                            "properties": {"total": {"type": "number"}},
                            "required": ["total"],
                            "additionalProperties": False,
                        },
                    }
                }
            }
        )
    )
    docs = load_corpus(tmp_path)
    assert [d.id for d in docs] == ["invoice"]
    assert "total" in docs[0].schema["properties"]


def test_a_manifest_entry_without_a_schema_gets_the_shared_one(tmp_path):
    """The bundled corpus deliberately omits per-document schemas so payload
    differences are attributable to the document, not to a field count."""
    (tmp_path / "inv.pdf").write_bytes(b"%PDF-1.4 fake")
    (tmp_path / "manifest.json").write_text(
        json.dumps(
            {"documents": {"invoice": {"file": "inv.pdf", "category": "invoices"}}}
        )
    )
    docs = load_corpus(tmp_path)
    assert "documentTitle" in docs[0].schema["properties"]


def test_the_bundled_corpus_manifest_resolves_every_file():
    """Task 7's own check, as a test rather than a one-off command: a manifest
    entry pointing at a missing file fails as a confusing SDK error deep in a
    run that has already spent money."""
    from pathlib import Path

    corpus = Path(__file__).resolve().parent.parent / "costlab" / "corpus"
    docs = load_corpus(corpus)
    missing = [d.id for d in docs if not d.path.exists()]
    assert len(docs) == 17, f"expected 17 documents, found {len(docs)}"
    assert not missing, f"missing files: {missing}"
    # Both size ranges must stay bundled — that is what makes the constant
    # visible as a constant rather than as a percentage.
    import json as _json

    entries = _json.loads((corpus / "manifest.json").read_text())["documents"]
    pages = sorted(e["pages"] for e in entries.values())
    assert pages[0] == 1 and pages[-1] >= 40


def test_extracted_values_reads_the_sdk_envelope():
    """The SDK wraps values under "extraction" alongside its own metadata. Only
    the values are the answer."""
    raw = json.dumps(
        {
            "extraction": {"invoiceNumber": "AC-2025-1047", "totalAmount": 345015},
            "metadata": {"invoiceNumber": {"match": "id_match", "confidence": 0.98}},
        }
    )
    assert extracted_values(raw, with_nutrient=True) == {
        "invoiceNumber": "AC-2025-1047",
        "totalAmount": 345015,
    }


def test_extracted_values_reads_a_direct_chat_completion():
    body = {
        "choices": [
            {"message": {"content": '{"invoiceNumber": "AC-2025-1047"}'}}
        ]
    }
    assert extracted_values(body, with_nutrient=False) == {
        "invoiceNumber": "AC-2025-1047"
    }


def test_extracted_values_reads_an_anthropic_messages_reply():
    """Anthropic returns content blocks, not choices. Plan 1 established that
    this provider speaks a different dialect end to end; it does not stop at the
    request."""
    body = {"content": [{"type": "text", "text": '{"invoiceNumber": "AC-2025-1047"}'}]}
    assert extracted_values(body, with_nutrient=False) == {
        "invoiceNumber": "AC-2025-1047"
    }


def test_unparseable_content_is_none_not_an_empty_dict():
    """An empty dict scores every field as a mismatch and reports the provider
    as catastrophically wrong, when the truth is that we could not read its
    answer. Those are different findings and must not be conflated."""
    body = {"choices": [{"message": {"content": "I could not find the fields."}}]}
    assert extracted_values(body, with_nutrient=False) is None
    assert extracted_values("not json at all", with_nutrient=True) is None
    assert extracted_values(None, with_nutrient=False) is None


def test_a_json_array_reply_is_none_rather_than_a_field_map():
    """A local 8B model was measured returning the bare array ["b2"] instead of
    the requested object. It parses as JSON and is still not an answer."""
    body = {"choices": [{"message": {"content": '["b2"]'}}]}
    assert extracted_values(body, with_nutrient=False) is None


def test_a_fenced_json_block_still_parses():
    """Models wrap JSON in markdown fences despite instructions not to."""
    body = {
        "choices": [
            {"message": {"content": '```json\n{"invoiceNumber": "AC-1"}\n```'}}
        ]
    }
    assert extracted_values(body, with_nutrient=False) == {"invoiceNumber": "AC-1"}
