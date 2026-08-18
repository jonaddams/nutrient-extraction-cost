import re

import pytest

from costlab import brand


def test_asset_returns_file_text():
    assert "--text-neutral-primary" in brand.asset("theme.css")


def test_unknown_asset_raises():
    with pytest.raises(FileNotFoundError):
        brand.asset("nope.css")


def test_no_external_requests_in_brand_files():
    """A brand layer is exactly what smuggles a webfont URL into the report."""
    for name in ("theme.css", "print.css", "nutrient-logo.svg"):
        text = brand.asset(name)
        assert "http://" not in text
        assert "https://" not in text
        assert not re.search(r"url\(", text), f"{name} fetches something"


def test_no_font_binary_is_vendored():
    """ABC Monument Grotesk is ABC Dinamo's; we declare it, we do not ship it."""
    from pathlib import Path

    brand_dir = Path(brand.__file__).parent
    assert not list(brand_dir.glob("*.woff*"))
    assert not list(brand_dir.glob("*.ttf"))
    assert not list(brand_dir.glob("*.otf"))


def test_the_typeface_is_declared_with_a_fallback():
    css = brand.asset("theme.css")
    assert '"ABC Monument Grotesk"' in css
    assert "system-ui" in css


def test_the_logo_inherits_text_colour():
    """currentColor is what lets one SVG work on light and dark grounds."""
    assert 'fill="currentColor"' in brand.asset("nutrient-logo.svg")


def test_print_css_opens_the_appendix():
    assert "details" in brand.asset("print.css")
