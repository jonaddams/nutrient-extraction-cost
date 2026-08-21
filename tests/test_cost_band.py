"""The cost band names the model it measured, not just the provider.

The band's own sentence is that the overhead is a constant *per model* and does
not transfer to a sibling from the same family. Two of the four provider labels
name neither a model nor anything re-runnable — "OpenAI" is a vendor and "Local
runtime" is a place — so a card reading "Local runtime  +468 input tokens per
document" states a per-model constant without saying which model. Same shape as
the twelfth defect: a true label around a claim it does not support.

Fixing the labels in PROVIDERS is not the alternative. A local runtime's model is
determined at run time by LOCAL_MODEL, so a static label cannot carry it — which
is exactly why that label is generic in the first place.
"""

from costlab import render_html
from costlab.prices import PriceTable
from costlab.report import summarise


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
    }


def _table():
    return PriceTable(checked_on="2026-08-14", rates={})


def _pair(pid):
    return [_rec("a", pid, True, 1000), _rec("a", pid, False, 600)]


def test_by_provider_carries_the_resolved_model_id():
    out = summarise(_pair("openai"), _table(), models={"openai": "gpt-5.4"})
    assert out["byProvider"][0]["model"] == "gpt-5.4"


def test_the_model_id_falls_back_to_the_provider_default():
    """A run that recorded no explicit model still used one. An empty cell would
    read as "unknown model" under a per-model claim."""
    out = summarise(_pair("bedrock"), _table())
    assert out["byProvider"][0]["model"] == "qwen.qwen3-vl-235b-a22b-instruct"


def test_a_cost_card_names_the_model_id():
    out = render_html.render(
        summarise(_pair("openai"), _table(), models={"openai": "gpt-5.4"})
    )
    cost = out[out.index('id="cost"') : out.index('id="caveats"')]
    assert "gpt-5.4" in cost


def test_a_local_runtime_card_names_which_weights_produced_the_constant():
    """The case that matters most: every LM Studio model reports as `local`, so
    without the model id two runs of different weights produce identically
    labelled cards carrying different constants."""
    out = render_html.render(
        summarise(_pair("local"), _table(), models={"local": "qwen/qwen3-vl-8b"})
    )
    cost = out[out.index('id="cost"') : out.index('id="caveats"')]
    assert "qwen/qwen3-vl-8b" in cost
    assert "Local runtime" in cost, "the human label stays; the id joins it"


def test_the_provider_appendix_names_the_model_id():
    """Appendix B is the per-provider totals table, and it carries the same
    per-model constants as the cards."""
    out = render_html.render(
        summarise(_pair("local"), _table(), models={"local": "qwen/qwen3-vl-8b"})
    )
    appendix = out[out.index('id="appendix-b"') :]
    assert "qwen/qwen3-vl-8b" in appendix
