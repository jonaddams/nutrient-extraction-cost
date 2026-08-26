import re

from costlab import agreement, brand, render_html, report
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
    assert out.index('id="cost"') < out.index('id="appendix"')


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
    cost_band = out[out.index('id="cost"') : out.index("</section>")]
    assert "<table>" not in cost_band
    assert "<div class=cards>" not in cost_band


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

    assert "+470" in out
    assert "input tokens per document" in out
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
    """Distinct is the comparator's own count, computed here rather than
    omitted -- `render_html._distinct` now indexes it strictly rather than
    recomputing it from raw values (see agreement.py's `normalise_values`)."""
    distinct = len(set(agreement.normalise_values(values).values()))
    return {
        "docId": doc, "field": "documentTitle", "state": "disagreed",
        "values": values, "distinct": distinct,
    }


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


def test_every_disagreement_is_listed_not_just_a_sample():
    """Supersedes the old omitted-count test, and asserts something stronger.

    The previous layout showed three disagreements and stated how many it was
    hiding; the redesign ranks every one of them by spread, so there is nothing
    left to hide. If a future change reintroduces truncation, this fails —
    which is the point, because a selection rule that quietly dropped the least
    flattering row is exactly the dishonesty this project keeps finding.
    """
    table = PriceTable(checked_on="2026-08-14", rates={})
    records = [_rec("a", "bedrock", True, 1000), _rec("a", "bedrock", False, 600)]
    summary = report.summarise(records, table, models={"bedrock": "qwen3-vl"})
    summary["agreement"] = [
        _dis(f"doc{i}", {"a:direct": "1", "a:sdk": f"{i}"}) for i in range(6)
    ]
    summary["agreementSummary"] = {
        "fields": 6, "agreed": 0, "disagreed": 6, "ambiguous": 0,
        "unanswered": 0, "rate": 0.0,
    }

    out = render_html.render(summary)
    ranked = out[out.index("by spread"):]

    for i in range(6):
        assert f"doc{i}" in ranked, f"doc{i} is missing from the ranked list"
    assert "All six, by spread" in out  # spelled, like every small count in prose


def test_the_framing_sentence_travels_with_the_disagreements():
    table = PriceTable(checked_on="2026-08-14", rates={})
    records = [_rec("a", "bedrock", True, 1000), _rec("a", "bedrock", False, 600)]
    summary = report.summarise(records, table, models={"bedrock": "qwen3-vl"})
    summary["agreement"] = [_dis("a", {"a:direct": "1", "a:sdk": "2"})]
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
        "agreement": [_dis("a", {"a:direct": "1", "a:sdk": "2"})],
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
    assert 'id="appendix-a"' in appendix
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
    summary["agreement"] = [
        _dis(f"doc{i}", {"a:direct": "1", "a:sdk": f"{i}"}) for i in range(6)
    ]
    summary["agreementSummary"] = {
        "fields": 6, "agreed": 0, "disagreed": 6, "ambiguous": 0,
        "unanswered": 0, "rate": 0.0,
    }

    appendix = render_html.render(summary)
    appendix = appendix[appendix.index('id="appendix-c"'):]

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


# --- Appendix C: expected value, per-configuration verdict, one row per model ---
#
# The old appendix printed `provider:half='value'` reprs in a single cell. A
# reader looking at eight strings could not tell which was right -- the exact
# sentence that appendix used to justify the grounded half. It now shows the
# answer key's value as the reference, one row per model with direct and SDK
# side by side, and a mark per half.


def _keyed_summary(extracted_by_config, key_documents, field="totalAmount"):
    """A summary whose agreement rows are annotated against a real key."""
    from costlab.answers import AnswerKey

    table = PriceTable(checked_on="2026-08-14", rates={})
    records = []
    for (pid, sdk), value in extracted_by_config.items():
        records.append({
            "docId": "inv",
            "providerId": pid,
            "withNutrient": sdk,
            "usage": {"inputTokens": 100, "outputTokens": 10, "cachedInputTokens": 0},
            "status": 200,
            "calls": 1,
            "attempts": 1,
            "latencyMs": 1000.0,
            "extracted": {field: value},
            "requestedFields": [field],
            "schemaSource": "answer-key",
        })
    return report.summarise(
        records,
        table,
        models={pid: "m" for pid, _ in extracted_by_config},
        key=AnswerKey(checked_on="2026-08-26", documents=key_documents),
    )


def test_the_expected_value_is_shown_as_the_reference_to_read_against():
    summary = _keyed_summary(
        {("anthropic", False): "383350", ("anthropic", True): "345015"},
        {"inv": {"totalAmount": {"value": "345015", "source": "Amount Due $345,015.00"}}},
    )
    html = render_html.render(summary)
    assert "345015" in html
    assert "expected" in html.lower()


def test_a_correct_half_and_a_wrong_half_are_marked_differently():
    """The whole point of the column: telling them apart without reading both
    strings and knowing the document."""
    summary = _keyed_summary(
        {("anthropic", False): "383350", ("anthropic", True): "345015"},
        {"inv": {"totalAmount": {"value": "345015", "source": "Amount Due"}}},
    )
    html = render_html.render(summary)
    assert "mark-match" in html, "the correct half carries a match mark"
    assert "mark-mismatch" in html, "the wrong half carries a mismatch mark"


def test_a_mark_is_never_a_bare_glyph():
    """A tick alone is unreadable to a screen reader and ambiguous in print.
    Every mark carries a word."""
    summary = _keyed_summary(
        {("anthropic", False): "383350", ("anthropic", True): "345015"},
        {"inv": {"totalAmount": {"value": "345015", "source": "Amount Due"}}},
    )
    html = render_html.render(summary)
    for word in ("matches the key", "does not match"):
        assert word in html, word


def test_a_field_the_key_does_not_cover_is_neutral_never_a_cross():
    """Marking an unscored field wrong would invent a correctness claim. The
    agreement band is usable with no key at all."""
    summary = _keyed_summary(
        {("anthropic", False): "Recipe", ("anthropic", True): "From Lola"},
        {"inv": {"someOtherField": {"value": "x", "source": "y"}}},
    )
    # Scoped to the appendix markup: the inlined stylesheet defines
    # `.mark-mismatch` as a selector, so a whole-document search would match the
    # CSS rather than any actual mark.
    html = render_html.render(summary)
    section = html[html.index('id="appendix-c"'):]
    assert "mark-mismatch" not in section, "nothing here was compared to anything"
    assert "mark-unscored" in section
    assert "not in the answer key" in section


def test_an_ambiguous_comparison_gets_its_own_mark():
    """Neither right nor wrong: the comparator declined. Folding this into the
    cross would mark a provider wrong for our own uncertainty.

    The row has to genuinely DISAGREE to appear here at all — a field that is
    only ambiguous lands in state "ambiguous", which this appendix excludes on
    purpose rather than print as a disagreement nobody established. So one half
    returns the key's date with the components swapped (ambiguous against a
    slash date, which the comparator will not guess at) and the other returns a
    different month entirely (a plain mismatch)."""
    summary = _keyed_summary(
        {("anthropic", False): "1/4/2026", ("anthropic", True): "December 2020"},
        {"inv": {"totalAmount": {"value": "4/1/2026", "source": "Date"}}},
    )
    html = render_html.render(summary)
    assert "mark-unverified" in html
    assert "not compared confidently" in html
    assert "mark-mismatch" in html, "and the other half is a plain miss"


def test_models_run_frontier_to_self_hosted():
    """The same ordering the accuracy band uses, so a reader does not have to
    learn two."""
    summary = _keyed_summary(
        {("local", False): "a", ("local", True): "a",
         ("anthropic", False): "b", ("anthropic", True): "b"},
        {"inv": {"totalAmount": {"value": "b", "source": "y"}}},
    )
    html = render_html.render(summary)
    section = html[html.index("appendix-c"):]
    assert section.index("anthropic") < section.index("local")


def test_the_two_halves_of_a_model_sit_on_one_row():
    """Direct against SDK is the question the report exists to answer, so it
    belongs on one line rather than two rows to be matched up by eye."""
    summary = _keyed_summary(
        {("anthropic", False): "383350", ("anthropic", True): "345015"},
        {"inv": {"totalAmount": {"value": "345015", "source": "Amount Due"}}},
    )
    html = render_html.render(summary)
    section = html[html.index("appendix-c"):]
    row = re.search(r"<tr[^>]*>(?:(?!</tr>).)*383350(?:(?!</tr>).)*</tr>", section, re.S)
    assert row, "the wrong value should be inside a table row"
    assert "345015" in row.group(0), "and its own model's other half on the same row"
    # Both marks on the one row is what proves the halves are paired rather
    # than merely co-located in a single dumped cell.
    assert "mark-match" in row.group(0) and "mark-mismatch" in row.group(0)


def test_a_half_that_answered_nothing_is_absent_not_wrong():
    summary = _keyed_summary(
        {("anthropic", False): "345015", ("anthropic", True): None},
        {"inv": {"totalAmount": {"value": "345015", "source": "Amount Due"}}},
    )
    html = render_html.render(summary)
    assert "no answer" in html


def test_a_marks_words_are_an_attribute_not_visible_text():
    """The glyph says it. The words exist only so the mark is not glyph-only for
    a screen reader — they must never render beside the value, which is what a
    stray print rule outside its @media block did on first attempt.
    """
    summary = _keyed_summary(
        {("anthropic", False): "383350", ("anthropic", True): "345015"},
        {"inv": {"totalAmount": {"value": "345015", "source": "Amount Due"}}},
    )
    html = render_html.render(summary)
    section = html[html.index('id="appendix-c"'):]
    assert 'aria-label="matches the key"' in section
    assert ">matches the key<" not in section, "must not be visible text"
    assert ">does not match the key<" not in section


def test_the_mark_is_its_own_column_beside_each_value():
    """Five columns: model, mark, direct, mark, SDK. The marks line up down the
    page so the table can be scanned without reading a single value."""
    summary = _keyed_summary(
        {("anthropic", False): "383350", ("anthropic", True): "345015"},
        {"inv": {"totalAmount": {"value": "345015", "source": "Amount Due"}}},
    )
    html = render_html.render(summary)
    section = html[html.index('id="appendix-c"'):]
    row = re.search(r"<tr>(?:(?!</tr>).)*383350(?:(?!</tr>).)*</tr>", section, re.S)
    assert row, "expected a data row containing the wrong value"
    assert row.group(0).count("<td") == 5, "model + mark + value + mark + value"


def test_the_print_stylesheet_does_not_leak_onto_the_screen():
    """Every rule in print.css must sit inside its @media print block. One that
    does not applies always — which is how the screen-reader-only mark labels
    became visible next to every value."""
    from costlab import brand

    css = brand.asset("print.css")
    depth = 0
    for i, ch in enumerate(css):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            assert depth >= 0, "unbalanced braces in print.css"
    assert depth == 0, "unbalanced braces in print.css"
    # Everything after the media block closes is unscoped.
    start = css.index("@media print")
    d, end = 0, None
    for i in range(start, len(css)):
        if css[i] == "{":
            d += 1
        elif css[i] == "}":
            d -= 1
            if d == 0:
                end = i
                break
    assert end is not None
    trailing = css[end + 1:]
    # Comments are fine; a rule is not.
    stripped = re.sub(r"/\*.*?\*/", "", trailing, flags=re.S).strip()
    assert not stripped, f"unscoped rules after @media print: {stripped[:200]!r}"
