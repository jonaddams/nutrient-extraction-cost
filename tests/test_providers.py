from costlab.providers import PROVIDERS, available, direct_request


def test_every_provider_declares_its_kind_and_credential():
    for pid, p in PROVIDERS.items():
        assert p.id == pid
        assert p.kind in ("frontier", "open")
        # "local" authenticates with no key at all — endpoint only.
        assert p.credential_env or pid == "local"


def test_available_filters_on_credentials_present():
    got = {p.id for p in available({"ANTHROPIC_API_KEY": "x"})}
    assert "anthropic" in got
    assert "openai" not in got


def test_local_is_available_without_any_credential():
    # A local runtime is the one configuration where documents never leave the
    # building, so it must not be gated behind a key it does not use.
    assert "local" in {p.id for p in available({})}


def test_direct_request_is_minimal_and_carries_the_schema():
    schema = {"type": "object", "properties": {"total": {"type": "number"}}}
    body = direct_request(
        PROVIDERS["bedrock"],
        "qwen.qwen3-vl-235b-a22b-instruct",
        "INVOICE TOTAL 42.00",
        schema,
    )
    assert body["model"] == "qwen.qwen3-vl-235b-a22b-instruct"
    blob = str(body)
    assert "INVOICE TOTAL 42.00" in blob
    assert "total" in blob
    # No grounding scaffolding: a no-Nutrient integration has no reason to ask
    # for token log-probabilities, and including them would put Nutrient-only
    # content on both sides of the comparison where it silently cancels.
    assert "logprobs" not in body
    assert "top_logprobs" not in body


def test_unsupported_nutrient_cell_is_declared_not_guessed():
    # Task 1's spike decides this. A provider whose endpoint override does not
    # work must be reported unsupported, never measured wrongly.
    for p in PROVIDERS.values():
        assert isinstance(p.supports_nutrient_cell, bool)


# --- Beyond the plan. Added because Task 1 measured wire-shape differences the
# --- plan's own tests do not exercise, and a body that 400s is not measurable.


def test_anthropic_declares_its_own_wire_shape():
    """Verified live 2026-08-14: the SDK sends Anthropic to /v1/messages with
    x-api-key and an anthropic-version header, while every other provider gets
    /v1/chat/completions with a bearer token. The proxy must learn this here
    rather than hardcoding a provider check of its own."""
    anthropic = PROVIDERS["anthropic"]
    assert anthropic.chat_path == "/v1/messages"
    assert anthropic.auth_header == "x-api-key"
    assert anthropic.auth_prefix == ""
    assert ("anthropic-version", "2023-06-01") in anthropic.extra_headers

    for pid in ("openai", "bedrock", "local"):
        p = PROVIDERS[pid]
        assert p.chat_path == "/v1/chat/completions"
        assert p.auth_header == "Authorization"
        assert p.auth_prefix == "Bearer "
        assert p.extra_headers == ()


def test_direct_request_for_anthropic_is_a_messages_body_not_a_chat_body():
    """response_format is not an Anthropic parameter and max_tokens is required,
    so the OpenAI-shaped body the plan specified would 400 rather than measure.
    The schema travels in the prompt because no native structured-output
    parameter was verified for this endpoint — do not add one unmeasured."""
    schema = {"type": "object", "properties": {"total": {"type": "number"}}}
    body = direct_request(
        PROVIDERS["anthropic"], "claude-sonnet-5", "INVOICE TOTAL 42.00", schema
    )
    assert "response_format" not in body
    assert body["max_tokens"] > 0
    blob = str(body)
    assert "INVOICE TOTAL 42.00" in blob
    assert "total" in blob


def test_local_defaults_to_the_runtime_that_was_actually_verified():
    """LM Studio on 1234 completed a real extraction through the SDK on
    2026-08-14 and returned a usage block. Ollama's 11434 was never reachable
    to test, so it is documented rather than defaulted to."""
    assert PROVIDERS["local"].upstream_base == "http://localhost:1234"
