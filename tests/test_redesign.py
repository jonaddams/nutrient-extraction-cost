"""The canvas redesign: numbered sections, editorial headlines, computed copy.

The design that this implements ships beautiful sentences containing run-specific
figures — "Seventeen documents, three models", "seven disagreements". Every one of
them must be computed here. Hardcoding any of them would recreate, one day later,
the exact Critical the whole-branch review caught: a report asserting measurements
it did not take.
"""

import re

import pytest

from costlab import agreement, brand, render_html, report
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
         "values": {"bedrock:direct": "A", "bedrock:sdk": "B"}, "distinct": 2},
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
    """A disagreed row shaped the way `agreement()` actually produces one --
    including `distinct`, computed with the comparator's own
    `normalise_values` rather than omitted. A fixture missing this key
    describes a row shape the real comparator can never emit, which is
    exactly how 29 tests never noticed render_html recomputing `distinct`
    itself instead of reading the comparator's own count."""
    distinct = len(set(agreement.normalise_values(values).values()))
    return {
        "docId": doc, "field": field, "state": "disagreed", "values": values,
        "distinct": distinct,
    }


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
    # Where every configuration differed, the row says so — a stronger
    # statement than the bare count, and the one to read first.
    assert "<strong>4 of 4</strong> configurations differed" in out
    assert "<strong>2 of 2</strong> configurations differed" in out


def test_a_partial_disagreement_reports_its_distinct_count():
    """Not every row is unanimous: 2 distinct answers across 4 configurations
    is a different finding from 4 of 4, and must not be flattened into it."""
    summary = _two_doc_summary()
    summary["agreement"] = [
        _dis("part", {"a:direct": "x", "a:sdk": "x", "b:direct": "y", "b:sdk": "y"}),
    ]
    summary["agreementSummary"] = {
        "fields": 1, "agreed": 0, "disagreed": 1, "ambiguous": 0,
        "unanswered": 0, "rate": 0.0,
    }
    out = render_html.render(summary)
    assert "<strong>2</strong> distinct answers" in out
    assert "configurations differed" not in out[out.index("by spread"):]


def test_the_excluded_count_is_stated_not_implied():
    summary = _two_doc_summary()
    summary["agreement"] = [_dis("alpha", {"a:direct": "x", "a:sdk": "y"})]
    summary["agreementSummary"] = {
        "fields": 4, "agreed": 1, "disagreed": 1, "ambiguous": 1,
        "unanswered": 1, "rate": 0.5,
    }
    out = render_html.render(summary)
    # The rendered phrase itself, not a bare "2" that could match anything on
    # the page -- the excluded count (ambiguous + unanswered) must be the
    # number actually printed beside its own label.
    assert re.search(
        r"figure-xl>2</span>\s*<span class=figure-note>"
        r"fields excluded as unjudgeable or unanswered",
        out,
    )


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
    # The rule itself, not just both strings appearing anywhere on the page
    # (which would pass even if `--bg-state-warning` were only ever declared
    # on `:root` and never applied to `.card.accent`).
    assert re.search(r"\.card\.accent\s*\{[^}]*--bg-state-warning", out)


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


def test_the_price_note_is_an_accent_panel_with_its_flag_in_code():
    out = render_html.render(_two_doc_summary())
    assert "<div class=price-note>" in out
    # The rule itself applies the token as a background, not merely both
    # strings coexisting somewhere on the page.
    assert re.search(r"\.price-note\s*\{[^}]*--bg-state-warning", out)


def test_marking_flags_as_code_cannot_introduce_other_markup():
    """The note is prose from prices.json: escape first, then wrap only a
    known-safe pattern, so the <code> tags are the only markup that can appear."""
    hostile = render_html._code_flags(
        __import__("html").escape("use --prices <script>alert(1)</script>")
    )
    assert "<code>--prices</code>" in hostile
    assert "<script>" not in hostile
    assert "&lt;script&gt;" in hostile


def test_appendix_a_opens_onto_its_models_not_onto_every_row():
    """Opening A should answer "which models, and what constant" first.

    Each model's rows are a nested, collapsed panel, so the reader chooses to
    see fifty-one rows rather than being handed them.
    """
    out = render_html.render(_two_doc_summary())
    a = out[out.index('id="appendix-a"') : out.index('id="appendix-b"')]
    assert 'id="appendix-a" open' in out
    assert "<details class=group>" in a
    assert "class=group-id" in a


def test_an_unpriced_model_says_so_in_its_group_summary():
    table = PriceTable(checked_on="2026-08-14", rates={})
    records = [
        _rec("alpha", "openai", True, 1000),
        _rec("alpha", "openai", False, 600),
    ]
    summary = report.summarise(records, table, models={"openai": "gpt-5.4"})
    out = render_html.render(summary)
    assert "not priced" in out[out.index('id="appendix-a"'):]


def test_the_price_panel_is_lettered_like_its_siblings():
    out = render_html.render(_two_doc_summary())
    assert 'id="appendix-d"' in out
    assert "D · Price table" in out


def test_the_page_has_a_ground_for_its_white_cards_to_sit_on():
    """Warm paper page, white cards. On a white page the cards read as
    floating outlines, which is what the first render looked like."""
    css = brand.asset("theme.css")
    body = css[css.index("body {") : css.index("}", css.index("body {"))]
    assert "var(--bg-neutral-default-secondary)" in body
    assert "var(--bg-neutral-default-primary)" not in body

    # and the cards are still the lighter tone, or there is no contrast at all
    card = css[css.index(".card {") : css.index("}", css.index(".card {"))]
    assert "var(--bg-neutral-default-primary)" in card


def test_printing_does_not_tint_every_page():
    print_css = brand.asset("print.css")
    assert "background: #fff" in print_css


def test_a_run_where_everything_agreed_still_counts_its_configurations():
    """The best possible outcome must not announce "Zero configurations".

    Counting configurations from disagreeing rows only meant a clean run — every
    configuration returning the same answer — reported zero of them, which is
    false and reads as absurd. Configurations are counted across every row.
    """
    summary = _two_doc_summary()
    summary["agreement"] = [{
        "docId": "alpha", "field": "documentTitle", "state": "agreed",
        "values": {"bedrock:direct": "same", "bedrock:sdk": "same"},
    }]
    summary["agreementSummary"] = {
        "fields": 1, "agreed": 1, "disagreed": 0, "ambiguous": 0,
        "unanswered": 0, "rate": 1.0,
    }

    out = render_html.render(summary)
    headline = re.findall(r"<h2>(.*?)</h2>", out, re.S)[1]

    assert "Zero configurations" not in headline
    assert "Two configurations" in headline
    assert "no disagreements" in headline


# --- the page's "distinct" must be the comparator's, not a recomputation ---


def test_distinct_is_read_from_the_comparator_never_recomputed():
    """A row where three configurations answered nothing and one answered
    "Globex" has TWO distinct answers by the comparator's own rule (every
    absence is one shared answer) -- not four, which is what counting raw
    string reprs of None / "" / "." / "Globex" would give."""
    summary = _two_doc_summary()
    summary["agreement"] = [
        _dis("alpha", {
            "anthropic:direct": None, "anthropic:sdk": "",
            "openai:direct": ".", "openai:sdk": "Globex",
        }),
    ]
    summary["agreementSummary"] = {
        "fields": 1, "agreed": 0, "disagreed": 1, "ambiguous": 0,
        "unanswered": 0, "rate": 0.0,
    }
    out = render_html.render(summary)
    assert "2 distinct answers across 4 configurations" in out
    assert "4 distinct answers" not in out


def test_render_html_distinct_indexes_the_row_strictly():
    row = {"values": {"a:direct": "x", "a:sdk": "y"}, "distinct": 2}
    assert render_html._distinct(row) == 2

    with pytest.raises(KeyError):
        render_html._distinct({"values": {"a:direct": "x", "a:sdk": "y"}})


def test_the_sameness_test_uses_the_comparators_normalisation():
    """"Acme Corp." and "acme corp" are the same answer by the comparator's
    own text normalisation -- punctuation and case are typography, not
    content. Comparing raw strings would render this as the SDK
    disagreeing with the direct call over nothing."""
    summary = _two_doc_summary()
    summary["agreement"] = [
        _dis("alpha", {
            "a:direct": "Acme Corp.", "a:sdk": "acme corp",
            "b:direct": "Globex", "b:sdk": "Globex Inc",
        }),
    ]
    summary["agreementSummary"] = {
        "fields": 1, "agreed": 0, "disagreed": 1, "ambiguous": 0,
        "unanswered": 0, "rate": 0.0,
    }
    out = render_html.render(summary)
    cmp_block = out[out.index("class=cmp-head"):]
    assert "both halves identical" in cmp_block
    assert cmp_block.count("class='val agree'") == 1
    assert cmp_block.count("class='val diff'") == 2


# --- nothing judged must not read as a clean bill of health ---------------


def test_nothing_judged_says_so_plainly():
    summary = _two_doc_summary()
    summary["agreement"] = [
        {"docId": "alpha", "field": "documentTitle", "state": "ambiguous",
         "values": {"a:direct": "4/1/2026", "a:sdk": "2026-01-04"}, "distinct": 2},
    ]
    summary["agreementSummary"] = {
        "fields": 1, "agreed": 0, "disagreed": 0, "ambiguous": 1,
        "unanswered": 0, "rate": None,
    }
    out = render_html.render(summary)
    headline = re.findall(r"<h2>(.*?)</h2>", out, re.S)[1]

    assert "no disagreements" not in headline
    assert "nothing could be judged" in headline
    accuracy = out[out.index('id="agreement"'):]
    card = accuracy[: accuracy.index("card accent") + 400]
    assert "0 of 0" not in card
    assert "nothing could be judged" in card


# --- an empty string is an absence too, not a blank box --------------------


def test_an_empty_string_reads_as_no_answer_not_a_blank_box():
    summary = _two_doc_summary()
    summary["agreement"] = [
        _dis("alpha", {"a:direct": "", "a:sdk": "Meridian"}),
    ]
    summary["agreementSummary"] = {
        "fields": 1, "agreed": 0, "disagreed": 1, "ambiguous": 0,
        "unanswered": 0, "rate": 0.0,
    }
    out = render_html.render(summary)
    cmp_block = out[out.index("class=cmp-head"):]
    assert "<div class='val diff'>—</div>" in cmp_block


# --- an unrecognised configuration key must not vanish ---------------------


def test_an_unrecognised_half_raises_instead_of_vanishing():
    with pytest.raises(ValueError):
        render_html._by_provider_half(
            {"values": {"a:sdk-retry": "Y"}, "distinct": 1}
        )


# --- singular counts must be grammatical and true ---------------------------


def test_a_single_configuration_row_cannot_have_differed():
    """A row with exactly one configuration cannot report "1 of 1
    configurations differed" -- there is nothing else it could differ from."""
    summary = _two_doc_summary()
    summary["agreement"] = [_dis("solo", {"a:direct": "x"})]
    summary["agreementSummary"] = {
        "fields": 1, "agreed": 0, "disagreed": 1, "ambiguous": 0,
        "unanswered": 0, "rate": 0.0,
    }
    out = render_html.render(summary)
    assert "1 of 1" not in out
    assert "<strong>1</strong> distinct answer" in out
    # a single ranked row reads "The one, by spread", not "All one, by spread"
    assert "The one, by spread" in out
    assert "All one" not in out


# --- a per-100k figure is dollar-scale, not per-document cents -------------


def test_money_at_scale_drops_to_two_decimals_at_a_dollar():
    assert render_html._money_at_scale(367.8) == "$367.80"
    assert render_html._money_at_scale(0.0037) == "$0.0037"
    assert render_html._money_at_scale(None) == "not priced"


def test_the_flagship_card_does_not_print_four_decimals_over_a_dollar():
    table = PriceTable(
        checked_on="2026-08-14",
        rates={"bedrock": {"qwen3-vl": {"inputPerMTok": 100.0, "outputPerMTok": 100.0}}},
    )
    records = [
        _rec("alpha", "bedrock", True, 1_000_000),
        _rec("alpha", "bedrock", False, 600_000),
    ]
    summary = report.summarise(records, table, models={"bedrock": "qwen3-vl"})
    out = render_html.render(summary)
    cost = out[out.index('id="cost"'): out.index('id="agreement"')]
    assert "$4000.0000" not in cost
    assert re.search(r"\$[\d,]+\.\d{2}<", cost)


# --- a degenerate range is a single figure, stated as one -------------------


def test_a_zero_spread_states_one_figure_not_a_degenerate_range():
    assert render_html._spread(1226, 1226) == "exactly +1,226 on every call"
    assert render_html._spread(1200, 1226) == "+1,200 to +1,226"
    assert render_html._spread(None, None) == "n/a"


# --- the printed appendix must actually be revealed -------------------------


def test_print_css_reveals_closed_details_content():
    print_css = brand.asset("print.css")
    assert "details::details-content" in print_css
    assert "content-visibility: visible" in print_css


def test_theme_css_has_no_orphaned_tile_or_answer_rules():
    theme_css = brand.asset("theme.css")
    assert ".tile {" not in theme_css
    assert ".answer {" not in theme_css


def test_print_css_break_rules_name_live_classes():
    print_css = brand.asset("print.css")
    assert ".tile" not in print_css
    for live_class in (".card", ".caveat", ".cmp", "details.group", ".prov-cell"):
        assert live_class in print_css
