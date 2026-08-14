from costlab.capture import read_usage, redact_headers, summarise_request


def test_redact_headers_removes_credentials_case_insensitively():
    # The proxy handles live keys for up to four providers. A leaked key in a
    # committed log is the one unrecoverable mistake this tool can make.
    out = redact_headers(
        {
            "Authorization": "Bearer sk-secret",
            "x-api-key": "abc",
            "Content-Type": "application/json",
        }
    )
    assert out["Authorization"] == "<redacted>"
    assert out["x-api-key"] == "<redacted>"
    assert out["Content-Type"] == "application/json"


def test_summarise_request_counts_text_and_flags():
    body = {
        "model": "qwen.qwen3-vl-235b-a22b-instruct",
        "messages": [
            {"role": "system", "content": "you extract fields"},
            {"role": "user", "content": [{"type": "text", "text": "extract"}]},
        ],
        "response_format": {"type": "json_schema"},
    }
    out = summarise_request(body)
    assert out["model"] == "qwen.qwen3-vl-235b-a22b-instruct"
    assert out["textChars"] == len("you extract fields") + len("extract")
    assert out["imageCount"] == 0
    assert out["hasResponseFormat"] is True
    assert out["hasCacheControl"] is False
    assert out["toolCount"] == 0


def test_read_usage_normalises_openai_shape():
    out = read_usage({"usage": {"prompt_tokens": 1200, "completion_tokens": 40}})
    assert out == {"inputTokens": 1200, "outputTokens": 40, "cachedInputTokens": 0}


def test_read_usage_normalises_anthropic_shape():
    # Anthropic names them input_tokens/output_tokens and reports cache reads
    # separately. Normalising here means no later unit knows the difference.
    out = read_usage(
        {
            "usage": {
                "input_tokens": 900,
                "output_tokens": 30,
                "cache_read_input_tokens": 512,
            }
        }
    )
    assert out == {"inputTokens": 900, "outputTokens": 30, "cachedInputTokens": 512}


def test_read_usage_picks_up_openai_cached_tokens():
    out = read_usage(
        {
            "usage": {
                "prompt_tokens": 1000,
                "completion_tokens": 10,
                "prompt_tokens_details": {"cached_tokens": 256},
            }
        }
    )
    assert out["cachedInputTokens"] == 256


def test_read_usage_returns_none_when_absent():
    # A provider that reports no usage cannot be measured. None is the signal
    # the runner uses to record that honestly rather than inventing a zero.
    assert read_usage({"choices": []}) is None
