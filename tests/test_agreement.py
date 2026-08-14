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


def test_a_pair_the_comparator_cannot_judge_is_ambiguous_not_agreed():
    """"4/1/2026" against "2026-01-04" is a real case, not a contrived one:
    compare_field refuses to guess a date convention and returns "unverified"
    in both directions. Before this fix, the row silently became "agreed",
    reporting 100% agreement from a comparison that was never made -- a
    fabricated claim in a prospect-facing artifact that also understates
    disagreement, cutting against the case this tool exists to make. The row
    must be "ambiguous", not "agreed", and must not show up in a report's
    disagreement list either."""
    rows = agreement([
        _rec("inv", "bedrock", True, {"issueDate": "4/1/2026"}),
        _rec("inv", "anthropic", True, {"issueDate": "2026-01-04"}),
    ])
    row = next(r for r in rows if r["field"] == "issueDate")
    assert row["state"] == "ambiguous"
    assert row["agree"] is False
    # Would show up in a prospect-facing disagreement list if this were
    # miscounted as "disagreed" instead of "ambiguous".
    assert [r for r in rows if r["state"] == "disagreed"] == []

    summary = agreement_summary(rows)
    assert summary["ambiguous"] == 1
    assert summary["agreed"] == 0
    assert summary["disagreed"] == 0
    # Excluded from the rate's denominator entirely -- not folded into either
    # side, and not reported as a disagreement a prospect would see.
    assert summary["rate"] is None


def test_a_summary_of_only_ambiguous_rows_reports_no_rate():
    """Neither 0.0 (which would claim total disagreement) nor 1.0 (which
    would claim total agreement) is honest here: nothing was actually
    judged, so the rate must be None, consistent with every other "nothing
    comparable" case in this codebase."""
    rows = agreement([
        _rec("inv", "bedrock", True, {"issueDate": "4/1/2026"}),
        _rec("inv", "anthropic", True, {"issueDate": "2026-01-04"}),
    ])
    summary = agreement_summary(rows)
    assert summary["rate"] is None


def test_agreed_disagreed_and_ambiguous_reconcile_to_the_total_field_count():
    """`fields` is the total row count, so the three buckets must add back up
    to it exactly -- a report that shows fields, agreed, disagreed and
    ambiguous side by side must always reconcile, with no row silently
    uncounted or double-counted."""
    rows = agreement([
        _rec("inv", "bedrock", True, {
            "total": 345015, "vendor": "same", "issueDate": "4/1/2026",
        }),
        _rec("inv", "anthropic", True, {
            "total": 999, "vendor": "same", "issueDate": "2026-01-04",
        }),
    ])
    summary = agreement_summary(rows)
    assert summary["fields"] == 3
    assert (
        summary["agreed"] + summary["disagreed"] + summary["ambiguous"]
        == summary["fields"]
    )
