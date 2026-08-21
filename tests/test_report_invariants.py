"""Properties the report must hold whoever it is sent to."""

import re
from pathlib import Path

import pytest

from costlab import render_html, report
from costlab.prices import PriceTable

EXAMPLE = Path(__file__).parent.parent / "examples" / "example-report.html"


def _rec(doc, pid, with_nutrient, inp):
    return {
        "docId": doc,
        "providerId": pid,
        "withNutrient": with_nutrient,
        "usage": {"inputTokens": inp, "outputTokens": 10, "cachedInputTokens": 0},
        "status": 200,
        "calls": 1,
        "attempts": 1,
        "latencyMs": 1000.0,
        "extracted": {"documentTitle": "Invoice"},
        "requestedFields": ["documentTitle"],
    }


def _rendered():
    table = PriceTable(checked_on="2026-08-14", rates={})
    summary = report.summarise(
        [_rec("a", "bedrock", True, 1000), _rec("a", "bedrock", False, 600)],
        table,
        models={"bedrock": "qwen3-vl"},
        provenance={
            "corpusName": "Nutrient sample corpus",
            "documentCount": 1,
            "models": [{"providerId": "bedrock", "model": "qwen3-vl"}],
            "keySources": ["BEDROCK_API_KEY (set)"],
            "runDate": "2026-08-18T09:30:00-04:00",
            "priceTableDate": "2026-08-14",
            "toolVersion": "0.1.0",
        },
    )
    return render_html.render(summary)


def _assert_invariants(html: str, label: str) -> None:
    fetch = re.compile(
        r"""(url\(\s*['"]?|(?:src|href)\s*=\s*['"]?|@import\s+['"]?)"""
        r"""(https?:)?//""",
        re.IGNORECASE,
    )
    assert not fetch.search(html), f"{label} fetches something external"
    assert "@font-face" not in html, f"{label} embeds a font"
    assert "base64" not in html, f"{label} embeds a binary"
    assert "/Users/" not in html, f"{label} leaks a local path"
    assert "/home/" not in html, f"{label} leaks a local path"
    assert "C:\\" not in html, f"{label} leaks a local path"
    # Two id shapes: the internal SDK-0NN registry, and NAVI-NN, the Linear key
    # that became the tracker when the team moved off JIRA. Deliberately NOT a
    # generic LETTERS-DIGITS pattern: this report renders extracted field values,
    # so a real invoice number (INV-5465) or model label (GPT-5) would trip a
    # broad guard and turn the suite red on honest data. Add prefixes as trackers
    # appear rather than widening the shape.
    assert not re.search(r"SDK-0\d\d|NAVI-\d+", html), (
        f"{label} names an internal defect id"
    )
    assert not re.search(r"(sk-[A-Za-z0-9]{8}|Bearer\s+\S+)", html), (
        f"{label} looks like it carries a credential"
    )
    assert "10.0.0.1" not in html, f"{label} names an internal host"


def test_a_freshly_rendered_report_holds_the_invariants():
    _assert_invariants(_rendered(), "rendered report")


def test_the_committed_example_holds_the_invariants():
    """The example is the first thing a prospect opens, and it ships to a named
    recipient, so it is held to the same properties as a live render."""
    assert EXAMPLE.exists(), f"missing {EXAMPLE}"
    _assert_invariants(EXAMPLE.read_text(), "committed example")


def test_the_committed_example_is_labelled_as_our_corpus():
    assert "Nutrient sample corpus" in EXAMPLE.read_text()


def test_a_report_without_provenance_still_renders():
    """provenance is optional; a summary built without it must still produce a
    whole document rather than raising or printing None."""
    table = PriceTable(checked_on="2026-08-14", rates={})
    summary = report.summarise(
        [_rec("a", "bedrock", True, 1000), _rec("a", "bedrock", False, 600)],
        table,
        models={"bedrock": "qwen3-vl"},
    )
    out = render_html.render(summary)
    assert out.startswith("<!doctype html>")
    assert out.rstrip().endswith("</html>")
    assert "None" not in out


def test_the_fetch_invariant_actually_fires_on_a_css_url_reference():
    """A guard that has never been shown to fire is a guard nobody knows works.

    The old src=/href= regex would have sailed past a url(...) reference
    inside an inlined stylesheet. This proves the widened check catches it.
    """
    with pytest.raises(AssertionError):
        _assert_invariants(
            '<style>.x{background:url(https://evil/x.css)}</style>', "synthetic"
        )


def test_the_defect_id_invariant_fires_on_a_linear_key():
    """The tracker moved from an internal SDK-0NN registry to Linear, and the
    guard knew only the old shape. This pins the new one.

    The key here is deliberately synthetic, following test_provenance's synthetic
    path: proving the shape is caught does not require shipping a real issue id
    in a file that goes to a customer.
    """
    with pytest.raises(AssertionError):
        _assert_invariants("<p>see NAVI-9999 for the runtime fix</p>", "synthetic")


def test_the_defect_id_invariant_spares_real_extracted_values():
    """The deliberate narrowness, pinned. This report renders extracted field
    values, so a generic LETTERS-DIGITS guard would fail on an honest invoice
    number or model label and teach whoever hit it to delete the guard."""
    _assert_invariants(
        "<p>Invoice INV-5465 extracted by GPT-5 and Qwen3-VL-235B</p>", "synthetic"
    )
