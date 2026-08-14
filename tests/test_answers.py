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


def test_a_supplied_key_is_read_from_a_path():
    ...  # completed in Task 7, where --answers lands
