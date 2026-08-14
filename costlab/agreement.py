"""Where the providers disagree — the one accuracy mode needing no ground truth.

This is the default for a prospect's own corpus, and it is also the tool's
argument in miniature: where two providers return different answers, a reader
cannot tell which is right without a citation to check. That is precisely what
the grounded half buys and the direct half does not.

Values are compared with compare_field rather than string equality, so
"$345,015.00" and 345015 agree. A pair the comparator cannot judge counts as
neither agreement nor disagreement: an ambiguous comparison is not evidence of a
difference, and inflating the disagreement rate with ambiguity would overstate
the case this tool is making.

That is why a row is a three-way state, not a boolean. "4/1/2026" against
"2026-01-04" is exactly this case: compare_field refuses to guess a date
convention and returns "unverified" for both directions, so the row must land
as "ambiguous" rather than silently becoming "agreed" — reporting 100%
agreement from a comparison that was never made would be a fabricated claim in
a prospect-facing artifact, and it would understate disagreement, cutting
against the very case this tool exists to make.

The comparison TYPE for a row is decided from every value in the row, not from
whichever provider label happens to sort first alphabetically. Deciding it
from one arbitrary member means the same two values -- 345015 and
"$345,015.00" -- verify as agreeing or disagreeing depending only on which
provider's name sorts first, which would make a prospect's own naming of their
providers change what the report shows for an identical extraction. The rule
is: "number" only if EVERY value in the row parses unambiguously as a number
(via compare.py's own _to_number, the same parser compare_field itself uses
for numeric fields); otherwise "string". That degrades honestly at the edges
-- when only some values parse as numbers, falling back to a text comparison
is not a guess, it is refusing to fabricate a shared numeric type neither side
actually offered.

Fixing the type alone is not enough once a row has three or more cells, which
is the routine case here: PROVIDERS configures several providers, each with an
SDK and a direct half, so one (docId, field) row commonly holds many cells.
compare_field's numeric match is a TOLERANCE (abs(a - b) <= 0.01), and
tolerance-based equality is not transitive -- 100.008 is close enough to both
100.0 and 100.016, but 100.0 and 100.016 are 0.016 apart, over tolerance.
Comparing every other cell only against whichever one happens to be the
reference (a star topology) therefore reports a different verdict depending
purely on which cell that was, i.e. on provider naming again. The fix is
EVERY unordered pair, not a star: a row disagrees if any pair mismatches,
agrees if none mismatch and at least one pair matches, and is ambiguous only
if every pair came back unverified. Enumerating all pairs is order-independent
by construction -- it does not depend on argument, unlike a single arbitrary
reference -- and it is the honest reading: if two providers genuinely differ
by more than the tolerance, that is a real disagreement worth showing even
when some third value happens to sit between them.

`distinct` counts unique ANSWERS, not mismatches against an arbitrary
reference -- {100, 200, 200} has two distinct answers, not three, and a count
that fabricates a third would overstate disagreement in exactly the direction
this module exists to avoid overstating it. It is computed by normalising
every value the row's chosen way (the parsed number when the row is numeric,
otherwise the same text normalisation compare_field itself applies) and
counting unique results -- well-defined, order-independent, and it can never
exceed the number of cells in the row.
"""

from __future__ import annotations

from itertools import combinations
from typing import Any

from .compare import (
    _AMBIGUOUS_SLASH_DATE,
    _js_string,
    _normalise_text,
    _to_number,
    _to_ymd,
    compare_field,
)


def _label(record: dict[str, Any]) -> str:
    half = "sdk" if record.get("withNutrient") else "direct"
    return f"{record['providerId']}:{half}"


def _looks_numeric(value: Any) -> bool:
    """True only when a value is safe evidence that this row's shared type is
    "number". _to_number will happily parse a date-shaped string like
    "1/2/2026" into 122026.0 by stripping the slashes — correct behaviour for
    compare_field, which is only ever handed a value after the CALLER has
    already decided the field is numeric, but the wrong signal here, where
    agreement() is the one inferring the type from the values themselves. A
    string that looks like a date must never count as numeric evidence, even
    when _to_number can mangle it into one — otherwise two ambiguous slash
    dates get compared as numbers instead of falling into compare_field's
    date handling, and report a false "disagreed" on a pair the comparator
    was never actually able to judge.
    """
    if isinstance(value, str):
        text = value.strip()
        if _to_ymd(text) is not None or _AMBIGUOUS_SLASH_DATE.match(text):
            return False
    return _to_number(value) is not None


def agreement(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_doc: dict[str, dict[str, dict[str, Any]]] = {}
    for record in records:
        extracted = record.get("extracted")
        if not extracted:
            continue
        for field, value in extracted.items():
            by_doc.setdefault(record["docId"], {}).setdefault(field, {})[
                _label(record)
            ] = value

    rows: list[dict[str, Any]] = []
    for doc_id in sorted(by_doc):
        for field in sorted(by_doc[doc_id]):
            values = by_doc[doc_id][field]
            # One opinion is not a conflict. Counting it as one would inflate
            # the disagreement rate with fields nobody contested.
            if len(values) < 2:
                continue
            # Decided from every value in the row, never from one arbitrary
            # member -- see the module docstring for why that would make the
            # verdict depend on provider naming order.
            type_ = (
                "number"
                if all(_looks_numeric(v) for v in values.values())
                else "string"
            )

            # All unordered pairs, not a star against one arbitrary reference:
            # compare_field's numeric tolerance is not transitive, so a star
            # topology's verdict depends on which cell happened to be picked
            # as the reference -- i.e. on provider naming again. Enumerating
            # every pair is order-independent by construction and catches a
            # real disagreement (like 100.0 vs. 100.016 above) even when a
            # third value sits between them.
            pair_verdicts = [
                compare_field(a, {"value": b}, type_)
                for a, b in combinations(values.values(), 2)
            ]
            disagreed = any(v == "mismatch" for v in pair_verdicts)
            agreed = any(v == "match" for v in pair_verdicts)
            # Three states, not a boolean. A row where every pairwise
            # comparison came back "unverified" (compare_field could not judge
            # any of them, e.g. "4/1/2026" against "2026-01-04") must not
            # collapse into "agreed" — that would report 100% agreement from a
            # comparison that was never made, which is both a fabricated claim
            # and, in the direction that matters most, an understatement of
            # disagreement.
            if disagreed:
                state = "disagreed"
            elif agreed:
                state = "agreed"
            else:
                state = "ambiguous"

            # Unique ANSWERS, not mismatches against an arbitrary reference --
            # see the module docstring for why the latter overstates
            # disagreement. Normalised the same way the row's type decided:
            # the parsed number, or compare_field's own text normalisation.
            if type_ == "number":
                normalised = {_to_number(v) for v in values.values()}
            else:
                normalised = {_normalise_text(_js_string(v)) for v in values.values()}
            distinct = len(normalised)

            rows.append(
                {
                    "docId": doc_id,
                    "field": field,
                    "values": values,
                    "state": state,
                    "agree": state == "agreed",
                    "distinct": distinct,
                }
            )
    return rows


def agreement_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    agreed = sum(1 for r in rows if r["state"] == "agreed")
    disagreed = sum(1 for r in rows if r["state"] == "disagreed")
    ambiguous = sum(1 for r in rows if r["state"] == "ambiguous")
    judged = agreed + disagreed
    return {
        "fields": len(rows),
        "agreed": agreed,
        "disagreed": disagreed,
        "ambiguous": ambiguous,
        # None, never 0.0: nothing judged is not total disagreement. Ambiguous
        # rows are excluded from both numerator and denominator, not folded
        # into either side.
        "rate": agreed / judged if judged else None,
    }
