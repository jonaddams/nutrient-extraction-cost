from costlab import render_html, report
from costlab.prices import PriceTable


def _rec(doc, pid, with_nutrient, inp):
    return {
        "docId": doc,
        "providerId": pid,
        "withNutrient": with_nutrient,
        "usage": {"inputTokens": inp, "outputTokens": 10, "cachedInputTokens": 0},
        "status": 200,
        "calls": 1,
        "attempts": 1,
        "latencyMs": 1000.0,
        "extracted": {"documentTitle": "Invoice"},
        "requestedFields": ["documentTitle"],
    }


def _summary():
    table = PriceTable(checked_on="2026-08-14", rates={})
    return report.summarise(
        [_rec("a", "bedrock", True, 1000), _rec("a", "bedrock", False, 600)],
        table,
        models={"bedrock": "qwen3-vl"},
        provenance={
            "corpusName": "acme-invoices",
            "documentCount": 1,
            "models": [{"providerId": "bedrock", "model": "qwen3-vl"}],
            "keySources": ["BEDROCK_API_KEY (set)"],
            "runDate": "2026-08-18T09:30:00-04:00",
            "priceTableDate": "2026-08-14",
            "toolVersion": "0.1.0",
        },
    )


def test_the_delegate_and_the_module_agree():
    """report.render_html must stay a synonym, so no caller has to change."""
    summary = _summary()
    assert report.render_html(summary) == render_html.render(summary)


def test_it_is_a_complete_document():
    """Structural facts a restructure could genuinely break.

    Not `</html>`: this renderer emits a doctype followed by a fragment, with no
    <html> or <body> element at all. Task 5 introduces the full document; until
    then, asserting a closing tag would mean bending the code inside the one
    task whose purpose is to change no behaviour.
    """
    out = render_html.render(_summary())
    assert out.startswith("<!doctype html>")
    assert "<style>" in out
    assert "<h1>" in out
    assert "<h2>Reading this honestly</h2>" in out
