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


def test_the_answer_band_leads_with_the_per_model_constant():
    out = render_html.render(_summary())
    assert out.index("Nutrient SDK overhead") < out.index("<h2>Per document")


def test_the_provenance_block_names_the_corpus_and_the_model():
    out = render_html.render(_summary())
    assert "acme-invoices" in out
    assert "qwen3-vl" in out
    assert "BEDROCK_API_KEY (set)" in out
    assert "0.1.0" in out


def test_the_brand_layer_is_inlined():
    out = render_html.render(_summary())
    assert "--text-neutral-primary" in out
    assert 'fill="currentColor"' in out
    assert "@media print" in out


def test_the_constant_is_labelled_as_per_model():
    """468 on Qwen3-VL, 479 on Qwen3.5-9b, 1,226 on Sonnet. The number does not
    transfer to a sibling model, and the page has to say so."""
    out = render_html.render(_summary())
    assert "per model" in out


def test_the_document_is_now_whole():
    """A file we email to a prospect should be a complete document."""
    out = render_html.render(_summary())
    assert out.startswith("<!doctype html>")
    assert "<html lang=en>" in out
    assert out.rstrip().endswith("</html>")


def _dis(doc, values):
    return {"docId": doc, "field": "documentTitle", "state": "disagreed", "values": values}


def test_representative_picks_the_widest_divergence_first():
    rows = [
        _dis("small", {"a": "Invoice", "b": "Invoice."}),
        _dis("wide", {"a": "Invoice", "b": "Invoice No 12 " * 20}),
        _dis("mid", {"a": "Invoice", "b": "Invoice of CenturyLink Communications"}),
    ]
    chosen, omitted = render_html.representative_disagreements(rows, limit=2)
    assert [r["docId"] for r in chosen] == ["wide", "mid"]
    assert omitted == 1


def test_representative_is_deterministic_on_ties():
    rows = [_dis("b", {"x": "1", "y": "2"}), _dis("a", {"x": "1", "y": "2"})]
    chosen, _ = render_html.representative_disagreements(rows, limit=1)
    assert chosen[0]["docId"] == "a"


def test_agreed_rows_are_never_offered_as_disagreements():
    rows = [
        {"docId": "a", "field": "f", "state": "agreed", "values": {"x": "1", "y": "1"}},
        _dis("b", {"x": "1", "y": "2"}),
    ]
    chosen, omitted = render_html.representative_disagreements(rows, limit=3)
    assert [r["docId"] for r in chosen] == ["b"]
    assert omitted == 0


def test_the_summary_says_how_many_disagreements_it_is_not_showing():
    """A selection rule that quietly hid the least flattering disagreement would
    be exactly the dishonesty this project keeps finding."""
    table = PriceTable(checked_on="2026-08-14", rates={})
    records = [_rec("a", "bedrock", True, 1000), _rec("a", "bedrock", False, 600)]
    summary = report.summarise(records, table, models={"bedrock": "qwen3-vl"})
    summary["agreement"] = [_dis(f"doc{i}", {"x": "1", "y": f"{i}"}) for i in range(6)]
    summary["agreementSummary"] = {
        "fields": 6, "agreed": 0, "disagreed": 6, "ambiguous": 0,
        "unanswered": 0, "rate": 0.0,
    }

    out = render_html.render(summary)

    assert "3 more" in out


def test_the_framing_sentence_travels_with_the_disagreements():
    table = PriceTable(checked_on="2026-08-14", rates={})
    records = [_rec("a", "bedrock", True, 1000), _rec("a", "bedrock", False, 600)]
    summary = report.summarise(records, table, models={"bedrock": "qwen3-vl"})
    summary["agreement"] = [_dis("a", {"x": "1", "y": "2"})]
    summary["agreementSummary"] = {
        "fields": 1, "agreed": 0, "disagreed": 1, "ambiguous": 0,
        "unanswered": 0, "rate": 0.0,
    }

    out = render_html.render(summary)

    assert "citation" in out
    assert "not correctness" in out


def test_the_rate_falls_back_for_a_hand_built_summary():
    """A summary assembled by an external consumer may lack `rate`.

    Real summarise() output always carries it, so this branch is defensive only
    — but it is reachable by anyone building a summary dict themselves, and an
    untested fallback is a fallback nobody knows is broken.

    Exercised against `_accuracy_band` directly, not the full `render()` page:
    the legacy `agreement_section` further down the same page indexes
    `a["rate"]` unconditionally (restored, deliberately, to its pre-Task-6
    behaviour), so a summary that omits `rate` to reach this fallback would
    make the *rest* of the page crash. The fallback is real and reachable by a
    hand-built summary passed to `_accuracy_band`; it is not something a full
    `summarise()`-derived page can ever exhibit.
    """
    summary = {
        "agreementSummary": {"fields": 1, "agreed": 1, "disagreed": 1, "ambiguous": 0},
        "agreement": [_dis("a", {"x": "1", "y": "2"})],
    }

    out = render_html._accuracy_band(summary, lambda s: s)

    assert "50%" in out


def test_representative_is_stable_across_input_orders():
    """Determinism by construction, not by luck: same rows, either order, same pick."""
    a = _dis("doc", {"x": "1", "y": "2"})
    a["field"] = "alpha"
    b = _dis("doc", {"x": "1", "y": "2"})
    b["field"] = "beta"

    forward, _ = render_html.representative_disagreements([a, b], limit=1)
    reverse, _ = render_html.representative_disagreements([b, a], limit=1)

    assert forward[0]["field"] == reverse[0]["field"] == "alpha"


def test_every_caveat_is_outside_a_details_element():
    """A caveat a reader has to click for is a caveat we did not really make.

    Compares the ESCAPED text, which is what the document contains. Asserting
    the raw string would also pass if escaping were removed altogether, so the
    escaped form is the stronger assertion as well as the correct one.

    No <details> exists until Task 8, so this passes trivially today and becomes
    load-bearing when the appendix lands. Do not weaken it in the meantime.
    """
    import html

    summary = _summary()
    out = render_html.render(summary)
    head = out.split("<details")[0]
    for caveat in summary["caveats"]:
        assert html.escape(caveat) in head, f"caveat is behind a disclosure: {caveat[:40]}"


def test_unmeasurable_and_retried_notices_are_in_the_summary():
    table = PriceTable(checked_on="2026-08-14", rates={})
    sdk = _rec("a", "local", True, 10866)
    sdk["calls"] = sdk["attempts"] = 3
    direct = _rec("a", "local", False, 6766)
    direct["calls"] = direct["attempts"] = 2
    summary = report.summarise([sdk, direct], table, models={"local": "qwen3-vl"})

    head = render_html.render(summary).split("<details")[0]

    assert "not measurable" in head
    assert "retried" in head
