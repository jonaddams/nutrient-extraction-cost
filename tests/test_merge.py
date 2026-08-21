"""Combining saved runs into one report.

The four accuracy rungs live in two runs — the frontier models in one, the
self-hosted model in another — so the band restructured to compare them cannot
show them together without this. The whole risk here is that `providerId` is not
a model: every LM Studio model in this project ran as `local`, so a careless
merge sums two different models into one row and labels it with whichever ran
last. That is the failure this module exists to refuse.
"""

import pytest

from costlab.answers import AnswerKey
from costlab.merge import merge_runs
from costlab.prices import PriceTable
from costlab.report import summarise


def _rec(doc, pid, with_nutrient, inp, extracted=None):
    return {
        "docId": doc,
        "providerId": pid,
        "withNutrient": with_nutrient,
        "usage": {"inputTokens": inp, "outputTokens": 10, "cachedInputTokens": 0},
        "status": 200,
        "latencyMs": 1000.0,
        "schemaSource": "answer-key",
        "extracted": extracted if extracted is not None else {"total": 100},
    }


def _run(name, pid, model, date, *, schema="answer-key", doc="a"):
    records = [
        {**_rec(doc, pid, True, 1000), "schemaSource": schema},
        {**_rec(doc, pid, False, 600), "schemaSource": schema},
    ]
    return {
        "name": name,
        "records": records,
        "provenance": {
            "corpusName": "Nutrient sample corpus",
            "documentCount": 1,
            "models": [{"providerId": pid, "model": model}],
            "keySources": [f"{pid.upper()}_API_KEY (set)"],
            "runDate": date,
            "priceTableDate": "2026-08-14",
            "toolVersion": "0.1.0",
        },
    }


def _key():
    return AnswerKey(
        checked_on="2026-08-14",
        documents={"a": {"total": {"value": 100, "source": "Total 100"}}},
    )


def test_merging_two_runs_puts_both_models_in_one_report():
    records, prov = merge_runs([
        _run("frontier", "anthropic", "claude-sonnet-5", "2026-08-20T15:00:00-04:00"),
        _run("local", "local", "qwen/qwen3-vl-8b", "2026-08-20T17:02:38-04:00"),
    ])
    assert len(records) == 4
    out = summarise(records, PriceTable(checked_on="2026-08-14", rates={}),
                    provenance=prov, key=_key())
    assert [r["providerId"] for r in out["accuracyByModel"]] == ["anthropic", "local"]


def test_the_same_provider_id_running_two_different_models_is_refused():
    """`local` is a port, not a model. Summing qwen3-vl-8b and qwen3-vl-30b into
    one row would present two measurements as one and label it with whichever
    provenance won — the exact class of quiet dishonesty this tool removes."""
    with pytest.raises(ValueError) as err:
        merge_runs([
            _run("a", "local", "qwen/qwen3-vl-8b", "2026-08-20T15:00:00-04:00"),
            _run("b", "local", "qwen/qwen3-vl-30b", "2026-08-20T17:00:00-04:00"),
        ])
    assert "local" in str(err.value)
    assert "qwen/qwen3-vl-8b" in str(err.value)
    assert "qwen/qwen3-vl-30b" in str(err.value)


def test_the_same_provider_running_the_same_model_twice_is_allowed():
    """Two shards of one measurement, or a re-run of the same model, is a
    legitimate thing to combine."""
    records, prov = merge_runs([
        _run("a", "local", "qwen/qwen3-vl-8b", "2026-08-20T15:00:00-04:00", doc="a"),
        _run("b", "local", "qwen/qwen3-vl-8b", "2026-08-20T17:00:00-04:00", doc="b"),
    ])
    assert len(records) == 4


def test_a_run_without_recorded_models_cannot_be_merged_over_a_shared_provider():
    """If we cannot confirm two runs used the same weights, we must not assume
    they did. Failing loud beats a plausible wrong row."""
    a = _run("a", "local", "qwen/qwen3-vl-8b", "2026-08-20T15:00:00-04:00")
    b = _run("b", "local", "qwen/qwen3-vl-8b", "2026-08-20T17:00:00-04:00")
    b["provenance"].pop("models")
    with pytest.raises(ValueError) as err:
        merge_runs([a, b])
    assert "local" in str(err.value)


def test_the_unrecorded_model_check_does_not_depend_on_argument_order():
    """The first version of this guard only looked backwards, so a run with no
    recorded models escaped the check whenever it was listed FIRST: the same two
    runs were refused or silently merged depending on the order typed on the
    command line. A safety check that an argument order can switch off is not a
    safety check.
    """
    with_models = _run("acc", "anthropic", "claude-sonnet-5",
                       "2026-08-20T16:00:00-04:00")
    without = _run("cost", "anthropic", "claude-sonnet-5",
                   "2026-08-17T13:00:00-04:00")
    without["provenance"].pop("models")

    for order in ([without, with_models], [with_models, without]):
        with pytest.raises(ValueError) as err:
            merge_runs(order)
        assert "cost" in str(err.value)


def test_merged_provenance_names_every_run_and_its_date():
    """One report built from measurements taken at different times must say so;
    a single run date would be a false statement about when this was gathered."""
    _, prov = merge_runs([
        _run("frontier", "anthropic", "claude-sonnet-5", "2026-08-20T15:00:00-04:00"),
        _run("local", "local", "qwen/qwen3-vl-8b", "2026-08-20T17:02:38-04:00"),
    ])
    assert "2026-08-20T15:00:00-04:00" in prov["runDate"]
    assert "2026-08-20T17:02:38-04:00" in prov["runDate"]
    assert len(prov["sourceRuns"]) == 2


def test_a_joined_report_carries_a_caveat_saying_it_is_joined():
    _, prov = merge_runs([
        _run("frontier", "anthropic", "claude-sonnet-5", "2026-08-20T15:00:00-04:00"),
        _run("local", "local", "qwen/qwen3-vl-8b", "2026-08-20T17:02:38-04:00"),
    ])
    out = summarise([], PriceTable(checked_on="2026-08-14", rates={}), provenance=prov)
    assert any("separate run" in c for c in out["caveats"])


def test_a_single_run_gains_no_joined_caveat():
    """The caveat has to be absent when it does not apply, or it becomes noise
    every reader learns to skip."""
    run = _run("only", "anthropic", "claude-sonnet-5", "2026-08-20T15:00:00-04:00")
    out = summarise(
        run["records"],
        PriceTable(checked_on="2026-08-14", rates={}),
        provenance=run["provenance"],
    )
    assert not any("separate run" in c for c in out["caveats"])


def test_the_page_shows_every_run_date_not_just_one():
    """The provenance grid has one "Run" cell. On a joined report it has to
    carry both dates: naming one would be a false statement about when half the
    figures were measured."""
    from costlab import render_html

    records, prov = merge_runs([
        _run("frontier", "anthropic", "claude-sonnet-5", "2026-08-20T15:00:00-04:00"),
        _run("local", "local", "qwen/qwen3-vl-8b", "2026-08-20T17:02:38-04:00"),
    ])
    out = render_html.render(
        summarise(records, PriceTable(checked_on="2026-08-14", rates={}),
                  provenance=prov, key=_key())
    )
    assert "2026-08-20T15:00:00-04:00" in out
    assert "2026-08-20T17:02:38-04:00" in out
    assert "separate run" in out, "the joined caveat must reach the page"


def test_merging_a_cost_run_with_an_accuracy_run_still_warns_on_mixed_schemas():
    """Joining must not launder the incomparability it inherits: a shared-schema
    run and a key-derived run have token counts that cannot be compared."""
    records, prov = merge_runs([
        _run("cost", "anthropic", "claude-sonnet-5", "2026-08-20T15:00:00-04:00",
             schema="shared"),
        _run("acc", "local", "qwen/qwen3-vl-8b", "2026-08-20T17:00:00-04:00"),
    ])
    out = summarise(records, PriceTable(checked_on="2026-08-14", rates={}),
                    provenance=prov)
    assert out["mixedSchemas"] is True
