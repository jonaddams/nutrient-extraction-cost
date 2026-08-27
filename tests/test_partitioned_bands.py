"""Cost and accuracy in one report, computed from different records.

A cost-mode run asks every document for one shared schema, so a payload
difference is attributable to the document. An accuracy run asks each document
for its own answer-key fields, which makes it scoreable and makes its token
counts incomparable with the cost run's. Both are needed in the report a
prospect opens.

The resolution is that each band is computed from the records it is entitled to:
the cost band from shared-schema records alone, the accuracy band from
answer-key records alone. Nothing is blended, and the page says which documents
each band covers rather than silently narrowing.
"""

from costlab import render_html
from costlab.answers import AnswerKey
from costlab.prices import PriceTable
from costlab.report import render_terminal, summarise


def _rec(doc, pid, with_nutrient, inp, schema, extracted=None):
    return {
        "docId": doc,
        "providerId": pid,
        "withNutrient": with_nutrient,
        "usage": {"inputTokens": inp, "outputTokens": 10, "cachedInputTokens": 0},
        "status": 200,
        "latencyMs": 1000.0,
        "calls": 1,
        "attempts": 1,
        "schemaSource": schema,
        "schemaFieldCount": 1,
        "extracted": extracted if extracted is not None else {"total": 100},
    }


def _table():
    return PriceTable(checked_on="2026-08-14", rates={})


def _key():
    return AnswerKey(
        checked_on="2026-08-14",
        documents={
            "cost-doc": {"total": {"value": 100, "source": "Total 100"}},
            "acc-doc": {"total": {"value": 100, "source": "Total 100"}},
        },
    )


def _mixed():
    """One document measured in cost mode, another in accuracy mode."""
    return [
        _rec("cost-doc", "bedrock", True, 1000, "shared"),
        _rec("cost-doc", "bedrock", False, 600, "shared"),
        _rec("acc-doc", "bedrock", True, 1200, "answer-key"),
        _rec("acc-doc", "bedrock", False, 700, "answer-key"),
    ]


def test_the_cost_band_uses_only_the_shared_schema_records():
    """Blending a +400 shared-schema delta with a +500 key-derived one produces
    a per-model constant that describes neither run."""
    out = summarise(_mixed(), _table(), key=_key())
    row = out["byProvider"][0]
    assert row["documents"] == 1
    assert row["deltaInputTokens"] == 400
    assert {r["docId"] for r in out["byDocument"]} == {"cost-doc"}


def test_the_accuracy_band_uses_only_the_answer_key_records():
    """A cost-mode record was never asked the key's fields, so scoring it would
    manufacture a mismatch for a question nobody put to the model."""
    out = summarise(_mixed(), _table(), key=_key())
    assert out["accuracyByModel"]
    half = out["accuracyByModel"][0]["sdk"]
    assert half["verified"] == 1, "one scored document, not two"


def test_the_page_says_which_documents_each_band_covers():
    """Silently narrowing the cost band to a subset reads as "covered
    everything" when it did not. The counts have to be on the page."""
    out = summarise(_mixed(), _table(), key=_key())
    html = render_html.render(out)
    assert out["partitioned"] is True
    assert out["costDocumentCount"] == 1
    assert out["accuracyDocumentCount"] == 1
    assert "computed from different" in html


def test_a_single_source_run_is_partitioned_by_nothing():
    """The ordinary case must be untouched: one schema source means every record
    feeds every band, exactly as before."""
    recs = [
        _rec("a", "bedrock", True, 1000, "answer-key"),
        _rec("a", "bedrock", False, 600, "answer-key"),
        _rec("b", "bedrock", True, 1200, "answer-key"),
        _rec("b", "bedrock", False, 700, "answer-key"),
    ]
    out = summarise(recs, _table(), key=_key())
    assert out["partitioned"] is False
    assert out["byProvider"][0]["documents"] == 2


def test_the_old_advice_to_run_them_separately_is_gone():
    """"Run cost and accuracy separately" was correct while the bands shared one
    set of records. Now that each band takes only what it is entitled to, the
    advice is obsolete and telling a reader to undo the feature is worse than
    saying nothing."""
    text = render_terminal(summarise(_mixed(), _table(), key=_key())).lower()
    assert "run cost and accuracy separately" not in text
    assert "different" in text
