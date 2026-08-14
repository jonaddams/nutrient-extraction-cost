from costlab.agreement import agreement, agreement_summary


def _rec(doc, pid, with_nutrient, extracted):
    return {"docId": doc, "providerId": pid, "withNutrient": with_nutrient,
            "extracted": extracted}


def test_providers_that_agree_are_marked_agreed():
    rows = agreement([
        _rec("inv", "bedrock", True, {"total": "$345,015.00"}),
        _rec("inv", "anthropic", True, {"total": 345015}),
    ])
    row = next(r for r in rows if r["field"] == "total")
    assert row["agree"] is True
    assert row["distinct"] == 1


def test_providers_that_disagree_are_flagged_with_both_values():
    """The disagreement itself is the product: a prospect cannot tell which
    answer is right without a citation to check, which is the argument for
    grounded extraction."""
    rows = agreement([
        _rec("inv", "bedrock", True, {"total": 345015}),
        _rec("inv", "anthropic", True, {"total": 999}),
    ])
    row = next(r for r in rows if r["field"] == "total")
    assert row["agree"] is False
    assert set(row["values"].values()) == {345015, 999}


def test_a_field_only_one_cell_produced_is_not_a_disagreement():
    """One opinion is not a conflict. Counting it as one would inflate the
    disagreement rate with fields nobody contested."""
    rows = agreement([
        _rec("inv", "bedrock", True, {"total": 345015}),
        _rec("inv", "anthropic", True, {}),
    ])
    assert [r["field"] for r in rows] == []


def test_cells_that_extracted_nothing_are_ignored_entirely():
    assert agreement([_rec("inv", "bedrock", True, None),
                      _rec("inv", "anthropic", True, None)]) == []


def test_summary_rate_is_none_rather_than_zero_when_nothing_was_comparable():
    assert agreement_summary([])["rate"] is None


def test_summary_counts_agreed_and_disagreed_fields():
    rows = agreement([
        _rec("a", "bedrock", True, {"x": 1, "y": "same"}),
        _rec("a", "anthropic", True, {"x": 2, "y": "same"}),
    ])
    out = agreement_summary(rows)
    assert out["fields"] == 2
    assert out["agreed"] == 1
    assert out["disagreed"] == 1
    assert out["rate"] == 0.5
