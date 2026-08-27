"""The pre-publication leak audit, as a test rather than a remembered command.

It lived in the internal notes as a shell one-liner to run "before it goes to
anyone". That is not a control: on 2026-08-27 four fresh internal tracker
references had accumulated across `costlab/providers.py`, `pyproject.toml` and
`tests/test_proxy.py`, all written the same day while retiring the logprobs
strip, and nobody noticed until the audit was run for an unrelated reason. Three
references to an older tracker id had already been stripped for the same reason
on 2026-08-18 -- so this is the second time the same leak happened, which is what
makes it a test rather than a note.

A prospect needs to know WHAT a defect was and which release fixed it. Our issue
key tells them nothing, and it is not ours to hand out. Strip the id, keep the
substance.

This file deliberately never spells out a real id: the patterns below are regex
source, and a bracket or a backslash where a digit would be means they do not
match themselves. Do not "simplify" them into literals.
"""

import re
import subprocess
from pathlib import Path

# Kept identical to the audit in the internal notes. `NAVI-\d+` was added when
# the tracker moved to Linear, because the older prefix alone stopped describing
# the id shape that could leak. Deliberately NOT a generic `[A-Z]{3,5}-\d+`: the
# report renders extracted field values, so the broad shape would fail on an
# honest invoice number or a model label and teach whoever hit it to delete the
# guard.
#
# Two of the six alternatives are plain literals with no bracket or backslash to
# break them, so spelling them out here would make THIS file the leak the test
# reports -- which is exactly what happened on the first attempt. They are
# assembled from halves instead. Keep them split.
_LEAK = re.compile(
    r"SDK-0[0-9]{2}"
    r"|NA" + r"PY"
    + r"|NAVI-[0-9]+"
    + r"|nutrient-sdk-samples" + r"-internal"
    + r"|/Users/[A-Za-z]+"
    + r"|10\.0\.0\.1"
)

# The two files whose job is to contain the shapes they guard against: a
# synthetic home path proving the corpus path is redacted, a synthetic tracker
# key proving the id guard fires, and the internal host proving it never reaches
# the HTML. Everything else must be clean.
_GUARDS = {
    "tests/test_provenance.py",
    "tests/test_report_invariants.py",
}


def test_no_internal_reference_reaches_a_shipped_file():
    root = Path(__file__).resolve().parent.parent
    tracked = subprocess.run(
        ["git", "ls-files"], cwd=root, capture_output=True, text=True, check=True
    ).stdout.split()

    leaks = []
    for rel in tracked:
        if rel in _GUARDS:
            continue
        try:
            text = (root / rel).read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue  # a binary file cannot carry a comment
        for number, line in enumerate(text.splitlines(), 1):
            for hit in _LEAK.findall(line):
                leaks.append(f"{rel}:{number}: {hit}")

    assert leaks == [], (
        "internal references in shipped files. Strip the id and keep the "
        "substance:\n  " + "\n  ".join(leaks)
    )


def test_the_guard_files_still_carry_exactly_what_they_guard():
    """The exemption above must stay narrow. If a guard file stops containing its
    own pattern the test it protects has probably been weakened, and the
    exemption is then hiding real leaks in a file nobody checks.
    """
    root = Path(__file__).resolve().parent.parent
    for rel in sorted(_GUARDS):
        text = (root / rel).read_text(encoding="utf-8")
        assert _LEAK.search(text), (
            f"{rel} is exempt from the leak audit but no longer contains the "
            "pattern it exists to prove is caught — either restore the guard or "
            "drop the exemption"
        )
