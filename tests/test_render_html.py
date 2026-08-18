import re

from costlab import brand, render_html, report
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
    assert out.index("Nutrient SDK overhead") < out.index('id="appendix"')


def test_the_answer_band_says_so_when_there_is_no_delta_to_report():
    """SDK-only records: every cell lacks its direct-half partner, so
    summarise() leaves `byProvider` empty. The band must say plainly that
    there is nothing to report, not render tiles and a table with nothing in
    them."""
    table = PriceTable(checked_on="2026-08-14", rates={})
    records = [_rec("a", "bedrock", True, 1000), _rec("b", "bedrock", True, 900)]
    summary = report.summarise(records, table, models={"bedrock": "qwen3-vl"})

    assert summary["byProvider"] == []

    out = render_html.render(summary)

    assert "no delta to report" in out
    answer_section = out[out.index("<section class=answer>") : out.index("</section>")]
    assert "<table>" not in answer_section
    assert "<div class=tiles>" not in answer_section


def test_the_headline_figure_is_rounded_and_labelled_per_document():
    """Two documents with deltas of 469 and 470 average to 469.5. Floor
    division prints +469 — the wrong document's delta, silently preferred —
    and the old label had no unit, so it read as a run total rather than the
    per-document figure it actually is."""
    table = PriceTable(checked_on="2026-08-14", rates={})
    records = [
        _rec("a", "bedrock", True, 1000), _rec("a", "bedrock", False, 531),
        _rec("b", "bedrock", True, 900), _rec("b", "bedrock", False, 430),
    ]
    summary = report.summarise(records, table, models={"bedrock": "qwen3-vl"})
    prov = summary["byProvider"][0]
    assert prov["deltaInputTokens"] == 939
    assert prov["documents"] == 2

    out = render_html.render(summary)

    assert "+470 tokens per document" in out
    assert "+469 tokens per document" not in out


def test_the_provenance_block_names_the_corpus_and_the_model():
    out = render_html.render(_summary())
    assert "acme-invoices" in out
    assert "qwen3-vl" in out
    assert "BEDROCK_API_KEY (set)" in out
    assert "0.1.0" in out


def test_the_logo_is_wrapped_and_sized_by_the_stylesheet():
    """The inlined SVG carries its own width/height (711x120); nothing in the
    markup shrinks it on its own. `render()` must wrap it in `class=logo` and
    the stylesheet must size the child SVG — if either half drifts without the
    other, the wordmark ships full-bleed again."""
    out = render_html.render(_summary())
    assert "<div class=logo>" in out
    styles = brand.asset("theme.css")
    assert ".logo svg" in styles
    assert "height: 28px" in styles


def test_the_brand_layer_is_inlined():
    out = render_html.render(_summary())
    assert "--text-neutral-primary" in out
    assert 'fill="currentColor"' in out
    assert "@media print" in out


def test_the_constant_is_labelled_as_per_model():
    """The number does not transfer to a sibling model, and the page has to
    say so — without asserting a figure from some other run."""
    out = render_html.render(_summary())
    assert "per model" in out
    assert not re.search(r"\d", render_html.PER_MODEL_NOTE), (
        "the note must not cite figures from other runs — only the tables above "
        "may state measured numbers"
    )


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


# --- Task 8: the appendix, and the cleanup of the four legacy leftovers.


def test_the_appendix_holds_the_per_document_table():
    out = render_html.render(_summary())
    appendix = out[out.index('id="appendix"'):]
    assert 'id="per-document"' in appendix
    assert "sdkInputTokens" not in appendix  # keys are not rendered, values are
    assert "1,000" in appendix and "600" in appendix


def test_every_anchor_the_summary_links_to_exists():
    out = render_html.render(_summary())
    import re

    for target in set(re.findall(r'href="#([a-z-]+)"', out)):
        assert f'id="{target}"' in out, f"dangling anchor: #{target}"


def test_the_appendix_carries_every_disagreement():
    table = PriceTable(checked_on="2026-08-14", rates={})
    records = [_rec("a", "bedrock", True, 1000), _rec("a", "bedrock", False, 600)]
    summary = report.summarise(records, table, models={"bedrock": "qwen3-vl"})
    summary["agreement"] = [_dis(f"doc{i}", {"x": "1", "y": f"{i}"}) for i in range(6)]
    summary["agreementSummary"] = {
        "fields": 6, "agreed": 0, "disagreed": 6, "ambiguous": 0,
        "unanswered": 0, "rate": 0.0,
    }

    appendix = render_html.render(summary)
    appendix = appendix[appendix.index('id="disagreements"'):]

    for i in range(6):
        assert f"doc{i}" in appendix


def test_the_bulk_tables_are_collapsible():
    out = render_html.render(_summary())
    assert "<details" in out
    assert "<summary>" in out


def test_there_is_exactly_one_h1_and_one_style_block():
    """Task 5 introduced the real <h1>; the legacy one, and the legacy inline
    <style> block that predates the brand theme, must not survive alongside
    it."""
    out = render_html.render(_summary())
    assert out.count("<h1>") == 1
    assert out.count("<style>") == 1


def test_the_legacy_reading_this_honestly_section_is_not_duplicated():
    """`_honesty_band` renders the caveats once; the old bottom-of-page section
    that repeated them verbatim is gone."""
    out = render_html.render(_summary())
    assert out.count("<h2>Reading this honestly</h2>") == 1


def test_the_footer_says_the_file_carries_document_content():
    """On a prospect's own run the disagreement values ARE their document text,
    which makes this file sensitive. Say so rather than redacting: a report with
    its disagreements blacked out cannot make its own argument."""
    out = render_html.render(_summary())
    assert "values extracted from the documents" in out


def test_the_footer_carries_the_tool_version_and_price_date():
    out = render_html.render(_summary())
    footer = out[out.index("<footer"):]
    assert "0.1.0" in footer
    assert "2026-08-14" in footer


def test_the_footer_uses_the_brand_casing():
    """Sentence case for Nutrient, lowercase for the domain."""
    footer = render_html.render(_summary())
    footer = footer[footer.index("<footer"):]
    assert "nutrient.io" in footer
    assert "NUTRIENT" not in footer
