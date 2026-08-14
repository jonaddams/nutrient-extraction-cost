"""A dated price table and nothing more.

Prices move, and a tool that hardcodes them into logic quietly starts lying.
Every rate lives in prices.json with the date it was checked, and every report
prints that date beside any dollar figure it shows.

`rate()` returns None for anything not in the table, and no caller substitutes a
default. A missing rate means "we do not know what this costs", which is a
different statement from "this is free" — and the only one the data supports.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_BUNDLED = Path(__file__).with_name("prices.json")


@dataclass(frozen=True)
class PriceTable:
    checked_on: str
    rates: dict[str, dict[str, dict[str, float]]]
    note: str = ""

    def rate(self, provider_id: str, model: str) -> tuple[float, float] | None:
        """Input and output dollars per million tokens, or None if unpriced."""
        entry = (self.rates.get(provider_id) or {}).get(model)
        if not entry:
            return None
        return (float(entry["inputPerMTok"]), float(entry["outputPerMTok"]))

    def cost(
        self, provider_id: str, model: str, input_tokens: int, output_tokens: int
    ) -> float | None:
        """Dollars for one call, or None when the model is not in the table."""
        found = self.rate(provider_id, model)
        if found is None:
            return None
        input_rate, output_rate = found
        return (input_tokens * input_rate + output_tokens * output_rate) / 1_000_000


def load(path: str | Path | None = None) -> PriceTable:
    data: dict[str, Any] = json.loads(Path(path or _BUNDLED).read_text())
    return PriceTable(
        checked_on=data["checkedOn"],
        rates=data.get("rates", {}),
        note=data.get("note", ""),
    )
