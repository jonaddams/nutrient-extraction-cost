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
    assert digest == "1fde4d15792a4afc7338888948b5608793f328957b4454bc26723b9aef9cb292", (
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
