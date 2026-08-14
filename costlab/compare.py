"""The verdict for one extracted field. Pure, and deliberately narrow.

A port of the TypeScript comparator the extraction studio ships. The two are
pinned together by costlab/corpus/golden-cases.json, which both test suites
run: neither side can change a verdict without turning the other red.

Biased toward "unverified" by design. Every "mismatch" is a public claim that a
provider got something wrong, shown to a customer. When the comparison cannot be
made confidently — no key, or an unparseable input where a key exists — say
nothing rather than accuse.

That bias stops at one place, and the exception is deliberate: a field that HAS
a verified answer and got no value at all is a "mismatch". Scoring that as
"unverified" would make declining to answer improve a provider's score, which is
backwards — to a buyer, "didn't answer" and "answered wrong" both mean a human
still has to go and check. Do NOT extend that exception to the ambiguous cases
(an unparseable number, a date that will not resolve); the unverified bias
governs there, unweakened.
"""

from __future__ import annotations

import re
from typing import Any, Literal

Verdict = Literal["match", "mismatch", "unverified"]

# Absorbs float representation noise without hiding a real difference.
NUMBER_TOLERANCE = 0.01

_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11,
    "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7, "aug": 8,
    "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}

_ISO = re.compile(r"^(\d{4})-(\d{2})-(\d{2})(?:[T ].*)?$")
_LONG = re.compile(r"^([A-Za-z]+)\.?\s+(\d{1,2}),?\s+(\d{4})$")
_LONG_DAY_FIRST = re.compile(r"^(\d{1,2})\s+([A-Za-z]+)\.?,?\s+(\d{4})$")
_DASHES = re.compile("[‐‑‒–—−]")
_WHITESPACE = re.compile(r"\s+")

# A slash-separated date is genuinely ambiguous (US month/day/year vs.
# international day/month/year) and deliberately left unresolved by _to_ymd.
# See the guard in compare_field for how that ambiguity is handled without
# either guessing a convention or accusing a provider of a mismatch.
_AMBIGUOUS_SLASH_DATE = re.compile(r"^\d{1,2}/\d{1,2}/\d{4}$")


def _to_number(value: Any) -> float | None:
    """A finite number, or None when the text cannot be read unambiguously."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value) if value == value and abs(value) != float("inf") else None
    if not isinstance(value, str):
        return None

    # "1.165,10" (dot as thousands separator, comma as decimal) and "1,165.10"
    # (the reverse) are both real formats and this parser cannot tell which one
    # a given string means. The wrong guess is confidently wrong rather than
    # absent: stripping the comma from "1.165,10" yields 1.1651, a finite number
    # the caller has no way to recognise as fabricated. When a comma follows a
    # dot the string is ambiguous by construction, so refuse it. A dot following
    # a comma is the unambiguous US form and must keep parsing.
    last_dot = value.rfind(".")
    last_comma = value.rfind(",")
    if last_dot != -1 and last_comma != -1 and last_comma > last_dot:
        return None

    cleaned = re.sub(r"[^0-9.-]", "", value)
    if cleaned in ("", "-", "."):
        return None
    try:
        parsed = float(cleaned)
    except ValueError:
        return None
    return parsed if parsed == parsed and abs(parsed) != float("inf") else None


def _normalise_text(value: str) -> str:
    out = _WHITESPACE.sub(" ", value.strip())
    # Unify dash forms: "08 51 13 - Aluminum Windows" and
    # "08 51 13 — Aluminum Windows" are the same spec section typed two ways,
    # and typography must not decide a verdict.
    out = _DASHES.sub("-", out)
    # Periods and commas are typography in this corpus, not content: a trailing
    # sentence period, a suffix comma in "Group, LLC", a middle initial's
    # period. Every case this fixes is punctuation-only, so removing them can
    # only move a verdict toward "match", never toward an accusation.
    out = re.sub(r"[.,]", "", out)
    return _WHITESPACE.sub(" ", out).strip().lower()


def _js_string(value: Any) -> str:
    """Stringify the way JavaScript's String() does for whole-number floats.

    Python's str(345015.0) is "345015.0" where JS's String(345015.0) is
    "345015", and _normalise_text then strips the period and corrupts the
    digits to "3450150". The TypeScript comparator this is a port of returns
    "match" for 345015.0 against "345015"; without this, Python returns
    "mismatch" — a public accusation the original does not make.
    """
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _to_ymd(value: str) -> tuple[int, int, int] | None:
    """Literal year, month and day — or None when not confidently date-shaped.

    Never builds a datetime. A datetime carries a timezone question this
    comparison has no business asking: "2025-03-01" and "March 1, 2025" are the
    same calendar day, and any implementation that turns them into instants gets
    that right in UTC and wrong by one day in half the world. The date tests run
    under a non-UTC TZ precisely to catch a port that forgets this.
    """
    text = value.strip()
    # A 4-digit year must be present. Without this guard "88.06" reads as a
    # date in some parsers, and a silent date interpretation of a number is
    # worse than no comparison at all.
    if not re.search(r"\d{4}", text):
        return None

    iso = _ISO.match(text)
    if iso:
        # The time-and-zone suffix is discarded on purpose: this answers "same
        # calendar day", not "same instant". A provider that normalises to
        # "2025-03-01T00:00:00Z" is reporting the same day as "March 1, 2025".
        return (int(iso.group(1)), int(iso.group(2)), int(iso.group(3)))

    long_form = _LONG.match(text)
    if long_form:
        month = _MONTHS.get(long_form.group(1).lower())
        if month:
            return (int(long_form.group(3)), month, int(long_form.group(2)))

    day_first = _LONG_DAY_FIRST.match(text)
    if day_first:
        month = _MONTHS.get(day_first.group(2).lower())
        if month:
            return (int(day_first.group(3)), month, int(day_first.group(1)))

    return None


def compare_field(extracted: Any, verified: dict | None, type_: str) -> Verdict:
    if verified is None:
        return "unverified"
    if extracted is None or extracted == "":
        return "mismatch"

    if type_ == "number":
        a = _to_number(extracted)
        b = _to_number(verified.get("value"))
        if a is None or b is None:
            return "unverified"
        return "match" if abs(a - b) <= NUMBER_TOLERANCE else "mismatch"

    if type_ == "boolean":
        def norm(x: Any) -> bool:
            return x if isinstance(x, bool) else _normalise_text(str(x)) == "true"

        return "match" if norm(extracted) == norm(verified.get("value")) else "mismatch"

    a_text = _js_string(extracted)
    b_text = _js_string(verified.get("value"))

    # Dates first: "2025-03-01" and "March 1, 2025" are the same answer and a
    # string comparison would call that a mismatch. Only when BOTH sides resolve
    # — otherwise the text comparison below is the honest one.
    a_ymd = _to_ymd(a_text)
    b_ymd = _to_ymd(b_text)
    if a_ymd is not None and b_ymd is not None:
        return "match" if a_ymd == b_ymd else "mismatch"

    # Deliberate divergence from the TypeScript original: a slash date like
    # "03/01/2025" is genuinely ambiguous (US month/day/year vs. day/month/year)
    # and _to_ymd refuses to guess, so it never resolves. The TypeScript
    # comparator resolves it anyway via Date.parse, which silently picks the US
    # convention — exactly the kind of unearned guess this design already
    # refuses for numbers ("1.165,10" -> unverified rather than a fabricated
    # value). Replicating Date.parse's guess was considered and rejected; the
    # spec forbids Date.parse outright and the reasoning for numbers applies
    # identically here. So when one side resolves to a calendar day and the
    # other is only ambiguous-slash-shaped (not resolved), the honest answer is
    # "cannot confidently compare" — unverified, not a text mismatch. This is
    # deliberately narrow: it must not broaden to "either side has a digit",
    # which would swallow cases like "88.06" that must keep falling through to
    # a plain text comparison.
    if a_ymd is not None and b_ymd is None and _AMBIGUOUS_SLASH_DATE.match(b_text.strip()):
        return "unverified"
    if b_ymd is not None and a_ymd is None and _AMBIGUOUS_SLASH_DATE.match(a_text.strip()):
        return "unverified"

    return "match" if _normalise_text(a_text) == _normalise_text(b_text) else "mismatch"


def summarise_verdicts(verdicts: list[Verdict]) -> dict[str, int]:
    """Counts for a run summary.

    `verified` excludes unverified fields, so a score never implies an opinion
    about a field we have no answer key for. A provider must not be marked down
    because our key is incomplete.
    """
    matched = sum(1 for v in verdicts if v == "match")
    verified = sum(1 for v in verdicts if v != "unverified")
    return {"matched": matched, "verified": verified}
