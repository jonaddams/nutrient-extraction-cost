from costlab.agreement import agreement, agreement_summary


def _rec(doc, pid, with_nutrient, extracted):
    return {"docId": doc, "providerId": pid, "withNutrient": with_nutrient,
            "extracted": extracted}


def test_providers_that_agree_are_marked_agreed():
    """Deliberately the "unlucky" arrangement: "anthropic" sorts before
    "bedrock" and holds the STRING value here. Under the old
    field_type(reference)-from-one-arbitrary-member logic, that made the row
    compare as text and falsely disagree. It must agree regardless of which
    provider happens to hold which value -- see
    test_agreement_state_does_not_depend_on_which_provider_holds_which_value
    for the property pinned directly."""
    rows = agreement([
        _rec("inv", "anthropic", True, {"total": "$345,015.00"}),
        _rec("inv", "bedrock", True, {"total": 345015}),
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


def test_agreement_state_does_not_depend_on_which_provider_holds_which_value():
    """The comparison type must be decided from the whole row, not from
    whichever provider label happens to sort first alphabetically. Before
    this fix, the same two values -- 345015 and "$345,015.00" -- agreed or
    disagreed depending only on which provider's name sorted first and which
    value that provider happened to hold: field_type(reference) used
    whichever value belonged to the alphabetically-first label, so a number
    held by the first-sorting provider gave a numeric (agreeing) comparison,
    while a string held by the first-sorting provider gave a textual
    (falsely disagreeing) one. A prospect renaming their own providers must
    never change what a report says about an identical extraction, so this
    pins the property directly rather than relying on one lucky example."""

    def _state(pid_a, value_a, pid_b, value_b):
        rows = agreement([
            _rec("inv", pid_a, True, {"total": value_a}),
            _rec("inv", pid_b, True, {"total": value_b}),
        ])
        return next(r for r in rows if r["field"] == "total")["state"]

    # "alpha" sorts before "zulu" in both calls, so swapping which one holds
    # the number vs. the formatted string exercises exactly the alphabetical
    # tie-break the old code used to decide the comparison type.
    assert _state("alpha", 345015, "zulu", "$345,015.00") == "agreed"
    assert _state("alpha", "$345,015.00", "zulu", 345015) == "agreed"


def test_a_row_where_only_some_values_parse_as_numbers_falls_back_to_string():
    """When one side cannot be read as a number at all -- not merely
    formatted differently -- guessing a shared numeric type would be
    fabricating agreement neither side actually offered. Falling back to a
    text comparison is the honest answer; it is fine that the fallback
    correctly disagrees here, since 100 and "unknown" really are different
    answers."""
    rows = agreement([
        _rec("inv", "bedrock", True, {"total": 100}),
        _rec("inv", "anthropic", True, {"total": "unknown"}),
    ])
    row = next(r for r in rows if r["field"] == "total")
    assert row["state"] == "disagreed"


def test_three_cell_state_does_not_depend_on_provider_naming_order():
    """compare_field's numeric match is a TOLERANCE, so equality here is not
    transitive: 100.008 is within tolerance of both 100.0 and 100.016, but
    100.0 and 100.016 are 0.016 apart -- over tolerance. A star topology that
    compares every cell only against whichever provider's name happens to
    sort first therefore used to report a different verdict purely from
    naming: with the alphabetically-first provider holding 100.008 as the
    reference, both other values read as "close enough" (agreed); with the
    alphabetically-first provider holding 100.0 instead, the reference vs.
    100.016 exceeds tolerance (disagreed) -- same three values, opposite
    verdicts. All-pairs comparison always checks 100.0 against 100.016
    directly, regardless of which provider holds which value or how many
    ways the three are named and ordered, so the row must disagree in every
    arrangement below."""
    triple = [100.008, 100.0, 100.016]
    orderings = [
        [("alpha", triple[0]), ("beta", triple[1]), ("gamma", triple[2])],
        [("aaa", triple[1]), ("bbb", triple[0]), ("ccc", triple[2])],
        [("zzz", triple[2]), ("mmm", triple[0]), ("aaa", triple[1])],
        [("bedrock", triple[2]), ("anthropic", triple[1]), ("zed", triple[0])],
    ]
    states = set()
    for arrangement in orderings:
        rows = agreement([
            _rec("inv", pid, True, {"total": value}) for pid, value in arrangement
        ])
        row = next(r for r in rows if r["field"] == "total")
        states.add(row["state"])
    assert states == {"disagreed"}


def test_distinct_counts_unique_answers_not_mismatches_against_a_reference():
    """{100, 200, 200} has two distinct answers, not three. The old
    `1 + count(mismatches against an arbitrary reference)` formula would
    report 3 here (both other cells mismatch the reference), fabricating a
    third answer nobody gave -- overstating disagreement in exactly the
    direction this tool must not overstate it. `distinct` must equal the
    number of unique normalised values in the row."""
    rows = agreement([
        _rec("inv", "bedrock", True, {"total": 100}),
        _rec("inv", "anthropic", True, {"total": 200}),
        _rec("inv", "zed", True, {"total": 200}),
    ])
    row = next(r for r in rows if r["field"] == "total")
    assert row["distinct"] == 2


def test_two_unresolvable_slash_dates_are_ambiguous_at_the_agreement_level():
    """"1/2/2026" and "4/1/2026" are both ambiguous slash dates that never
    resolve to a calendar day (every component is <= 12 on both sides).
    compare_field now returns "unverified" for this pair (fixed in
    costlab/compare.py alongside this change), and agreement() must
    therefore report the row as "ambiguous", not "disagreed" -- two
    providers must not be shown to a prospect as disagreeing on a
    comparison the comparator confirmed nothing about."""
    rows = agreement([
        _rec("inv", "bedrock", True, {"issueDate": "1/2/2026"}),
        _rec("inv", "anthropic", True, {"issueDate": "4/1/2026"}),
    ])
    row = next(r for r in rows if r["field"] == "issueDate")
    assert row["state"] == "ambiguous"
