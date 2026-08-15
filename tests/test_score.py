from costlab.answers import AnswerKey
from costlab.score import score_records, score_summary


def _key():
    return AnswerKey(
        checked_on="2026-08-14",
        documents={
            "inv": {
                "invoiceNumber": {"value": "AC-2025-1047", "source": "Invoice No: ..."},
                "totalAmount": {"value": 345015, "source": "Amount Due ..."},
            }
        },
    )


def _rec(doc, pid, with_nutrient, extracted):
    return {
        "docId": doc, "providerId": pid, "withNutrient": with_nutrient,
        "extracted": extracted, "usage": {"inputTokens": 1, "outputTokens": 1,
                                          "cachedInputTokens": 0},
        "status": 200,
    }


def test_a_perfect_cell_scores_every_field():
    out = score_records(
        [_rec("inv", "bedrock", True,
              {"invoiceNumber": "AC-2025-1047", "totalAmount": "$345,015.00"})],
        _key(),
    )
    assert out[0]["score"]["matched"] == 2
    assert out[0]["score"]["verified"] == 2


def test_a_field_the_key_does_not_cover_is_not_scored_against_the_provider():
    """Extracting something the key says nothing about is neither right nor
    wrong. Counting it either way makes a provider's score depend on how
    complete our key is."""
    out = score_records(
        [_rec("inv", "bedrock", True,
              {"invoiceNumber": "AC-2025-1047", "totalAmount": 345015,
               "vendorName": "Anything At All"})],
        _key(),
    )
    assert out[0]["score"]["verified"] == 2
    assert "vendorName" not in out[0]["score"]["verdicts"]


def test_a_missing_field_that_the_key_covers_is_a_mismatch():
    """"Didn't answer" and "answered wrong" both mean a human still has to go
    and check, so declining to answer must not improve a score."""
    out = score_records(
        [_rec("inv", "bedrock", True, {"invoiceNumber": "AC-2025-1047"})], _key()
    )
    assert out[0]["score"]["verdicts"]["totalAmount"] == "mismatch"
    assert out[0]["score"]["matched"] == 1
    assert out[0]["score"]["verified"] == 2


def test_a_cell_that_extracted_nothing_is_unscoreable_not_zero():
    """None means the harness could not read the answer. Scoring it as 0/2
    would publish a claim about the provider that the run cannot support."""
    out = score_records([_rec("inv", "bedrock", False, None)], _key())
    assert out[0]["score"] is None


def test_a_document_absent_from_the_key_is_unscoreable():
    out = score_records([_rec("other", "bedrock", True, {"x": 1})], _key())
    assert out[0]["score"] is None


def test_summary_reports_no_accuracy_rather_than_zero_when_nothing_scored():
    out = score_summary(score_records([_rec("inv", "bedrock", True, None)], _key()))
    row = out[0]
    assert row["accuracy"] is None
    assert row["unscoreable"] == 1


def test_summary_separates_the_two_halves_of_each_provider():
    """The question a prospect is asking is whether the SDK's grounding buys
    accuracy, so the two halves must never be averaged together."""
    recs = [
        _rec("inv", "bedrock", True, {"invoiceNumber": "AC-2025-1047", "totalAmount": 345015}),
        _rec("inv", "bedrock", False, {"invoiceNumber": "WRONG", "totalAmount": 345015}),
    ]
    rows = {r["withNutrient"]: r for r in score_summary(score_records(recs, _key()))}
    assert rows[True]["accuracy"] == 1.0
    assert rows[False]["accuracy"] == 0.5


def test_an_empty_extraction_is_scored_not_treated_as_unscoreable():
    """A provider that answers and finds nothing returns {}, not None. That
    must be SCORED — every key-covered field becomes a mismatch — not treated
    as unscoreable. score_records' gate is `extracted is None`, an identity
    check that {} does not satisfy, so this is already correct. But nothing
    else in the suite pins that gate: a future change to `if not fields or not
    extracted:` would treat {} as falsy too, silently undoing a Critical fix
    from an earlier task, and a provider that declines by returning {} would
    escape scoring entirely and look more reliable than one that guessed and
    got it wrong. This test exists to catch exactly that regression."""
    out = score_records([_rec("inv", "bedrock", True, {})], _key())
    assert out[0]["score"] is not None
    assert out[0]["score"]["verdicts"]["invoiceNumber"] == "mismatch"
    assert out[0]["score"]["verdicts"]["totalAmount"] == "mismatch"
    assert out[0]["score"]["matched"] == 0
    assert out[0]["score"]["verified"] == 2


def test_summary_counts_unverified_fields_separately_from_unscoreable_records():
    """`unscoreable` counts whole records the harness could not read at all (or
    the key has no document entry for); `unverifiedFields` counts individual
    fields within a SCOREABLE record that the key DOES cover but whose
    comparison could not be made confidently -- an ambiguous date format, a
    number that will not parse. `score_records` only ever builds a verdict for
    a field the key has an entry for, so a field the key does not cover can
    never reach this count; the first half of this test asserts exactly that
    (a record extracting a field outside the key shows unverifiedFields == 0).
    The old wording here said the opposite, "fields the key does not cover" --
    the exact phrasing an earlier commit existed to correct in score.py and
    report.py, left behind here where it then contradicted the assertion
    below it."""
    key = AnswerKey(
        checked_on="2026-08-14",
        documents={"inv": {"invoiceNumber": {"value": "AC-2025-1047", "source": "..."}}},
    )
    out = score_summary(
        score_records(
            [_rec("inv", "bedrock", True,
                  {"invoiceNumber": "AC-2025-1047", "totalAmount": 345015})],
            key,
        )
    )
    row = out[0]
    assert row["unscoreable"] == 0
    assert row["unverifiedFields"] == 0

    # A genuinely unverified FIELD (as opposed to an unscoreable RECORD) comes
    # from compare_field's own ambiguous cases, e.g. an unparseable number
    # against a numeric key value.
    numeric_key = AnswerKey(
        checked_on="2026-08-14",
        documents={"inv": {"totalAmount": {"value": 345015, "source": "..."}}},
    )
    out2 = score_summary(
        score_records(
            [_rec("inv", "bedrock", True, {"totalAmount": "not a number"})],
            numeric_key,
        )
    )
    row2 = out2[0]
    assert row2["unscoreable"] == 0
    assert row2["unverifiedFields"] == 1
    assert row2["verified"] == 0
    assert row2["accuracy"] is None
