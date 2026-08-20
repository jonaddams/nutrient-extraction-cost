"""Every difference between providers, in one file.

This is the file a prospect edits to add their own provider or model, so it is
deliberately data rather than logic: no unit outside this module knows that
Anthropic and OpenAI name their usage fields differently, or that a local
runtime needs no credential.

Everything here that is not obvious was measured live on 2026-08-14 rather
than read from documentation. Where a value looks arbitrary, the comment says
what was run to get it.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Provider:
    id: str
    label: str
    kind: str  # "frontier" | "open"
    credential_env: str  # "" when none is required
    default_model: str
    upstream_base: str  # scheme + host, no path
    sdk_provider: str  # the value the Nutrient SDK expects
    supports_nutrient_cell: bool  # set from the Task 1 spike, never guessed

    # Request keys the proxy strips before forwarding, because this upstream
    # answers WRONG rather than complaining when it receives them. Empty for
    # every hosted provider -- see RecordingProxy._drop_keys for why a local
    # runtime needs logprobs gone.
    drop_request_keys: tuple[str, ...] = ()

    # --- Wire shape. Not in the original plan; added because the Nutrient SDK
    # --- was observed sending Anthropic somewhere else entirely, and the proxy
    # --- must not carry a provider check of its own.
    #
    #   anthropic  POST /v1/messages          x-api-key + anthropic-version
    #   all others POST /v1/chat/completions  Authorization: Bearer
    #
    # A proxy that assumes the OpenAI shape does not fail loudly on the
    # Anthropic path: the SDK raises "anthropic returned no text content
    # (finishReason=(none))", whose own wording blames the prompt and says
    # endpoint reachability is not the likely cause.
    chat_path: str = "/v1/chat/completions"
    auth_header: str = "Authorization"
    auth_prefix: str = "Bearer "
    extra_headers: tuple[tuple[str, str], ...] = ()

    @property
    def is_openai_wire(self) -> bool:
        """True when this provider speaks the OpenAI chat-completions dialect.

        Three of the four do, including Bedrock and a local runtime. Callers
        should branch on this rather than on `id`, so adding a provider means
        editing this file only.
        """
        return self.chat_path == "/v1/chat/completions"


# Anthropic requires a max_tokens on every request; the OpenAI dialect does not.
# Sized to comfortably hold a field-extraction reply and no more — an unbounded
# value would let a thinking model spend output tokens the comparison then has
# to explain.
# Both dialects, though only Anthropic REQUIRES it. The OpenAI-wire body
# went without one until a local runtime showed why that is not safe: under
# grammar-constrained decoding an unbounded JSON `number` can fail to
# terminate, and qwen3-vl-30b answered `"totalAmount": 4201.4500000000015...`
# with the digits running on until the proxy's 600s timeout. One document took
# longer than the entire 102-call frontier run. A cap turns a hang into a
# truncated body, which `extracted_values` cannot parse and therefore records
# as unreadable -- "not scoreable", never a mismatch, so the model is not
# marked wrong for our own cutoff.
_DIRECT_MAX_TOKENS = 2048

PROVIDERS: dict[str, Provider] = {
    "anthropic": Provider(
        id="anthropic",
        label="Claude Sonnet 5",
        kind="frontier",
        credential_env="ANTHROPIC_API_KEY",
        default_model="claude-sonnet-5",
        upstream_base="https://api.anthropic.com",
        sdk_provider="anthropic",
        supports_nutrient_cell=True,
        chat_path="/v1/messages",
        auth_header="x-api-key",
        auth_prefix="",
        extra_headers=(("anthropic-version", "2023-06-01"),),
    ),
    "openai": Provider(
        id="openai",
        label="OpenAI",
        kind="frontier",
        credential_env="OPENAI_API_KEY",
        default_model="gpt-5.4",
        upstream_base="https://api.openai.com",
        sdk_provider="openai",
        supports_nutrient_cell=True,
    ),
    "bedrock": Provider(
        id="bedrock",
        label="Qwen3-VL 235B (Bedrock)",
        kind="open",
        credential_env="BEDROCK_API_KEY",
        default_model="qwen.qwen3-vl-235b-a22b-instruct",
        upstream_base=os.environ.get(
            "BEDROCK_BASE", "https://bedrock-mantle.us-east-1.api.aws"
        ),
        # Bedrock's OpenAI-compatible surface. The SDK rejects every other
        # value on this path, so the id and the SDK provider differ on purpose.
        sdk_provider="openai",
        supports_nutrient_cell=True,
    ),
    "local": Provider(
        id="local",
        label="Local runtime",
        kind="open",
        credential_env="",
        default_model=os.environ.get("LOCAL_MODEL", "qwen/qwen3-vl-8b"),
        # LM Studio's default port. This is the local runtime that was actually
        # verified end to end through the SDK — it completed an extraction and
        # returned a usage block. Ollama exposes the same dialect on 11434 and
        # should work, but was never reachable to confirm, so it is an override
        # rather than the default: LOCAL_BASE=http://localhost:11434
        upstream_base=os.environ.get("LOCAL_BASE", "http://localhost:1234"),
        sdk_provider="local",
        supports_nutrient_cell=True,
        drop_request_keys=("logprobs", "top_logprobs"),
    ),
}

# All four cells are measurable: every provider above honoured the SDK's
# endpoint override, and every one returned a usage block the proxy could read.
# Nothing here is speculative — see the spike findings for the raw output.

# The whole no-Nutrient prompt. Everything the SDK sends beyond this is the
# scaffolding whose cost this tool exists to price.
DIRECT_PROMPT = "Extract the requested fields from this document as JSON."


def available(env: dict[str, str] | None = None) -> list[Provider]:
    """Providers whose credential is present. A local runtime needs none."""
    env = os.environ if env is None else env
    return [
        p
        for p in PROVIDERS.values()
        if not p.credential_env or env.get(p.credential_env, "").strip()
    ]


def direct_request(
    provider: Provider, model: str, document_text: str, schema: dict[str, Any]
) -> dict[str, Any]:
    """A minimal no-Nutrient request: the document, the schema, nothing else.

    Two bodies, because the two dialects do not accept each other's. The
    OpenAI dialect takes a json_schema response_format, verified to return
    schema-conformant JSON (`{"total": 42}` from a one-line document).

    Anthropic rejects that body twice over. Both errors were reproduced against
    the live API on 2026-08-14:

        400 invalid_request_error  max_tokens: Field required
        400 invalid_request_error  response_format: Extra inputs are not permitted

    So max_tokens is mandatory, response_format is refused outright, and the
    schema travels in the prompt instead.

    The schema is deliberately NOT sent to Anthropic as a tool definition even
    though that would constrain it more tightly: no such call was measured, and
    an unverified parameter on the no-Nutrient side would put made-up
    scaffolding into the very comparison this tool exists to make honest.
    """
    if provider.is_openai_wire:
        return {
            "model": model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": DIRECT_PROMPT},
                        {"type": "text", "text": document_text},
                    ],
                }
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "extraction", "schema": schema},
            },
            "max_tokens": _DIRECT_MAX_TOKENS,
        }

    return {
        "model": model,
        "max_tokens": _DIRECT_MAX_TOKENS,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            f"{DIRECT_PROMPT}\n\n"
                            f"Reply with JSON matching this schema:\n"
                            f"{json.dumps(schema)}"
                        ),
                    },
                    {"type": "text", "text": document_text},
                ],
            }
        ],
    }
