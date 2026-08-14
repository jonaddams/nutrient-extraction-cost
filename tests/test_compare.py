import hashlib
import json
from pathlib import Path

import pytest

from costlab.compare import compare_field, summarise_verdicts

FIXTURE = Path(__file__).resolve().parent.parent / "costlab" / "corpus" / "golden-cases.json"
CASES = json.loads(FIXTURE.read_text())["cases"]


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_golden_case(case):
    """Every case here also runs against the TypeScript comparator in the
    extraction studio. Neither implementation can change a verdict without
    failing a test the other side runs too — that shared contract is the only
    thing keeping a port from drifting away from the original."""
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
    assert digest == "01c5bd9ebdacf9f867f7f704ee1a4f086be603eb34dabdb9b556d04cd7c1997c", (
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
