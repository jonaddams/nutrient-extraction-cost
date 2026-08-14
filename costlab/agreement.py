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

The comparison TYPE for a row is decided from every PRESENT value in the row,
not from whichever provider label happens to sort first alphabetically.
Deciding it from one arbitrary member means the same two values -- 345015 and
"$345,015.00" -- verify as agreeing or disagreeing depending only on which
provider's name sorts first, which would make a prospect's own naming of their
providers change what the report shows for an identical extraction. The rule
is: "number" only if EVERY present value in the row parses unambiguously as a
number (via compare.py's own _to_number, the same parser compare_field itself
uses for numeric fields); otherwise "string". That degrades honestly at the
edges -- when only some present values parse as numbers, falling back to a
text comparison is not a guess, it is refusing to fabricate a shared numeric
type neither side actually offered.

PRESENT is doing real work in that sentence: absent values are excluded from
the type decision entirely, not counted as evidence either way. An absence
carries no type information -- that is what absence means -- but
_looks_numeric(None) is False, so counting it here demoted an otherwise
unanimous numeric row to "string" the instant any one provider returned
nothing: {100, "$100.00"} agreed, but {100, "$100.00", None} fell back to a
text comparison between 100 and "$100.00" and disagreed -- two providers who
plainly agree reported as disagreeing because a THIRD provider found nothing.
Three providers with two halves each is this tool's normal configuration, and
a provider returning null for a field it could not find is ordinary, so this
was reachable in real runs, not a contrived corner case. Restricting the type
decision to present values fixes it; the absent cell still drives the row to
"disagreed" via the absence rule below (one provider answered, one did not --
a real difference), but it does so without corrupting the *other* providers'
verdict against each other.

Fixing the type alone is not enough once a row has three or more cells, which
is the routine case here: PROVIDERS configures several providers, each with an
SDK and a direct half, so one (docId, field) row commonly holds many cells.
compare_field's numeric match is a TOLERANCE (abs(a - b) <= 0.01), and
tolerance-based equality is not transitive -- 100.008 is close enough to both
100.0 and 100.016, but 100.0 and 100.016 are 0.016 apart, over tolerance. A
star topology -- comparing every other cell only against whichever one
happens to be the reference -- therefore reports a different verdict
depending purely on which cell that was, i.e. on provider naming again. The
fix is EVERY unordered pair, not a star: a row disagrees if any pair
mismatches, agrees if none mismatch and at least one pair matches, and is
ambiguous only if every pair came back unverified. That is the honest
reading: if two providers genuinely differ by more than the tolerance, that
is a real disagreement worth showing even when some third value happens to
sit between them.

Enumerating every pair does NOT, by itself, make the per-pair verdict
order-independent -- that was the false claim this docstring made through
three rounds of fixes, and it is exactly how the next bug survived
unnoticed. compare_field is asymmetric in its two operands by design: it
opens with `if extracted is None or extracted == "": return "mismatch"`,
which inspects only the first argument. That rule is CORRECT for scoring
against a ground-truth key (a provider that declined to answer a field the
key covers must not score better than one that guessed wrong), and it is
pinned there by the shared golden-case fixture. It is wrong here, where
calling compare_field(a, {"value": b}) casts one PEER into the "verified"
role that asymmetry depends on, and that casting is just whichever one
combinations() happened to emit first -- insertion order again. Concretely:
compare_field(".", {"value": ""}, "string") is "match" (both normalise to
""), but compare_field("", {"value": "."}, "string") is "mismatch" (the
extracted-side check fires before normalisation ever runs), so the exact
same pair of values disagrees or agrees depending on which provider's
record happened to be built first.

The fix is to classify absence explicitly, per value, before ever calling
compare_field: a value is absent if it is None, or if
_normalise_text(_js_string(value)) is empty (which is why "." and ""
collapse to the same "no answer" -- a punctuation placeholder and a blank
field are the same non-answer in different clothes). Given that:
  - both absent -> the pair AGREES. Two providers that both found nothing
    have not disagreed about anything.
  - exactly one absent -> the pair DISAGREES. One found a value, one did
    not; that is a real difference a prospect should see, and it is
    symmetric by inspection -- it does not matter which side is which.
  - both present -> delegate to compare_field as before. In this regime the
    None/"" branch cannot fire (both values are, by construction, evidence
    of an answer), and every remaining branch -- numeric tolerance, ymd
    equality, boolean, and text normalisation -- treats its two operands
    alike, so the result is symmetric by construction, not by luck.
Only with absence handled this way is the per-pair verdict actually
order-independent; enumerating all pairs was necessary but not sufficient.

`distinct` counts unique ANSWERS, not mismatches against an arbitrary
reference -- {100, 200, 200} has two distinct answers, not three, and a count
that fabricates a third would overstate disagreement in exactly the direction
this module exists to avoid overstating it. Two absent values are the same
answer and must count as one, so every absent value normalises to a single
shared marker before counting; present values normalise the row's chosen way
(the parsed number when the row is numeric, otherwise the same text
normalisation compare_field itself applies). Counting the unique results is
well-defined, order-independent, and can never exceed the number of cells in
the row.
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


class _Absent:
    """A single canonical marker every absent value normalises to for
    `distinct` -- so None, "" and "." collapse to one shared answer instead
    of three. A dedicated sentinel rather than reusing None or "" so it can
    never collide with a real parsed number or a genuinely-empty-after-
    normalisation string (there is no such string: emptiness after
    normalisation is exactly the absence test)."""


_ABSENT = _Absent()


def _label(record: dict[str, Any]) -> str:
    half = "sdk" if record.get("withNutrient") else "direct"
    return f"{record['providerId']}:{half}"


def _is_absent(value: Any) -> bool:
    """True for a value that amounts to "no answer" -- None, "", or a
    punctuation-only placeholder like "." that normalises to nothing.

    compare_field's own extracted-is-None-or-empty rule is correct for
    scoring against a ground-truth key but must never decide a PEER
    comparison, where there is no key and either side could just as easily
    have been cast as "extracted". Classifying absence here, before either
    value is handed to compare_field, is what makes the pairwise verdict
    symmetric regardless of which value combinations() happened to emit
    first -- see the module docstring for the concrete "." vs "" example
    this closes.
    """
    if value is None:
        return True
    return _normalise_text(_js_string(value)) == ""


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
            # Decided from every PRESENT value in the row, never from one
            # arbitrary member -- see the module docstring for why that would
            # make the verdict depend on provider naming order. Absent values
            # are excluded from this decision entirely: an absence carries no
            # type information (that is what absence means), and
            # _looks_numeric(None) is False, so including absent cells here
            # would demote an otherwise-numeric row to "string" the moment
            # any one provider returned nothing -- exactly the bug this
            # exclusion closes. A row with no present values at all falls
            # back to "string", unchanged from prior behaviour (and moot: the
            # pairwise loop below never delegates to compare_field when
            # every value is absent).
            present_values = [v for v in values.values() if not _is_absent(v)]
            type_ = (
                "number"
                if present_values and all(_looks_numeric(v) for v in present_values)
                else "string"
            )

            # All unordered pairs, not a star against one arbitrary reference:
            # compare_field's numeric tolerance is not transitive, so a star
            # topology's verdict depends on which cell happened to be picked
            # as the reference -- i.e. on provider naming again. Enumerating
            # every pair catches a real disagreement (like 100.0 vs. 100.016
            # above) even when a third value sits between them.
            #
            # Absence is classified before either value ever reaches
            # compare_field -- see _is_absent and the module docstring for
            # why compare_field's own None/"" rule must not decide a peer
            # comparison. Only once both values are confirmed present is the
            # verdict delegated, where compare_field's remaining branches are
            # symmetric in their two operands by construction.
            pair_verdicts = []
            for a, b in combinations(values.values(), 2):
                a_absent, b_absent = _is_absent(a), _is_absent(b)
                if a_absent and b_absent:
                    pair_verdicts.append("match")
                elif a_absent or b_absent:
                    pair_verdicts.append("mismatch")
                else:
                    pair_verdicts.append(compare_field(a, {"value": b}, type_))
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
            # disagreement. Every absent value collapses to the same _ABSENT
            # marker -- None and "" and "." are one answer, not three -- and
            # every present value normalises the row's chosen way: the parsed
            # number, or compare_field's own text normalisation. _ABSENT can
            # never collide with a real normalised value (a parsed number is
            # always a float; a normalised present string is never empty,
            # since emptiness after normalisation is exactly the absence
            # test above), so the count is unambiguous.
            normalised = {
                _ABSENT
                if _is_absent(v)
                else (_to_number(v) if type_ == "number" else _normalise_text(_js_string(v)))
                for v in values.values()
            }
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
