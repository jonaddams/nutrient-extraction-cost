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
