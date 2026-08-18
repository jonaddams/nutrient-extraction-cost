"""Brand assets, vendored so the report needs no network to look right.

Values are copied from the Nutrient design system's `[data-theme="company"]`
block (reconstructed from the public PSPDFKit/nutrient-website repo). The
company theme, not `sdk`: this document gets printed and circulated, and the
sdk theme is dark.

The typeface is DECLARED, never embedded. ABC Monument Grotesk belongs to ABC
Dinamo and Nutrient's licence covers the website; this repo is intended to be
public, so shipping the font file would be redistribution we have not cleared.
The stack falls back to system-ui, so colour, layout, spacing and the logo stay
brand-correct everywhere and the brand face appears wherever it is installed.
"""

from pathlib import Path

_DIR = Path(__file__).parent


def asset(name: str) -> str:
    """The text of one brand file.

    Kept to a whitelist so a caller cannot read arbitrary paths through it.
    """
    if name not in {"theme.css", "print.css", "nutrient-logo.svg"}:
        raise FileNotFoundError(name)
    return (_DIR / name).read_text(encoding="utf-8")
