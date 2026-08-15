import json

import pytest

from costlab.answers import field_type, load_answers, schema_for


def test_the_bundled_key_covers_the_corpus_and_is_dated():
    key = load_answers()
    assert key.checked_on
    assert len(key.documents) == 17


def test_every_bundled_value_carries_its_source_line():
    """`source` is the evidence behind the word "verified". A value with no
    source is a guess wearing a key's clothes, and the next session cannot tell
    the two apart."""
    key = load_answers()
    for doc_id, fields in key.documents.items():
        for name, entry in fields.items():
            assert entry.get("source"), f"{doc_id}.{name} has no source"


def test_the_two_deliberately_ungraded_fields_stay_out_of_the_key():
    """These are excluded for DIFFERENT reasons — one is genuinely ambiguous on
    the page, the other was redacted out of the document. Either way, adding
    them silently changes every published score."""
    key = load_answers()
    assert "invoiceNumber" not in key.documents["scanned-invoice"]
    assert "recordId" not in key.documents["emergency-dept-billing-worksheet"]


def test_schema_for_covers_exactly_the_keys_fields():
    key = load_answers()
    schema = schema_for(key, "northgate-claim-file")
    assert set(schema["properties"]) == set(key.documents["northgate-claim-file"])
    assert schema["additionalProperties"] is False
    assert sorted(schema["required"]) == sorted(schema["properties"])


def test_schema_for_an_unknown_document_is_none_not_an_empty_schema():
    """An empty schema would extract nothing and score every field as a
    mismatch."""
    assert schema_for(load_answers(), "no-such-document") is None


@pytest.mark.parametrize(
    "value,expected",
    [(345015, "number"), (48215.6, "number"), ("AC-2025-1047", "string"),
     ("March 1, 2025", "string"), (True, "string")],
)
def test_field_type_maps_a_key_value_to_a_comparator_type(value, expected):
    assert field_type(value) == expected


def test_a_supplied_key_is_read_from_a_path(tmp_path):
    """`--answers key.json` reads that file instead of the bundled key, and
    nothing of the bundled key leaks into it. This body was a bare `...` --
    a test that asserted nothing while still being counted in the suite, so
    the JSON half of `--answers` (which landed in Task 7) had no coverage at
    all while appearing to have some."""
    p = tmp_path / "key.json"
    p.write_text(json.dumps({
        "checkedOn": "2026-08-14",
        "note": "supplied by a prospect",
        "documents": {
            "inv": {
                "invoiceNumber": {"value": "AC-2025-1047", "source": "Invoice No"},
                "totalAmount": {"value": 345015, "source": "Amount Due"},
            }
        },
    }))

    key = load_answers(p)
    assert key.checked_on == "2026-08-14"
    assert key.note == "supplied by a prospect"
    assert set(key.documents) == {"inv"}
    assert key.documents["inv"]["totalAmount"]["value"] == 345015
    # The bundled corpus must not bleed through a supplied key.
    assert key.fields_for("lumen-invoice") == {}
    # And a supplied key drives the derived schema the same way the bundled
    # one does.
    assert set(schema_for(key, "inv")["properties"]) == {
        "invoiceNumber", "totalAmount"
    }


def test_a_supplied_csv_key_is_read(tmp_path):
    """A prospect with a spreadsheet of known values should not have to author
    JSON to use this."""
    p = tmp_path / "key.csv"
    p.write_text(
        "docId,field,value,source\n"
        "inv,invoiceNumber,AC-2025-1047,Invoice No: AC-2025-1047\n"
        "inv,totalAmount,345015,Amount Due\n"
    )
    from costlab.answers import load_answers_csv

    key = load_answers_csv(p)
    assert key.documents["inv"]["invoiceNumber"]["value"] == "AC-2025-1047"
    # Numeric-looking values become numbers so they compare with tolerance
    # rather than as text.
    assert key.documents["inv"]["totalAmount"]["value"] == 345015


def test_a_csv_missing_required_columns_fails_loudly(tmp_path):
    """Silently reading zero rows would report every provider as unscoreable and
    look like a model problem."""
    p = tmp_path / "bad.csv"
    p.write_text("document,field\ninv,invoiceNumber\n")
    from costlab.answers import load_answers_csv

    with pytest.raises(ValueError, match="docId"):
        load_answers_csv(p)


def test_a_header_only_csv_reports_the_empty_data_problem_not_missing_columns(tmp_path):
    """A CSV with a valid header and zero data rows previously computed
    `present` from the first data ROW, so it had none to read and reported
    "missing required column(s): docId, field, value. Found: nothing" -- a
    message that sends a prospect to rename columns that are already
    correct. The header IS valid here; the actual, fixable problem is that
    there is no data below it, and the error must say that instead.
    """
    p = tmp_path / "empty.csv"
    p.write_text("docId,field,value,source\n")
    from costlab.answers import load_answers_csv

    with pytest.raises(ValueError, match="no data rows"):
        load_answers_csv(p)
