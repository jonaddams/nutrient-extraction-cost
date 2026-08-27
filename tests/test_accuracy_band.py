"""The accuracy band, organised by model rather than by provider-and-half.

Jon chose this shape on 2026-08-20: four rows, frontier to self-hosted, because
on-prem cost and privacy is the argument the report exists to make — otherwise a
reader could just use the hosted API. Organised by provider-and-half, the
comparison a buyer cares about is one the reader has to assemble themselves.
"""

from costlab import render_html
from costlab.answers import AnswerKey
from costlab.prices import PriceTable
from costlab.report import summarise


def _rec(doc, pid, with_nutrient, inp, extracted):
    return {
        "docId": doc,
        "providerId": pid,
        "withNutrient": with_nutrient,
        "usage": {"inputTokens": inp, "outputTokens": 10, "cachedInputTokens": 0},
        "status": 200,
        "latencyMs": 1000.0,
        "extracted": extracted,
    }


def _table():
    return PriceTable(checked_on="2026-08-14", rates={})


def _key_one_field():
    return AnswerKey(
        checked_on="2026-08-14",
        documents={"a": {"total": {"value": 100, "source": "Total 100"}}},
    )


def _both_halves(pid, sdk_value, direct_value):
    return [
        _rec("a", pid, True, 1000, {"total": sdk_value}),
        _rec("a", pid, False, 600, {"total": direct_value}),
    ]


def test_a_model_s_two_halves_land_on_one_row():
    out = summarise(_both_halves("bedrock", 100, 999), _table(), key=_key_one_field())
    rows = out["accuracyByModel"]
    assert len(rows) == 1, "one row per model, not one per model-and-half"
    row = rows[0]
    assert row["providerId"] == "bedrock"
    assert row["label"] == "Qwen3-VL 235B (Bedrock)"
    assert row["sdk"]["accuracy"] == 1.0
    assert row["direct"]["accuracy"] == 0.0


def test_rows_run_frontier_then_hosted_then_self_hosted():
    """The ordering IS the argument: a self-hosted model landing near a frontier
    one only reads as a finding if the rungs descend in what they cost and
    concede. Alphabetical order puts the local runtime first and says nothing."""
    recs = []
    for pid in ("local", "bedrock", "anthropic"):
        recs += _both_halves(pid, 100, 100)
    out = summarise(recs, _table(), key=_key_one_field())
    assert [r["providerId"] for r in out["accuracyByModel"]] == [
        "anthropic",
        "bedrock",
        "local",
    ]
    assert [r["rung"] for r in out["accuracyByModel"]] == [
        "frontier",
        "hosted",
        "self-hosted",
    ]


def test_an_unscoreable_half_is_absent_rather_than_zero():
    """`None` means the harness could not read the answer; 0.0 says the model got
    everything wrong. Three separate defects in this project came from conflating
    those two, so pairing the halves onto one row must not collapse them."""
    recs = [
        _rec("a", "bedrock", True, 1000, {"total": 100}),
        _rec("a", "bedrock", False, 600, None),
    ]
    out = summarise(recs, _table(), key=_key_one_field())
    row = out["accuracyByModel"][0]
    assert row["sdk"]["accuracy"] == 1.0
    assert row["direct"]["accuracy"] is None
    assert row["direct"]["unscoreable"] == 1


def test_each_half_keeps_its_own_denominator():
    """The halves can be computed over different document counts — the harness
    skips a direct cell whose SDK cell failed. One shared denominator on the row
    would hide that and invite a like-for-like reading the data cannot support."""
    key = AnswerKey(
        checked_on="2026-08-14",
        documents={
            "a": {"total": {"value": 100, "source": "Total 100"}},
            "b": {"total": {"value": 200, "source": "Total 200"}},
        },
    )
    recs = [
        _rec("a", "bedrock", True, 1000, {"total": 100}),
        _rec("a", "bedrock", False, 600, {"total": 100}),
        _rec("b", "bedrock", True, 1000, {"total": 200}),
    ]
    out = summarise(recs, _table(), key=key)
    row = out["accuracyByModel"][0]
    assert row["sdk"]["verified"] == 2
    assert row["direct"]["verified"] == 1


def test_a_model_run_on_only_one_half_still_gets_a_row():
    """A direct-only run is a real thing to do, and a provider whose grounded
    cell is unsupported has no SDK half at all. The missing half must read as
    absent — the row still belongs in the band, because its measured half is
    just as valid as anyone else's."""
    recs = [_rec("a", "bedrock", False, 600, {"total": 100})]
    out = summarise(recs, _table(), key=_key_one_field())
    row = out["accuracyByModel"][0]
    assert row["direct"]["accuracy"] == 1.0
    assert row["sdk"] is None


def test_a_model_with_no_answer_key_produces_no_rows():
    """Cost mode runs without a key. The band must be absent, not a table of
    empty rows implying the models were scored and found wanting."""
    out = summarise(_both_halves("bedrock", 100, 100), _table())
    assert out["accuracyByModel"] == []


def test_a_row_carries_the_model_id_it_was_actually_run_against():
    """Two of the four provider labels are not model names — "OpenAI" is a
    vendor and "Local runtime" is a place. In a band organised BY MODEL that is
    the twelfth defect's shape again: a true label around a claim it does not
    support. The resolved model id has to travel with the row.
    """
    out = summarise(
        _both_halves("openai", 100, 100),
        _table(),
        models={"openai": "gpt-5.4"},
        key=_key_one_field(),
    )
    assert out["accuracyByModel"][0]["model"] == "gpt-5.4"


def test_the_model_id_falls_back_to_the_provider_default():
    """A run that did not record which model it used still has one — the
    provider's default. An empty cell would read as "unknown model"."""
    out = summarise(_both_halves("bedrock", 100, 100), _table(), key=_key_one_field())
    assert out["accuracyByModel"][0]["model"] == "qwen.qwen3-vl-235b-a22b-instruct"


# --- The rendered band ----------------------------------------------------
#
# Section 02 was headed "Accuracy" while rendering *agreement*, with the real
# scored accuracy collapsed into an appendix panel. These pin the swap: scored
# accuracy leads, agreement becomes the supporting material underneath it.


def _three_rungs():
    """One run spanning frontier, hosted and self-hosted, with a disagreement.

    The local half is deliberately wrong on the direct side so the band has both
    a scored difference and an agreement difference to render.
    """
    recs = []
    for pid, direct in (("anthropic", 100), ("bedrock", 100), ("local", 999)):
        recs += _both_halves(pid, 100, direct)
    return summarise(recs, _table(), key=_key_one_field())


def _band(html):
    return html[html.index('id="accuracy"') :]


def test_the_band_leads_with_scored_accuracy_before_agreement():
    """The scored figure is the one a buyer is buying. Agreement is context for
    it — two models can agree and both be wrong — so it cannot come first."""
    out = render_html.render(_three_rungs())
    band = _band(out)
    assert band.index("accuracy-by-model") < band.index("card accent")


def test_the_rows_run_frontier_to_self_hosted_in_the_page():
    out = render_html.render(_three_rungs())
    band = _band(out)
    assert (
        band.index("Claude Sonnet 5")
        < band.index("Qwen3-VL 235B (Bedrock)")
        < band.index("Local runtime")
    )


def test_each_row_names_its_rung_so_the_ordering_reads_as_deliberate():
    """Without the rung named, four model labels in a fixed order are just a
    list; the descent from frontier to self-hosted is the whole argument."""
    band = _band(render_html.render(_three_rungs()))
    assert "frontier" in band
    assert "self-hosted" in band


def test_the_page_names_the_model_id_not_only_the_provider_label():
    """A reader quoting a figure needs to know which weights produced it — the
    tool's own finding is that the overhead constant is per model, so a sibling
    from the same family is a different measurement."""
    recs = _both_halves("openai", 100, 100)
    out = render_html.render(
        summarise(recs, _table(), models={"openai": "gpt-5.4"}, key=_key_one_field())
    )
    assert "gpt-5.4" in _band(out)


def test_a_row_shows_both_halves_with_their_own_denominators():
    """A single denominator would hide that the halves cover different document
    counts, which is exactly the like-for-like reading the data cannot support."""
    band = _band(render_html.render(_three_rungs()))
    assert "1/1" in band


def test_an_unscoreable_half_never_renders_as_zero_percent():
    recs = [
        _rec("a", "bedrock", True, 1000, {"total": 100}),
        _rec("a", "bedrock", False, 600, None),
    ]
    band = _band(render_html.render(summarise(recs, _table(), key=_key_one_field())))
    rows = band[band.index("accuracy-by-model") :]
    rows = rows[: rows.index("</table>")]
    assert "not scoreable" in rows
    # "(0%)", not "0%": the sibling half legitimately renders 100%, which
    # contains the substring. The requirement is that nothing renders as a
    # zero SCORE, not that the characters never appear.
    assert "(0%)" not in rows


def test_every_internal_link_resolves_on_a_scored_run():
    """The existing anchor guards both use keyless fixtures, so the links this
    band adds — it points at the appendix panel for the per-half detail — were
    on a path no test rendered. An unfaithful fixture hiding a real defect is
    this project's most expensive recurring mistake."""
    import re

    out = render_html.render(_three_rungs())
    targets = set(re.findall(r'href="#([a-z-]+)"', out))
    assert "appendix-accuracy" in targets, "the band should link to the detail"
    for target in targets:
        assert f'id="{target}"' in out, f"dangling anchor: #{target}"


def test_without_an_answer_key_the_band_makes_no_accuracy_claim():
    """Cost mode has nothing scored. The band still has agreement to show, but
    an empty by-model table would imply the models were scored and did badly."""
    recs = []
    for pid, direct in (("anthropic", 100), ("bedrock", 999)):
        recs += _both_halves(pid, 100, direct)
    out = render_html.render(summarise(recs, _table()))
    band = _band(out)
    assert "accuracy-by-model" not in band
    assert "card accent" in band, "agreement must still render without a key"
