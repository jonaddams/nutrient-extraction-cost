"""The absent marker is part of `agreement`'s public surface.

`render_html` decides whether a cell renders as an em dash, and it was reaching
into `agreement._ABSENT` — another module's private name — four times to do it.
That is the kind of coupling that silently breaks the next time the comparator is
refactored, and the renderer's em dash is not a cosmetic detail: it is the
difference between "this provider answered nothing" and "this provider answered
something we are not showing you".

Two names, one concept, and both are needed. `ABSENT` is the marker itself,
required as a lookup default so that a provider/half missing from a row compares
EQUAL to one that answered nothing — both mean "no answer", and defaulting to
anything else would render two absences as a disagreement. `is_absent` is the
predicate, so no caller has to know the marker is a singleton compared by
identity.
"""

from costlab import agreement


def test_the_marker_is_public():
    assert hasattr(agreement, "ABSENT")


def test_is_absent_recognises_the_marker():
    assert agreement.is_absent(agreement.ABSENT) is True


def test_a_real_answer_is_not_absent():
    for value in ("Acme Corp.", "0", 0, 0.0, "—", False):
        assert agreement.is_absent(value) is False, value


def test_zero_is_an_answer_not_an_absence():
    """Explicitly, because a falsy check instead of an identity check would call
    a real extracted 0 "no answer" and render it as an em dash — turning a
    measured value into a blank."""
    assert agreement.is_absent(0) is False
    assert agreement.is_absent(0.0) is False


def test_every_form_of_absence_normalises_to_the_marker():
    """None, empty string and a punctuation placeholder are one answer, not
    three — the property `distinct` is counted with."""
    normalised = agreement.normalise_values(
        {"a:direct": None, "b:direct": "", "c:direct": "."}
    )
    assert all(agreement.is_absent(v) for v in normalised.values())


def test_two_absent_cells_read_as_the_same_answer():
    """The property the renderer depends on: two absences must compare equal, or
    the page accuses two providers of disagreeing when neither answered."""
    normalised = agreement.normalise_values({"a:direct": None, "a:sdk": ""})
    assert normalised["a:direct"] == normalised["a:sdk"]


def test_a_missing_cell_defaults_to_absent_and_still_compares_equal():
    """A provider/half absent from the row entirely is also "no answer", so it
    has to compare equal to one that answered nothing. This is why the marker
    itself is public and not only the predicate."""
    normalised = agreement.normalise_values({"a:direct": ""})
    missing = normalised.get("a:sdk", agreement.ABSENT)
    assert agreement.is_absent(missing)
    assert missing == normalised["a:direct"]


def test_the_renderer_does_not_reach_into_agreement_s_privates():
    """The regression guard for this whole change. Asserted against the source
    because the coupling is a source-level fact: an attribute access that only
    happens on one branch would not show up in any render."""
    from pathlib import Path

    source = Path(agreement.__file__).parent / "render_html.py"
    text = source.read_text()
    assert "agreement._" not in text, (
        "render_html is using a private name from agreement"
    )
