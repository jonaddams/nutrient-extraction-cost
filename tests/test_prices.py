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
    """The shipped table must not contain a rate nobody verified. OpenAI and the
    local runtime are absent on purpose — no list price was confirmed for the
    OpenAI model this tool defaults to, and a local runtime has no per-token
    price at all. Both must surface as "not priced", never as $0.00, which is a
    claim about cost rather than an absence of one.
    """
    table = load()
    assert table.rate("bedrock", "qwen.qwen3-vl-235b-a22b-instruct") == (0.53, 2.66)
    assert table.rate("anthropic", "claude-sonnet-5") == (3.0, 15.0)
    assert table.rate("openai", "gpt-5.4") is None
    assert table.rate("local", "qwen/qwen3-vl-8b") is None


def test_the_bundled_table_is_dated_and_says_what_the_dates_mean():
    table = load()
    assert table.checked_on
    # The introductory-rate expiry is the single most perishable fact in the
    # table, so the note must carry it rather than leaving a stale number to be
    # quoted at a prospect after it lapses.
    assert "2026-08-31" in table.note
