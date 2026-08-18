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
    assert not re.search(r"SDK-0\d\d", html), f"{label} names an internal defect id"
    assert not re.search(r"(sk-[A-Za-z0-9]{8}|Bearer\s+\S+)", html), (
        f"{label} looks like it carries a credential"
    )
    assert "10.0.0.1" not in html, f"{label} names an internal host"


def test_a_freshly_rendered_report_holds_the_invariants():
    _assert_invariants(_rendered(), "rendered report")


def test_the_committed_example_holds_the_invariants():
    """The example is the first thing a prospect opens, and it ships in a public
    repo, so it is held to the same properties as a live render."""
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
