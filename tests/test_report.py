from costlab.prices import PriceTable
from costlab.report import render_html, render_json, render_terminal, summarise


def _rec(doc, pid, with_nutrient, inp):
    return {
        "docId": doc,
        "providerId": pid,
        "withNutrient": with_nutrient,
        "usage": {"inputTokens": inp, "outputTokens": 10, "cachedInputTokens": 0},
        "status": 200,
        "latencyMs": 1000.0,
    }


def test_summarise_computes_the_delta_per_provider():
    table = PriceTable(checked_on="2026-08-14", rates={})
    out = summarise(
        [_rec("a", "bedrock", True, 1000), _rec("a", "bedrock", False, 600)], table
    )
    row = out["byDocument"][0]
    assert row["deltaInputTokens"] == 400


def test_records_without_usage_are_excluded_and_counted():
    # A provider that reports no usage must not silently become a zero-token
    # row that drags every average down.
    table = PriceTable(checked_on="2026-08-14", rates={})
    bad = _rec("b", "local", True, 0)
    bad["usage"] = None
    out = summarise(
        [_rec("a", "bedrock", True, 900), _rec("a", "bedrock", False, 500), bad],
        table,
    )
    assert out["unmeasurable"] == 1
    assert len(out["byDocument"]) == 1


# --- Beyond the plan. Each of these is a way the report could mislead.


def _priced_table():
    return PriceTable(
        checked_on="2026-08-14",
        rates={
            "bedrock": {
                "qwen.qwen3-vl-235b-a22b-instruct": {
                    "inputPerMTok": 0.53,
                    "outputPerMTok": 2.66,
                }
            }
        },
    )


def test_cost_is_computed_from_the_table_not_invented():
    out = summarise(
        [
            _rec("a", "bedrock", True, 1_000_000),
            _rec("a", "bedrock", False, 500_000),
        ],
        _priced_table(),
        models={"bedrock": "qwen.qwen3-vl-235b-a22b-instruct"},
    )
    row = out["byDocument"][0]
    assert row["priced"] is True
    # 1M input at 0.53 plus 10 output tokens at 2.66/MTok.
    assert round(row["sdkCost"], 6) == round(0.53 + 10 * 2.66 / 1_000_000, 6)
    assert round(row["deltaCost"], 6) == round(0.53 - 0.265, 6)


def test_an_unpriced_provider_reports_tokens_but_no_dollars():
    """Missing a rate must not become a zero cost. A row that says $0.00 asserts
    the calls were free; a row that says "not priced" says we do not know."""
    out = summarise(
        [_rec("a", "openai", True, 1000), _rec("a", "openai", False, 600)],
        _priced_table(),
        models={"openai": "gpt-5.4"},
    )
    row = out["byDocument"][0]
    assert row["deltaInputTokens"] == 400
    assert row["priced"] is False
    assert row["sdkCost"] is None
    assert row["deltaCost"] is None
    assert "not priced" in render_terminal(out)
    assert "$0.00" not in render_terminal(out)


def test_html_never_shows_a_dollar_figure_without_the_date_it_was_priced_on():
    out = summarise(
        [
            _rec("a", "bedrock", True, 1_000_000),
            _rec("a", "bedrock", False, 500_000),
        ],
        _priced_table(),
        models={"bedrock": "qwen.qwen3-vl-235b-a22b-instruct"},
    )
    html = render_html(out)
    assert "$" in html
    assert "2026-08-14" in html


def test_html_states_the_direct_cells_lose_page_coordinates():
    """The two halves are not feature-equivalent, and a price comparison that
    omits this is the most misleading thing this tool could publish."""
    out = summarise(
        [_rec("a", "bedrock", True, 1000), _rec("a", "bedrock", False, 600)],
        _priced_table(),
    )
    html = render_html(out).lower()
    assert "coordinate" in html


def test_html_warns_that_token_counts_do_not_compare_across_providers():
    """Measured 2026-08-14: the same document was 1,800 prompt tokens on OpenAI,
    2,282 on Bedrock and 2,540 on Anthropic. A reader comparing those columns is
    comparing tokenizers, not efficiency."""
    out = summarise(
        [
            _rec("a", "bedrock", True, 1000),
            _rec("a", "bedrock", False, 600),
            _rec("a", "anthropic", True, 1400),
            _rec("a", "anthropic", False, 900),
        ],
        _priced_table(),
    )
    html = render_html(out).lower()
    assert "tokeni" in html  # tokenizer / tokenisation, either spelling


def test_the_dollar_delta_is_reconcilable_from_the_token_columns_shown():
    """The measured $31.99/100k on Bedrock is more than 468 input tokens alone
    accounts for: output differs too, and output is priced ~5x input. If the
    report shows only an input delta, the dollar figure looks like an arithmetic
    error. Both deltas must be visible."""
    recs = [
        _rec("a", "bedrock", True, 1000),
        _rec("a", "bedrock", False, 600),
    ]
    recs[0]["usage"]["outputTokens"] = 40
    recs[1]["usage"]["outputTokens"] = 10
    out = summarise(
        recs, _priced_table(), models={"bedrock": "qwen.qwen3-vl-235b-a22b-instruct"}
    )
    prov = out["byProvider"][0]
    assert prov["deltaInputTokens"] == 400
    assert prov["deltaOutputTokens"] == 30
    expected = (400 * 0.53 + 30 * 2.66) / 1_000_000
    assert round(prov["deltaCost"], 10) == round(expected, 10)
    assert "+30" in render_terminal(out)


def test_one_verbose_direct_call_cannot_flip_the_headline_projection():
    """Measured on the 17-document corpus: one document's direct call emitted
    ~7,500 more output tokens than its SDK counterpart, and because output prices
    ~5x input that single outlier dragged the aggregate from +$21 to -$87 per
    100k — i.e. it made the SDK look cheaper overall. The headline is priced from
    input tokens, which measure the same document on both sides. The
    output-inclusive total is still reported, separately and labelled.
    """
    recs = [
        _rec("normal", "bedrock", True, 1000),
        _rec("normal", "bedrock", False, 532),
        _rec("outlier", "bedrock", True, 1000),
        _rec("outlier", "bedrock", False, 532),
    ]
    recs[3]["usage"]["outputTokens"] = 7_500  # the verbose direct call
    out = summarise(
        recs, _priced_table(), models={"bedrock": "qwen.qwen3-vl-235b-a22b-instruct"}
    )
    prov = out["byProvider"][0]
    assert prov["deltaInputTokens"] == 936
    # Input-priced headline stays positive and reflects the constant.
    assert prov["deltaCostPer100k"] > 0
    # The output-inclusive figure goes negative, and is kept visible rather than
    # silently becoming the headline.
    assert prov["deltaCostPer100kIncludingOutput"] < 0
    text = render_terminal(out)
    assert "input" in text and "not like-for-like" in text


def test_at_volume_projection_scales_the_measured_mean():
    """A per-document delta of $0.0003 is true and useless; the decision is made
    at volume. The projection is linear, which is only legitimate because the
    delta is a constant per call — the per-call spread is the warning if not."""
    out = summarise(
        [
            _rec("a", "bedrock", True, 1_000_000),
            _rec("a", "bedrock", False, 500_000),
        ],
        _priced_table(),
        models={"bedrock": "qwen.qwen3-vl-235b-a22b-instruct"},
    )
    prov = out["byProvider"][0]
    assert prov["deltaCostPer100k"] == prov["deltaCost"] / 1 * 100_000
    assert prov["deltaMin"] == prov["deltaMax"] == 500_000


def test_at_volume_projection_is_absent_rather_than_zero_when_unpriced():
    out = summarise(
        [_rec("a", "openai", True, 1000), _rec("a", "openai", False, 600)],
        _priced_table(),
        models={"openai": "gpt-5.4"},
    )
    assert out["byProvider"][0]["deltaCostPer100k"] is None


def test_json_render_round_trips():
    import json

    out = summarise(
        [_rec("a", "bedrock", True, 1000), _rec("a", "bedrock", False, 600)],
        _priced_table(),
    )
    assert json.loads(render_json(out))["byDocument"][0]["deltaInputTokens"] == 400
