import hashlib
import json
from pathlib import Path

import pytest

from costlab.compare import compare_field, summarise_verdicts

FIXTURE = Path(__file__).resolve().parent.parent / "costlab" / "corpus" / "golden-cases.json"
CASES = json.loads(FIXTURE.read_text())["cases"]


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_golden_case(case):
    """Every case here also runs against the TypeScript comparator this is a
    port of. Neither implementation can change a verdict without failing a test
    the other side runs too — that shared contract is the only thing keeping a
    port from drifting away from the original."""
    assert (
        compare_field(case["extracted"], case["verified"], case["type"])
        == case["expected"]
    )


def test_the_fixture_is_the_one_the_other_repository_ships():
    """A copied fixture that silently diverges is worse than no fixture: both
    suites stay green while the two comparators drift. This hash is recorded in
    both repositories. If it fails, the copies differ — reconcile them, do not
    just update the constant."""
    digest = hashlib.sha256(FIXTURE.read_bytes()).hexdigest()
    assert digest == "9a27801f510b1a4130777cef7a8652abe6f392ba8d09e2fb73ca31509ebfdab1", (
        f"golden-cases.json changed. New hash: {digest}. "
        "Update BOTH repositories, then update this constant."
    )


def test_summarise_excludes_unverified_from_the_denominator():
    """A field with no answer key must not count as a failure. Including it
    would make a provider's score depend on how complete our key is."""
    out = summarise_verdicts(["match", "match", "mismatch", "unverified"])
    assert out == {"matched": 2, "verified": 3}


def test_summarise_of_nothing_is_not_a_division_by_zero_waiting_to_happen():
    assert summarise_verdicts([]) == {"matched": 0, "verified": 0}
    assert summarise_verdicts(["unverified"]) == {"matched": 0, "verified": 0}


def test_ambiguous_slash_date_is_unverified_not_a_mismatch():
    """Python-only case: this is a DELIBERATE, permanent divergence from the
    TypeScript comparator, not a bug to reconcile. It must never move into the
    shared fixture, because the two implementations genuinely disagree here.

    The TypeScript comparator resolves "03/01/2025" against "March 1, 2025" as
    a match — it builds a JS Date via Date.parse, which silently assumes the US
    month/day/year convention for a bare slash date. That is a guess about a
    regional convention this codebase has no way to verify, and the project's
    own spec forbids Date.parse for exactly that reason.

    This Python port refuses the same guess it already refuses for numbers:
    "1.165,10" (a number that could be either "1165.10" or "1.16510"
    depending on which mark is the decimal separator) returns "unverified"
    rather than fabricating a value by picking one reading. A slash date is
    ambiguous the same way, so a slash-shaped string that cannot be resolved to
    a calendar day must not fall through to a plain text mismatch against a
    date the other side DID resolve. "unverified" is the honest verdict: not
    "the provider is wrong" (a mismatch would say that), but "this codebase
    cannot confidently say either way."
    """
    assert (
        compare_field("03/01/2025", {"value": "March 1, 2025"}, "string")
        == "unverified"
    )
    assert (
        compare_field("March 1, 2025", {"value": "03/01/2025"}, "string")
        == "unverified"
    )


def test_unambiguous_slash_date_resolves_normally():
    """Python-only case, alongside the ambiguous one above: a slash date is
    only genuinely ambiguous when BOTH leading components could be a month.
    "20/09/2022" cannot be month-20, so it unambiguously reads as day/month/
    year and must resolve and compare like any other date — a provider that
    answers in ISO against this key value must not be marked unverified.

    This is drawn from three real slash dates in the bundled answer key
    (an invoice's issue date, another invoice's issue date, and a billing
    worksheet's admission date); before this fix all three silently dropped
    out of scoring against a provider that (correctly) answered in ISO."""
    assert (
        compare_field("2022-09-20", {"value": "20/09/2022"}, "string") == "match"
    )
    assert (
        compare_field("20/09/2022", {"value": "2022-09-20"}, "string") == "match"
    )
    assert (
        compare_field("2022-09-21", {"value": "20/09/2022"}, "string") == "mismatch"
    )


def test_both_components_low_slash_date_stays_unverified():
    """"4/1/2026" could be April 1st or January 4th — both components are
    <= 12, so this stays genuinely ambiguous even against an ISO date the
    provider got right by one reading. Do not extend the >12 resolution
    logic to guess a convention here."""
    assert (
        compare_field("2026-01-04", {"value": "4/1/2026"}, "string") == "unverified"
    )


def test_two_unresolvable_slash_dates_against_each_other_stay_unverified():
    """The existing guard above only covers ONE side being an unresolvable
    slash date against a side that DID resolve. When BOTH sides are
    ambiguous slash dates that never resolve -- "1/2/2026" and "4/1/2026",
    every component <= 12 on both -- they used to fall through to the plain
    text comparison and report "mismatch": a confident claim that two
    providers disagree, when the comparator has confirmed nothing about
    either value. That is the same guess this design already refuses for a
    single ambiguous side, just on both sides at once, so the verdict must
    be "unverified" here too, not a text mismatch."""
    assert compare_field("1/2/2026", {"value": "4/1/2026"}, "string") == "unverified"
    assert compare_field("4/1/2026", {"value": "1/2/2026"}, "string") == "unverified"


def test_a_value_identical_to_the_key_matches_even_when_the_form_is_ambiguous():
    """Two bundled answer-key values are printed on their documents in a slash
    form whose day and month cannot be told apart -- happy-tooth-invoice-excel
    .issueDate "4/1/2026" and emergency-dept-billing-worksheet.admissionDate
    "12/04/2016", every leading component <= 12. Before the text-equality
    short-circuit, the both-sided ambiguity guard returned "unverified" for
    them even against a provider that returned the key value VERBATIM, so
    every bundled run printed "2 field(s) the key covers but could not be
    confidently compared" and no provider could ever be scored on either
    field.

    A value cannot be a wrong reading of itself, and saying so guesses no
    regional convention. The key values themselves are not changed: they are
    human-verified as printed."""
    for printed in ("4/1/2026", "12/04/2016"):
        assert compare_field(printed, {"value": printed}, "string") == "match"

    # And a provider that NORMALISES one of them to ISO is still unverified --
    # honest, because nothing here can tell 4 January from 1 April.
    assert (
        compare_field("2026-01-04", {"value": "4/1/2026"}, "string") == "unverified"
    )


def test_the_text_equality_short_circuit_does_not_weaken_the_other_paths():
    """It is placed after the number and boolean branches and before the date
    handling, so it can only ever pre-empt a date path -- and never in a
    direction that hides a real difference.

    Specifically: declining to answer a field the key covers must still be a
    mismatch (the empty/None rule fires before it), a numeric field must still
    be judged numerically, and a boolean must still be judged as a boolean."""
    # "Didn't answer" must not become a match against an empty key value.
    assert compare_field("", {"value": ""}, "string") == "mismatch"
    assert compare_field(None, {"value": ""}, "string") == "mismatch"
    # The number branch still owns numeric fields: identical text is beside
    # the point when the values parse.
    assert compare_field("1.165,10", {"value": "1.165,10"}, "number") == "unverified"
    assert compare_field("345,015", {"value": 345015}, "number") == "match"
    # The boolean branch still owns boolean fields.
    assert compare_field("TRUE", {"value": "true"}, "boolean") == "match"
    assert compare_field("true", {"value": "false"}, "boolean") == "mismatch"
    # A genuinely different pair of ambiguous slash dates stays unverified --
    # the short-circuit only fires on identical text.
    assert compare_field("1/2/2026", {"value": "4/1/2026"}, "string") == "unverified"


def test_the_suite_runs_outside_utc():
    """costlab/compare.py's `_to_ymd` docstring claims "the date tests run
    under a non-UTC TZ precisely to catch a port that forgets this". That was
    false as committed -- there was no conftest.py, no pytest config, no CI and
    no TZ anywhere, so a UTC machine happily stayed green against exactly the
    bug the design exists to prevent. conftest.py now sets Asia/Kolkata
    (UTC+05:30, a half-hour offset, which catches more than a whole-hour one)
    and this test is what keeps the docstring's claim honest.

    A developer running `TZ=UTC pytest` deliberately is respected by
    conftest.py's `setdefault`, so this test skips rather than failing them."""
    import os
    import time

    tz = os.environ.get("TZ")
    if tz == "UTC":
        pytest.skip("TZ=UTC was requested explicitly for this run")
    assert tz, "conftest.py must set a TZ for the suite"
    assert tz != "UTC"
    # Actually in effect, not merely set in the environment.
    assert time.timezone != 0 or time.altzone != 0


# --- A key value the page does not actually print --------------------------
#
# Every answer-key entry carries the `source` line it was read from -- that
# citation is what the word "verified" means in this corpus. One bundled entry
# records a value the page does not print: heavenly-hamburgers-recipe's
# documentTitle is "Heavenly Hamburgers", read from a page printing
# "Heavenly Here's what's cookin': Hamburgers", because the title is interleaved
# with a graphic. That value is a human reconstruction, and no extraction can be
# judged against it -- a model returning what the page literally prints is not
# wrong, and one returning the reconstruction is not right for any reason we can
# evidence.
#
# The key DECLARES this with `"reconstructed": true`. It is never inferred.
# Inferring it -- testing whether the value appears inside its own source -- was
# tried first and is dangerous: it holds only where sources are full verbatim
# quotes, so an abbreviated "Invoice No: ..." or a descriptive "read from the
# header" in a prospect's key would make every string field look reconstructed
# and silently stop being scored.


def test_a_reconstructed_key_value_cannot_be_compared():
    from costlab.compare import compare_field

    entry = {
        "value": "Heavenly Hamburgers",
        "source": "Heavenly Here's what's cookin': Hamburgers",
        "reconstructed": True,
    }
    assert compare_field("Heavenly Hamburgers", entry, "string") == "unverified"
    assert compare_field("From. Lola to", entry, "string") == "unverified"


def test_an_empty_answer_is_also_unjudgeable_against_a_reconstruction():
    """Not "mismatch". If we cannot establish what the right answer was, we
    cannot establish that a blank is the wrong one either."""
    from costlab.compare import compare_field

    entry = {"value": "Heavenly Hamburgers", "source": "...", "reconstructed": True}
    assert compare_field("", entry, "string") == "unverified"


def test_an_unflagged_entry_scores_normally_however_its_source_reads():
    """The guard must NOT be inferred from the source text. An abbreviated
    source is ordinary in a hand-written key and must not remove the field from
    the measurement."""
    from costlab.compare import compare_field

    entry = {"value": "AC-2025-1047", "source": "Invoice No: ..."}
    assert compare_field("AC-2025-1047", entry, "string") == "match"
    assert compare_field("AC-9999", entry, "string") == "mismatch"


def test_the_flag_applies_to_numbers_too():
    """Nothing about the reason is text-specific: a total someone worked out
    from line items rather than read off the page is the same problem."""
    from costlab.compare import compare_field

    entry = {"value": 345015, "source": "sum of line items", "reconstructed": True}
    assert compare_field(345015, entry, "number") == "unverified"


def test_only_one_bundled_key_entry_is_flagged_as_reconstructed():
    """A guard on the corpus itself. A flagged field stops being scored, so a
    future key edit that adds one must be deliberate and visible."""
    from costlab.answers import load_answers
    from costlab.compare import is_reconstruction

    key = load_answers()
    found = [
        f"{doc}.{name}"
        for doc, fields in key.documents.items()
        for name, entry in fields.items()
        if is_reconstruction(entry)
    ]
    assert found == ["heavenly-hamburgers-recipe.documentTitle"], found


def test_the_flagged_entry_explains_itself_in_the_key():
    """The flag removes a field from every provider's score. The key has to say
    why, where the next person to read it will look."""
    from costlab.answers import load_answers

    entry = load_answers().documents["heavenly-hamburgers-recipe"]["documentTitle"]
    assert entry.get("reconstructed") is True
    assert "graphic" in entry.get("reconstructedWhy", "")


# --- A value that names an entity inside a form box ------------------------
#
# bill-of-lading's `consignee` and `shipper` were marked WRONG for all eight
# configurations, and none of them was wrong. The key records the entity's name
# ("EuroHub Logistics Center"); on a bill of lading that field is a printed BOX
# containing the name and its address, and every model returned the whole box.
# Not one returned the bare name.
#
# The key is narrower than the field it names. It is NOT widened, because the
# key's own note promises every value was read off the document by a human and
# never derived from a model's output -- and the only evidence for a fuller value
# here IS model output. So the judgement recorded is about the FIELD, not a new
# ground truth: `"acceptsEnclosingBlock": true` means "returning the box that
# encloses this value is also correct".
#
# Confined to entries a human has blessed, on purpose. Treating containment as a
# match everywhere would have blessed three real errors in the same corpus:
# carrier returning a DIFFERENT field's value appended (TRAILER NO), a
# documentTitle with "Ory]" OCR noise attached, and -- worst -- an invoiceNumber
# where the key reads 616770524 and the model returned 06167705240, a wrong
# identifier that "contains" the right one only as an artifact of digits.


def _boxed(value, source):
    return {"value": value, "source": source, "acceptsEnclosingBlock": True}


def test_the_enclosing_block_is_a_match_when_the_key_allows_it():
    from costlab.compare import compare_field

    entry = _boxed("EuroHub Logistics Center", "CONSIGNEE (TO): EuroHub Logistics Center")
    got = ("EuroHub Logistics Center 45 Terminal Read, Logistics Park Rotterdam, "
           "3008 AB, Netherlands")
    assert compare_field(got, entry, "string") == "match"


def test_the_bare_value_still_matches_when_the_flag_is_set():
    """The flag widens what counts, it must not narrow it -- a model returning
    exactly what the key records cannot become wrong by adding the allowance."""
    from costlab.compare import compare_field

    entry = _boxed("EuroHub Logistics Center", "CONSIGNEE (TO): EuroHub Logistics Center")
    assert compare_field("EuroHub Logistics Center", entry, "string") == "match"


def test_a_different_answer_is_still_a_mismatch_under_the_flag():
    from costlab.compare import compare_field

    entry = _boxed("EuroHub Logistics Center", "CONSIGNEE (TO): EuroHub Logistics Center")
    assert compare_field("Apex Industrial Supply Ltd.", entry, "string") == "mismatch"


def test_containment_is_not_a_match_without_the_flag():
    """The whole safety of this feature. Unflagged entries keep scoring exactly
    as before."""
    from costlab.compare import compare_field

    entry = {"value": "Employment Application", "source": "Employment Application"}
    assert compare_field("Employment Application Ory]", entry, "string") == "mismatch"


def test_a_wrong_identifier_that_contains_the_right_one_stays_a_mismatch():
    """The case that rules out inferring this instead of declaring it: the key
    reads 616770524 and a model returned 06167705240. Containment holds as a
    digit artifact; the number is wrong."""
    from costlab.compare import compare_field

    entry = {"value": "616770524", "source": "Invoice Number 616770524"}
    assert compare_field("06167705240", entry, "string") == "mismatch"


def test_the_flag_is_ignored_for_non_string_fields():
    """An enclosing box is a text idea. A number that contains another number is
    a different number, and 345015 must not match 1345015."""
    from costlab.compare import compare_field

    entry = {"value": 345015, "source": "Amount Due $345,015.00",
             "acceptsEnclosingBlock": True}
    assert compare_field(1345015, entry, "number") == "mismatch"
    assert compare_field(345015, entry, "number") == "match"


def test_only_the_two_bill_of_lading_entries_carry_the_flag():
    """A guard on the corpus. The flag makes a field easier to pass, so adding
    one must be deliberate and visible."""
    from costlab.answers import load_answers

    key = load_answers()
    found = sorted(
        f"{doc}.{name}"
        for doc, fields in key.documents.items()
        for name, entry in fields.items()
        if entry.get("acceptsEnclosingBlock")
    )
    assert found == ["bill-of-lading.consignee", "bill-of-lading.shipper"], found


def test_the_flagged_entries_explain_themselves():
    from costlab.answers import load_answers

    fields = load_answers().documents["bill-of-lading"]
    for name in ("consignee", "shipper"):
        why = fields[name].get("acceptsEnclosingBlockWhy", "")
        assert "box" in why or "address" in why, f"{name}: {why!r}"
