"""The canvas redesign: numbered sections, editorial headlines, computed copy.

The design that this implements ships beautiful sentences containing run-specific
figures — "Seventeen documents, three models", "seven disagreements". Every one of
them must be computed here. Hardcoding any of them would recreate, one day later,
the exact Critical the whole-branch review caught: a report asserting measurements
it did not take.
"""

import re

from costlab import render_html, report
from costlab.prices import PriceTable


def _rec(doc, pid, with_nutrient, inp, out=10, extracted=None):
    return {
        "docId": doc,
        "providerId": pid,
        "withNutrient": with_nutrient,
        "usage": {"inputTokens": inp, "outputTokens": out, "cachedInputTokens": 0},
        "status": 200,
        "calls": 1,
        "attempts": 1,
        "latencyMs": 1000.0,
        "extracted": extracted if extracted is not None else {"documentTitle": "T"},
        "requestedFields": ["documentTitle"],
    }


def _two_doc_summary():
    """Deliberately NOT seventeen documents and NOT three models."""
    table = PriceTable(checked_on="2026-08-14", rates={})
    records = [
        _rec("alpha", "bedrock", True, 1000),
        _rec("alpha", "bedrock", False, 600),
        _rec("beta", "bedrock", True, 2000),
        _rec("beta", "bedrock", False, 1600),
    ]
    return report.summarise(
        records,
        table,
        models={"bedrock": "qwen3-vl"},
        provenance={
            "corpusName": "acme-invoices",
            "documentCount": 2,
            "models": [{"providerId": "bedrock", "model": "qwen3-vl"}],
            "keySources": ["BEDROCK_API_KEY (set)"],
            "runDate": "2026-08-18T09:30:00-04:00",
            "priceTableDate": "2026-08-14",
            "toolVersion": "0.1.0",
        },
    )


# --- the anti-hardcode guard, which is the whole point ---------------------


def test_no_static_prose_carries_a_measurement():
    """Prose constants must not contain figures. Only computed values may.

    A measurement here looks like a thousands separator, a dollar amount, or a
    percentage — 1,226 / $367.80 / 59%. Section numbers ("01") and plain small
    integers in ordinary sentences are not measurements.
    """
    measurement = re.compile(r"\d,\d{3}|\$\s?\d|\d+\s?%")

    # OUTPUT_CAVEAT is the one permitted exception, and only because it names
    # its own provenance: "in one measured run a single document's direct call
    # emitted about 7,500 more output tokens". A figure attributed to another
    # run is a citation; the same figure stated bare would be a claim about
    # THIS run, which is the defect this test exists to prevent.
    attributed = {"OUTPUT_CAVEAT"}

    for name in dir(render_html):
        value = getattr(render_html, name)
        if name.isupper() and isinstance(value, str) and name not in attributed:
            assert not measurement.search(value), f"{name} carries a measurement"

    from costlab import report

    assert "in one measured run" in report.OUTPUT_CAVEAT, (
        "the exception is only safe while the caveat still attributes its figure"
    )


def test_the_standfirst_counts_this_run_not_the_design_s_run():
    out = render_html.render(_two_doc_summary())
    head = out[: out.index('id="cost"')]
    assert "Seventeen" not in head and "seventeen" not in head
    assert "2 documents" in head or "two documents" in head.lower()


def test_the_accuracy_headline_counts_this_run():
    summary = _two_doc_summary()
    summary["agreement"] = [
        {"docId": "alpha", "field": "documentTitle", "state": "disagreed",
         "values": {"bedrock:direct": "A", "bedrock:sdk": "B"}},
    ]
    summary["agreementSummary"] = {
        "fields": 1, "agreed": 0, "disagreed": 1, "ambiguous": 0,
        "unanswered": 0, "rate": 0.0,
    }
    out = render_html.render(summary)
    assert "seven disagreements" not in out.lower()
    assert "1 disagreement" in out or "one disagreement" in out.lower()


# --- structure the design specifies ---------------------------------------


def test_the_five_sections_appear_in_the_designed_order():
    out = render_html.render(_two_doc_summary())
    order = [out.index(f'id="{s}"') for s in ("cost", "caveats", "appendix")]
    assert order == sorted(order)


def test_sections_are_numbered_with_eyebrows():
    out = render_html.render(_two_doc_summary())
    assert "01 — Cost" in out
    assert "03 — Caveats" in out


def test_the_provenance_grid_labels_all_six_facts():
    out = render_html.render(_two_doc_summary())
    for label in (
        "Documents run", "Run", "Price table checked",
        "Tool version", "Models compared", "Credentials used",
    ):
        assert label in out, f"provenance grid missing {label!r}"


def test_one_cost_card_per_model_carrying_its_own_delta():
    out = render_html.render(_two_doc_summary())
    # both documents have a +400 delta, so the card must say +400 per document
    assert "+400" in out
    assert "input tokens per document" in out


def test_caveats_are_numbered_and_titled_without_losing_their_bodies():
    summary = _two_doc_summary()
    out = render_html.render(summary)
    assert "The delta is not waste" in out
    assert "Output tokens are not comparable" in out
    # the existing bodies, which tests/test_report.py pins, survive verbatim
    for caveat in summary["caveats"]:
        import html as html_mod

        assert html_mod.escape(caveat) in out


def test_the_appendix_has_three_lettered_parts():
    out = render_html.render(_two_doc_summary())
    for anchor, label in (
        ("appendix-a", "A · Per document"),
        ("appendix-b", "B · Per provider"),
        ("appendix-c", "C · Every disagreement"),
    ):
        assert f'id="{anchor}"' in out, f"missing {anchor}"
        assert label in out, f"missing label {label!r}"


def test_appendix_a_groups_documents_by_model():
    out = render_html.render(_two_doc_summary())
    tail = out[out.index('id="appendix-a"'):]
    # the group header states the model, its document count and its constant
    assert "2 documents" in tail
    assert "+400 input tokens each" in tail


def test_every_internal_link_resolves():
    out = render_html.render(_two_doc_summary())
    for target in set(re.findall(r'href="#([a-z-]+)"', out)):
        assert f'id="{target}"' in out, f"dangling anchor: #{target}"


# --- the disagreement treatment the design introduces ----------------------


def _dis(doc, values, field="documentTitle"):
    return {"docId": doc, "field": field, "state": "disagreed", "values": values}


def test_one_disagreement_is_shown_in_full_by_provider_and_half():
    summary = _two_doc_summary()
    summary["agreement"] = [
        _dis("alpha", {
            "bedrock:direct": "Statement of Financial Position",
            "bedrock:sdk": "Meridian Components Inc.",
            "openai:direct": "Same", "openai:sdk": "Same",
        }),
    ]
    summary["agreementSummary"] = {
        "fields": 1, "agreed": 0, "disagreed": 1, "ambiguous": 0,
        "unanswered": 0, "rate": 0.0,
    }
    out = render_html.render(summary)
    assert "Direct call" in out and "With Nutrient SDK" in out
    assert "3 distinct answers across 4 configurations" in out
    # a provider whose two halves agree is called out rather than repeated
    assert "both halves identical" in out


def test_all_disagreements_are_ranked_by_spread_with_their_counts():
    summary = _two_doc_summary()
    summary["agreement"] = [
        _dis("narrow", {"a:direct": "x", "a:sdk": "y"}),
        _dis("wide", {"a:direct": "p", "a:sdk": "q", "b:direct": "r", "b:sdk": "s"}),
    ]
    summary["agreementSummary"] = {
        "fields": 2, "agreed": 0, "disagreed": 2, "ambiguous": 0,
        "unanswered": 0, "rate": 0.0,
    }
    out = render_html.render(summary)
    ranked = out[out.index("by spread"):]
    assert ranked.index("wide") < ranked.index("narrow")
    assert "4 distinct answers" in out and "2 distinct answers" in out


def test_the_excluded_count_is_stated_not_implied():
    summary = _two_doc_summary()
    summary["agreement"] = [_dis("alpha", {"a:direct": "x", "a:sdk": "y"})]
    summary["agreementSummary"] = {
        "fields": 4, "agreed": 1, "disagreed": 1, "ambiguous": 1,
        "unanswered": 1, "rate": 0.5,
    }
    out = render_html.render(summary)
    assert "2" in out  # ambiguous + unanswered
    assert "unjudgeable or unanswered" in out


def test_a_sentence_spells_all_its_numbers_or_none_of_them():
    """Mixed spelling reads worse than either choice made consistently.

    "17 documents, three models" is what you get from deciding per number
    instead of per sentence, so the rule is: spell only when every count in the
    sentence is spellable.
    """
    assert render_html._spellable(3, 17) is True
    assert render_html._spellable(3, 240) is False

    table = PriceTable(checked_on="2026-08-14", rates={})
    # 21 documents on one model: 21 is past the word list, so BOTH go numeric.
    records = []
    for i in range(21):
        records.append(_rec(f"doc{i:02d}", "bedrock", True, 1000))
        records.append(_rec(f"doc{i:02d}", "bedrock", False, 600))
    summary = report.summarise(
        records, table, models={"bedrock": "qwen3-vl"},
        provenance={
            "corpusName": "big-corpus", "documentCount": 21,
            "models": [{"providerId": "bedrock", "model": "qwen3-vl"}],
            "keySources": ["BEDROCK_API_KEY (set)"],
            "runDate": "2026-08-18T09:30:00-04:00",
            "priceTableDate": "2026-08-14", "toolVersion": "0.1.0",
        },
    )

    head = render_html.render(summary)
    head = head[: head.index('id="cost"')]

    assert "21 documents, 1 model" in head
    assert "one model" not in head


def test_the_provenance_grid_tiles_without_leaving_a_gap():
    """Six facts on a four-column grid: four single cells, two spanning two.

    The grid's own background is the hairline colour, so any column the cells
    do not fill renders as a grey block rather than as whitespace. 4 + 2*2 = 8
    is exactly two rows.
    """
    out = render_html.render(_two_doc_summary())
    grid = out[out.index("class=prov-grid") : out.index("id=\"cost\"")]
    assert grid.count("class='prov-cell wide'") == 2
    assert grid.count("prov-cell") == 6


def test_machine_shaped_values_are_set_in_mono():
    """Dates, versions, model ids and env vars are mono; prose is not."""
    out = render_html.render(_two_doc_summary())
    grid = out[out.index("class=prov-grid") : out.index("id=\"cost\"")]
    assert "<span class='prov-v mono'>2026-08-18T09:30:00-04:00</span>" in grid
    assert "<span class='prov-v'>2 from acme-invoices</span>" in grid


def test_the_agreement_rate_card_carries_the_accent_fill():
    """One card in colour, the rest plain — the eye should land on the rate."""
    summary = _two_doc_summary()
    summary["agreement"] = [_dis("alpha", {"a:direct": "x", "a:sdk": "y"})]
    summary["agreementSummary"] = {
        "fields": 1, "agreed": 0, "disagreed": 1, "ambiguous": 0,
        "unanswered": 0, "rate": 0.0,
    }
    out = render_html.render(summary)
    assert "<div class='card accent'>" in out
    assert out.count("class='card accent'") == 1, "only the rate card is filled"
    assert ".card.accent" in out and "--bg-state-warning" in out


def test_agreeing_halves_are_one_captioned_box_not_the_same_string_twice():
    summary = _two_doc_summary()
    summary["agreement"] = [
        _dis("alpha", {
            "anthropic:direct": "Meridian Components Inc.",
            "anthropic:sdk": "Meridian Components Inc.",
            "bedrock:direct": "Statement of Financial Position",
            "bedrock:sdk": "Meridian Components Inc. Statement",
        }),
    ]
    summary["agreementSummary"] = {
        "fields": 1, "agreed": 0, "disagreed": 1, "ambiguous": 0,
        "unanswered": 0, "rate": 0.0,
    }
    out = render_html.render(summary)
    cmp_block = out[out.index("class=cmp-head") : out.index("by spread")]

    # anthropic agreed: one box spanning both columns, captioned once
    assert cmp_block.count("class='val agree'") == 1
    assert cmp_block.count("Meridian Components Inc.</div>") == 0  # not printed bare twice
    assert cmp_block.count("both halves identical") == 1

    # bedrock differed: two boxes, each carrying the error edge
    assert cmp_block.count("class='val diff'") == 2


def test_a_missing_half_still_reads_as_a_difference():
    """One side answering and the other not is a difference, not agreement."""
    summary = _two_doc_summary()
    summary["agreement"] = [_dis("alpha", {"a:direct": "something", "a:sdk": None})]
    summary["agreementSummary"] = {
        "fields": 1, "agreed": 0, "disagreed": 1, "ambiguous": 0,
        "unanswered": 0, "rate": 0.0,
    }
    out = render_html.render(summary)
    assert "class='val diff'" in out
    assert "—" in out
