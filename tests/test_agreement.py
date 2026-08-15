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


def test_a_field_only_one_provider_was_asked_about_is_not_a_disagreement():
    """One opinion is not a conflict -- but only when it really is one
    opinion. This test used to assert the bug: it passed `{}` for the second
    provider and expected NO row, which encoded "answered and found nothing"
    as "was never asked". That directly contradicted
    test_exactly_one_absent_value_disagrees below, which says exactly one
    absent value makes a pair disagree, on the identical situation.

    The genuine case is a field the other provider's schema never mentioned:
    `requestedFields` records what each cell was actually asked for, so a
    field outside it is a question nobody put to that provider, not an
    absence. Counting that as a disagreement would inflate the rate with
    fields nobody contested."""
    records = [
        _rec("inv", "bedrock", True, {"total": 345015, "vendor": "Acme"}),
        _rec("inv", "anthropic", True, {"total": 345015}),
    ]
    records[0]["requestedFields"] = ["total", "vendor"]
    records[1]["requestedFields"] = ["total"]
    rows = agreement(records)
    assert [r["field"] for r in rows] == ["total"]
    assert next(r for r in rows if r["field"] == "total")["state"] == "agreed"


def test_a_cell_that_did_not_run_produces_no_row_at_all():
    """`None` is a cell that did not run -- the harness has no answer from it,
    not an answer of "nothing". It must not take part, which leaves one lone
    opinion on the field and therefore no row."""
    rows = agreement([
        _rec("inv", "bedrock", True, {"total": 345015}),
        _rec("inv", "anthropic", True, None),
    ])
    assert [r["field"] for r in rows] == []


def test_a_provider_that_answered_nothing_disagrees_rather_than_vanishing():
    """`{}` is a provider that ANSWERED and found nothing, and that is a real
    difference from a provider that found a value -- the same case
    test_exactly_one_absent_value_disagrees pins with an explicit None.

    Before the fix, `if not extracted: continue` collapsed `{}` into "did not
    run", so with two providers the field disappeared from the report
    entirely, and with three providers it inverted the headline: measured on
    the branch, a third provider returning {"total": None, "date": None} gave
    agreed 0 / disagreed 2 / rate 0.0, while the SAME provider returning {}
    gave agreed 2 / disagreed 0 / rate 1.0. Same reality, opposite headline.
    It is reachable in ordinary use: neither half of a cell forces every
    requested key to come back."""
    rows = agreement([
        _rec("inv", "bedrock", True, {"total": 345015}),
        _rec("inv", "anthropic", True, {}),
    ])
    row = next(r for r in rows if r["field"] == "total")
    assert row["state"] == "disagreed"
    assert row["values"] == {"bedrock:sdk": 345015, "anthropic:sdk": None}
    assert row["distinct"] == 2

    # And the three-provider headline is the same whichever way the silent
    # provider expresses its silence -- an omitted key and an explicit null
    # are the same non-answer.
    def _summary(third):
        return agreement_summary(agreement([
            _rec("inv", "a", True, {"total": 100, "date": "2026-01-04"}),
            _rec("inv", "b", True, {"total": 100, "date": "2026-01-04"}),
            _rec("inv", "c", True, third),
        ]))

    assert _summary({"total": None, "date": None}) == _summary({})
    assert _summary({})["disagreed"] == 2
    assert _summary({})["agreed"] == 0


def test_a_provider_that_omits_one_key_still_contributes_an_absence():
    """Row membership must not be the union of keys providers HAPPENED to
    emit. A provider that returned `total` but left `vendor` out has not
    withdrawn from the vendor row -- it answered nothing there, which is a
    difference worth showing."""
    rows = agreement([
        _rec("inv", "bedrock", True, {"total": 100, "vendor": "Acme"}),
        _rec("inv", "anthropic", True, {"total": 100}),
    ])
    by_field = {r["field"]: r for r in rows}
    assert sorted(by_field) == ["total", "vendor"]
    assert by_field["total"]["state"] == "agreed"
    assert by_field["vendor"]["state"] == "disagreed"
    assert by_field["vendor"]["values"] == {
        "bedrock:sdk": "Acme", "anthropic:sdk": None
    }


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


def test_every_bucket_reconciles_to_the_total_field_count():
    """`fields` is the total row count, so the four buckets must add back up to
    it exactly -- a report showing fields, agreed, disagreed, ambiguous and
    unanswered side by side must always reconcile, with no row silently
    uncounted or double-counted. Two of those buckets are excluded from the
    rate, so the identity is what lets a reader see how much was excluded
    rather than having to infer it."""
    rows = agreement([
        _rec("inv", "bedrock", True, {
            "total": 345015, "vendor": "same", "issueDate": "4/1/2026",
            "poNumber": None,
        }),
        _rec("inv", "anthropic", True, {
            "total": 999, "vendor": "same", "issueDate": "2026-01-04",
            "poNumber": "",
        }),
    ])
    summary = agreement_summary(rows)
    assert summary["fields"] == 4
    assert summary["agreed"] == 1        # vendor
    assert summary["disagreed"] == 1     # total
    assert summary["ambiguous"] == 1     # issueDate, two unresolvable readings
    assert summary["unanswered"] == 1    # poNumber, nobody answered
    assert (
        summary["agreed"]
        + summary["disagreed"]
        + summary["ambiguous"]
        + summary["unanswered"]
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


def test_absence_agreement_is_order_independent():
    """compare_field is asymmetric in its two operands by design: it opens
    with `if extracted is None or extracted == "": return "mismatch"`, which
    inspects only the first argument. That rule is correct for scoring
    against a ground-truth key, but agreement() casts one PEER into the
    "verified" role that asymmetry depends on, and which peer plays that
    role used to be nothing but insertion order. Concretely,
    compare_field(".", {"value": ""}, "string") is "match" (both normalise
    to "") but compare_field("", {"value": "."}, "string") is "mismatch" (the
    extracted-side check fires first) -- so the exact same pair of records,
    listed in the opposite order, used to flip between "agreed" and
    "disagreed". For every pair below, the state must be identical with the
    records in both insertion orders."""
    pairs = [
        ("", "."),
        (None, "x"),
        ("", ""),
        (None, None),
        (100, "$100.00"),
        (345015, "$345,015.00"),
    ]
    for value_a, value_b in pairs:
        records = [
            _rec("inv", "bedrock", True, {"total": value_a}),
            _rec("inv", "anthropic", True, {"total": value_b}),
        ]
        forward = next(
            r for r in agreement(records) if r["field"] == "total"
        )["state"]
        backward = next(
            r for r in agreement(list(reversed(records))) if r["field"] == "total"
        )["state"]
        assert forward == backward, (value_a, value_b, forward, backward)


def test_a_field_no_provider_answered_is_unanswered_not_agreed():
    """Two providers that both found nothing have not DISAGREED -- but they
    have not agreed about an answer either, because there is no answer. None,
    "", and "." are the same non-answer wearing different clothes
    (_normalise_text(".") is ""), so every pair of them is one distinct
    non-answer; the row's state is "unanswered", and it stays out of the
    agreement rate entirely.

    Counting these as agreements inflated the headline badly: four requested
    fields where the providers differed on one and nobody answered the other
    three reported "Agreement: 3/4 fields (75%)", three quarters of it from
    comparisons never made. The error ran AGAINST the case this tool exists to
    make, which is exactly why it survived a whole-branch review -- an
    overstatement in the flattering direction gets challenged.
    """
    absent_pairs = [
        (None, None), ("", ""), (".", "."),
        (None, ""), ("", "."), (None, "."),
    ]
    for absent_a, absent_b in absent_pairs:
        rows = agreement([
            _rec("inv", "bedrock", True, {"total": absent_a}),
            _rec("inv", "anthropic", True, {"total": absent_b}),
        ])
        row = next(r for r in rows if r["field"] == "total")
        assert row["state"] == "unanswered", (absent_a, absent_b)
        assert row["distinct"] == 1, (absent_a, absent_b)
        summary = agreement_summary(rows)
        assert summary["unanswered"] == 1, (absent_a, absent_b)
        assert summary["agreed"] == 0, (absent_a, absent_b)
        # Nothing was judged, so there is no rate to report.
        assert summary["rate"] is None, (absent_a, absent_b)


def test_unanswered_fields_do_not_inflate_the_agreement_rate():
    """The exact shape that produced the fabricated headline: several fields
    requested, the providers differ on one, and no provider answers the rest.
    The rate must describe only the fields that were actually judged."""
    requested = ["invoiceNumber", "issueDate", "vendorName", "totalAmount"]
    rows = agreement([
        {**_rec("inv", "bedrock", True, {"totalAmount": 100}),
         "requestedFields": requested},
        {**_rec("inv", "anthropic", True, {"totalAmount": 999}),
         "requestedFields": requested},
    ])
    summary = agreement_summary(rows)
    assert summary["fields"] == 4
    assert summary["unanswered"] == 3
    assert summary["agreed"] == 0
    assert summary["disagreed"] == 1
    # Was 0.75 before this fix, from three comparisons that never happened.
    assert summary["rate"] == 0.0


def test_exactly_one_absent_value_disagrees():
    """One provider found a value and the other did not -- that is a real
    difference a prospect should see, and it must disagree regardless of
    which side is the one that found nothing."""
    present_and_absent = [("x", None), ("x", ""), ("x", ".")]
    for present, absent in present_and_absent:
        rows = agreement([
            _rec("inv", "bedrock", True, {"total": present}),
            _rec("inv", "anthropic", True, {"total": absent}),
        ])
        row = next(r for r in rows if r["field"] == "total")
        assert row["state"] == "disagreed", (present, absent)

        rows_reversed = agreement([
            _rec("inv", "bedrock", True, {"total": absent}),
            _rec("inv", "anthropic", True, {"total": present}),
        ])
        row_reversed = next(r for r in rows_reversed if r["field"] == "total")
        assert row_reversed["state"] == "disagreed", (absent, present)


def test_distinct_of_one_never_implies_disagreement():
    """The invariant this whole round of fixes exists to guarantee: across a
    table of representative rows, distinct == 1 must never coincide with
    state == "disagreed". If every provider's answer normalises to the same
    thing -- including "no answer" -- there is nothing left to disagree
    about. Checked across a table, not one example, because three prior
    rounds were each defeated by a test that only covered one shape of
    input."""
    value_sets = [
        [None, None],
        ["", ""],
        [".", "."],
        [None, "", "."],
        [100, "$100.00"],
        [345015, "$345,015.00", 345015.0],
        ["same", "same", "same"],
        # Two identical ambiguous slash dates. compare_field's both-sided
        # slash-date guard used to return "unverified" here even though the
        # raw text was identical, landing the row on "ambiguous"; the
        # text-equality short-circuit added ahead of that guard now returns
        # "match", so this lands on "agreed". Either way the invariant under
        # test holds -- neither is "disagreed" -- and "agreed" is the more
        # honest of the two: a value cannot be a wrong reading of itself.
        ["4/1/2026", "4/1/2026"],
    ]
    for values in value_sets:
        records = [
            _rec("inv", f"provider{i}", True, {"total": v})
            for i, v in enumerate(values)
        ]
        rows = agreement(records)
        row = next(r for r in rows if r["field"] == "total")
        if row["distinct"] == 1:
            assert row["state"] != "disagreed", values


def test_an_absent_cell_does_not_change_how_present_cells_compare_to_each_other():
    """The row's numeric type used to be inferred from EVERY value,
    including absent ones, and _looks_numeric(None) is False, so one
    provider returning nothing demoted the whole row to a text comparison:
    {100, "$100.00"} agreed with distinct=1, but {100, "$100.00", None} fell
    back to a text comparison between 100 and "$100.00" and disagreed with
    distinct=3 -- two providers who plainly agree, reported as disagreeing
    WITH EACH OTHER, because a third provider found nothing.

    Once any cell is absent the row correctly reports "disagreed" either
    way (one provider did not answer -- a real difference), so `state`
    alone cannot show whether the present pair was itself corrupted by the
    type flip. `distinct` can: it must stay 2 -- one present answer plus one
    absence -- never 3, whenever an absent cell is added to a pair of
    present values that the comparator recognises as the same answer.
    A `distinct` of 3 here would mean the present pair stopped agreeing
    with itself the moment a peer went silent, which is exactly the bug
    this test pins."""
    agreeing_present_pairs = [
        (100, "$100.00"),
        ("x", "x"),
    ]
    for pair in agreeing_present_pairs:
        baseline_rows = agreement([
            _rec("inv", "p0", True, {"total": pair[0]}),
            _rec("inv", "p1", True, {"total": pair[1]}),
        ])
        baseline = next(r for r in baseline_rows if r["field"] == "total")
        assert baseline["state"] == "agreed", pair
        assert baseline["distinct"] == 1, pair  # sanity check on the pair itself

        for absent in (None, ""):
            rows = agreement([
                _rec("inv", "p0", True, {"total": pair[0]}),
                _rec("inv", "p1", True, {"total": pair[1]}),
                _rec("inv", "p2", True, {"total": absent}),
            ])
            row = next(r for r in rows if r["field"] == "total")
            # Correctly disagrees now -- one provider did not answer -- but
            # for the honest reason, not a fabricated mismatch between the
            # present pair:
            assert row["state"] == "disagreed", (pair, absent)
            assert row["distinct"] == 2, (pair, absent)


def test_distinct_counts_one_absence_regardless_of_how_many_cells_are_absent():
    """{100, "$100.00", None, None} has two distinct answers -- one numeric
    amount and one absence -- not three or four. Every absent cell must
    collapse into the same single counted absence no matter how many
    providers returned nothing."""
    rows = agreement([
        _rec("inv", "bedrock", True, {"total": 100}),
        _rec("inv", "anthropic", True, {"total": "$100.00"}),
        _rec("inv", "zed", True, {"total": None}),
        _rec("inv", "yed", True, {"total": None}),
    ])
    row = next(r for r in rows if r["field"] == "total")
    assert row["distinct"] == 2


def test_one_absent_cell_among_agreeing_present_values_is_a_coherent_disagreement():
    """Pinning the coordinator's worked example directly: {100, "$100.00",
    None} must type-infer as "number" from the two present values, compare
    100 against "$100.00" as a match, disagree overall (one provider did not
    answer -- a real difference), and count two distinct answers (one
    amount, one absence) rather than three."""
    rows = agreement([
        _rec("inv", "bedrock", True, {"total": 100}),
        _rec("inv", "anthropic", True, {"total": "$100.00"}),
        _rec("inv", "zed", True, {"total": None}),
    ])
    row = next(r for r in rows if r["field"] == "total")
    assert row["state"] == "disagreed"
    assert row["distinct"] == 2
