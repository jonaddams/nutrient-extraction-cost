import json

from costlab.prices import load


def test_price_table_carries_the_date_it_was_checked(tmp_path):
    # A published tool with undated prices is worse than one with none:
    # Sonnet 5's introductory rate ends 2026-08-31 and Bedrock is priced
    # separately from Anthropic's first-party rates.
    p = tmp_path / "p.json"
    p.write_text(
        json.dumps(
            {
                "checkedOn": "2026-08-14",
                "rates": {
                    "anthropic": {
                        "claude-sonnet-5": {
                            "inputPerMTok": 3.0,
                            "outputPerMTok": 15.0,
                        }
                    }
                },
            }
        )
    )
    table = load(p)
    assert table.checked_on == "2026-08-14"
    assert table.rate("anthropic", "claude-sonnet-5") == (3.0, 15.0)


def test_unknown_model_returns_none_rather_than_a_guess(tmp_path):
    p = tmp_path / "p.json"
    p.write_text(json.dumps({"checkedOn": "2026-08-14", "rates": {}}))
    assert load(p).rate("anthropic", "unknown-model") is None


# --- Beyond the plan.


def test_the_bundled_table_prices_only_what_was_actually_looked_up():
    """Every rate here was read off the vendor's own pricing page on the date
    the table carries. A local runtime stays absent because it has no per-token
    price at all — it must surface as "not priced", never as $0.00, which is a
    claim about cost rather than an absence of one.

    Sonnet 5 is $2/$10, NOT $3/$15. The table carried $3/$15 for two weeks on
    the strength of a scheduled increase that was then cancelled: Anthropic's
    pricing page now says the introductory $2/$10 "is now the standard price"
    and "the previously scheduled increase to $3/$15 ... will not occur". Every
    run in that window overstated Anthropic's cost by 50%.
    """
    table = load()
    assert table.rate("bedrock", "qwen.qwen3-vl-235b-a22b-instruct") == (0.53, 2.66)
    assert table.rate("anthropic", "claude-sonnet-5") == (2.0, 10.0)
    assert table.rate("openai", "gpt-5.4") == (2.5, 15.0)
    assert table.rate("local", "qwen/qwen3-vl-8b") is None


def test_every_provider_that_bills_money_has_a_rate():
    """The guard that would have caught the OpenAI gap before a prospect did.

    A provider needing a credential is one a vendor invoices, so its default
    model must be priced or the cost band shows "not priced" for a model the
    reader is being asked to compare. A provider needing NO credential is
    self-hosted and correctly has no rate.
    """
    from costlab.providers import PROVIDERS

    table = load()
    unpriced = [
        f"{pid}/{p.default_model}"
        for pid, p in PROVIDERS.items()
        if p.credential_env and table.rate(pid, p.default_model) is None
    ]
    assert unpriced == [], f"billed but unpriced: {unpriced}"


def test_the_note_makes_no_claim_about_a_cancelled_price_increase():
    """The note explained the wrong figure confidently: it said the $2.00 rate
    "ends 2026-08-31, reverting to the 3.00 listed here". That increase was
    cancelled. A note that justifies a stale number is worse than no note.
    """
    note = load().note
    assert "reverting" not in note.lower()
    assert "no list price was confirmed for the default OpenAI model" not in note


def test_the_bundled_table_is_dated_and_says_what_the_dates_mean():
    table = load()
    assert table.checked_on
    # The introductory-rate expiry is the single most perishable fact in the
    # table, so the note must carry it rather than leaving a stale number to be
    # quoted at a prospect after it lapses.
    assert "2026-08-31" in table.note
