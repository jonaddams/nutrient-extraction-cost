"""Cost-relevant facts about one outbound model request.

Pure functions only: no network, no filesystem, no globals. proxy.py does the
I/O and delegates every decision here, which is what makes the interesting
behaviour testable without a server or a spent token.
"""

from __future__ import annotations

from typing import Any

_REDACT = {"authorization", "x-api-key", "api-key", "cookie", "proxy-authorization"}


def redact_headers(headers: dict[str, str]) -> dict[str, str]:
    """Replace credential values with a placeholder, preserving key names."""
    return {
        k: ("<redacted>" if k.lower() in _REDACT else v) for k, v in headers.items()
    }


def _has_cache_control(node: Any) -> bool:
    if isinstance(node, dict):
        return "cache_control" in node or any(
            _has_cache_control(v) for v in node.values()
        )
    if isinstance(node, list):
        return any(_has_cache_control(v) for v in node)
    return False


def summarise_request(body: dict[str, Any]) -> dict[str, Any]:
    """The cost-relevant shape of one outbound request."""
    text_chars, images = 0, 0
    for message in body.get("messages") or []:
        content = message.get("content")
        if isinstance(content, str):
            text_chars += len(content)
            continue
        for part in content or []:
            if not isinstance(part, dict):
                continue
            if part.get("type") == "text":
                text_chars += len(part.get("text") or "")
            elif part.get("type") in ("image_url", "image"):
                images += 1
    return {
        "model": body.get("model"),
        "textChars": text_chars,
        "imageCount": images,
        "imageBytes": 0,
        "hasCacheControl": _has_cache_control(body),
        "hasResponseFormat": bool(body.get("response_format")),
        "toolCount": len(body.get("tools") or []),
    }


def read_usage(body: dict[str, Any]) -> dict[str, int] | None:
    """Normalise any provider's usage block, or None if there isn't one.

    Providers disagree on names: OpenAI-compatible surfaces say prompt_tokens
    and nest cached counts under prompt_tokens_details, Anthropic says
    input_tokens and reports cache reads as their own field. Normalising once
    here means no later unit has to know which provider it is looking at.

    Three shapes were confirmed live (2026-08-14), not two — and two of them
    omit prompt_tokens_details ENTIRELY rather than reporting zero, which is
    why the lookup below guards with `or {}`:

        OpenAI     prompt_tokens / completion_tokens, prompt_tokens_details present
        Anthropic  input_tokens / output_tokens, cache_read_input_tokens
        Bedrock    prompt_tokens / completion_tokens, NO prompt_tokens_details
        LM Studio  prompt_tokens / completion_tokens, NO prompt_tokens_details

    Anthropic's cache_creation_input_tokens is deliberately NOT counted here:
    cache writes are billed above the base input rate, not below it, so folding
    them into cachedInputTokens would report a premium as a discount.

    None is meaningful and must not become zero: a provider that reports no
    usage cannot be measured, and the runner records that rather than
    inventing a number.
    """
    usage = body.get("usage")
    if not isinstance(usage, dict):
        return None
    input_tokens = usage.get("prompt_tokens", usage.get("input_tokens"))
    output_tokens = usage.get("completion_tokens", usage.get("output_tokens"))
    if input_tokens is None and output_tokens is None:
        return None
    cached = usage.get("cache_read_input_tokens", 0) or (
        usage.get("prompt_tokens_details") or {}
    ).get("cached_tokens", 0)
    return {
        "inputTokens": int(input_tokens or 0),
        "outputTokens": int(output_tokens or 0),
        "cachedInputTokens": int(cached or 0),
    }
