import json

from costlab.providers import PROVIDERS
from costlab.runner import Cell, load_corpus, plan_cells, summarise_attempts


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
            [
                {
                    "id": "invoice",
                    "file": "inv.pdf",
                    "schema": {
                        "type": "object",
                        "properties": {"total": {"type": "number"}},
                        "required": ["total"],
                        "additionalProperties": False,
                    },
                }
            ]
        )
    )
    docs = load_corpus(tmp_path)
    assert [d.id for d in docs] == ["invoice"]
    assert "total" in docs[0].schema["properties"]
