# OpenRouter model evaluation

Status: **evaluation recorded; no model selected or enabled**.

This document records the comparison between the two current candidates for a
model-driven Hermes assistant. The existing deployment uses local LM Studio
with Qwen3 30B-A3B; OpenRouter remains disabled until the operator explicitly
approves a model and completes the OpenRouter configuration.

## Evaluation snapshot

The OpenRouter public model and endpoint catalogs were checked during this
evaluation. Prices and endpoint availability are not contractual and must be
rechecked immediately before activation.

| Model | Input price | Output price | Context | Tools/structured output |
|---|---:|---:|---:|---|
| `google/gemini-2.5-flash-lite` | $0.10/M tokens | $0.40/M tokens | 1,048,576 | Yes |
| `deepseek/deepseek-v4-flash` | approximately $0.047/M tokens | approximately $0.095/M tokens | approximately 1M | Yes |

DeepSeek is substantially cheaper. For this mail workload, however, the
absolute monthly difference is expected to be small; privacy, provider
predictability, latency, and tool behavior matter more than token price.

## Gemini 2.5 Flash-Lite

Model ID:

```text
google/gemini-2.5-flash-lite
```

Advantages:

- Designed for low-latency, high-volume workloads.
- Supports Hermes-compatible function tools and structured output.
- Large context window for bounded mail reports and future assistant tasks.
- A comparatively simple provider and privacy boundary when routed through
  Google Vertex.
- Good default fit for mail summarization, classification, and approval
  workflows.

Tradeoffs:

- Less capable than larger Gemini, Claude, or DeepSeek reasoning models for
  complex long-horizon planning.
- Google AI Studio and Google Vertex are different OpenRouter endpoints; the
  privacy configuration must not allow unrestricted routing.
- More expensive than DeepSeek, although the expected absolute cost remains
  low for daily mail processing.

## DeepSeek V4 Flash

Model ID:

```text
deepseek/deepseek-v4-flash
```

Advantages:

- Excellent price/performance potential.
- Large context window and support for tools, structured output, and reasoning
  controls.
- Potentially stronger agentic behavior per dollar than Flash-Lite.

Tradeoffs:

- OpenRouter routes this model through many different providers.
- The current ZDR endpoint list does not use a first-party DeepSeek endpoint;
  it contains third-party inference providers such as OpenInference, Azure,
  DeepInfra, NextBit, Phala, and others.
- Provider-specific latency, availability, privacy terms, and tool-call
  behavior require more operational testing.
- Unrestricted automatic provider fallback would be inappropriate for private
  mail.

## Zero Data Retention comparison

OpenRouter defines Zero Data Retention (ZDR) as a provider policy under which
the provider does not retain request data. OpenRouter documents that ZDR can
be enforced per request with:

```json
{
  "provider": {
    "zdr": true,
    "data_collection": "deny",
    "allow_fallbacks": false,
    "require_parameters": true
  }
}
```

ZDR is a routing constraint, not a guarantee that mail stays on the local
machine. Email content still leaves the machine and is processed transiently
by the selected provider. ZDR also does not automatically cover external
plugins or tools; this project will not enable OpenRouter web-search or other
third-party plugins for mail processing.

### Current ZDR endpoint observations

The public ZDR endpoint catalog currently lists:

- **Gemini 2.5 Flash-Lite:** two endpoints, both Google Vertex variants:
  `google-vertex` and `google-vertex/eu`.
- **DeepSeek V4 Flash:** multiple endpoints across unrelated inference
  providers, rather than a single first-party DeepSeek endpoint.

Therefore Gemini has the clearer ZDR boundary. DeepSeek can be used with ZDR,
but it requires selecting and reviewing one approved ZDR provider instead of
allowing automatic routing across the available pool.

For a strict privacy deployment, the intended policy is:

1. Enforce `provider.zdr=true`.
2. Set `data_collection` to `deny`.
3. Set `allow_fallbacks` to `false`.
4. Set `require_parameters` to `true`.
5. Restrict `only`/provider routing to an explicitly approved endpoint family.
6. Verify that the selected endpoint supports the required Hermes tool and
   structured-output parameters.
7. Keep OpenRouter logging disabled and do not enable external plugins.

ZDR eligibility and provider policies must be checked again at activation;
OpenRouter can change endpoint availability and provider declarations.

## Recommendation

For this personal-mail assistant, the recommended first choice is:

```text
google/gemini-2.5-flash-lite
```

using a Google Vertex ZDR endpoint with automatic fallback disabled. It gives
up some DeepSeek price/performance in exchange for a simpler and more
reviewable privacy boundary and a more predictable operational profile.

DeepSeek V4 Flash remains a strong alternative if maximum capability per dollar
is more important than provider simplicity. It should only be activated with a
pinned, reviewed ZDR provider and a dedicated acceptance test for tool calls,
prompt injection, latency, and failure handling.

## Activation work, when approved

Selecting either model will require a separate implementation change:

- Store an OpenRouter API key outside the repository with mode `0600`.
- Configure Hermes to use the selected OpenRouter model and provider.
- The model-driven Hermes cron workflow is now active with local LM Studio
  Qwen3 30B-A3B; any future OpenRouter migration must preserve that workflow.
- Preserve fixed no-argument mail tools, Docker isolation, DM-only delivery,
  unread preservation, attachment-byte prohibition, and disabled mutations.
- Add provider routing preferences for ZDR and no fallback.
- Set a spending limit and monitor OpenRouter usage.
- Test with fixtures before sending real mail content to the provider.
- Re-run prompt-injection, tool-boundary, malformed-output, and Discord
  delivery tests.

No OpenRouter API key was added and no mail content was sent to OpenRouter as
part of this evaluation.

## References

- [Gemini 2.5 Flash-Lite model endpoints](https://openrouter.ai/api/v1/models/google/gemini-2.5-flash-lite/endpoints)
- [DeepSeek V4 Flash model endpoints](https://openrouter.ai/api/v1/models/deepseek/deepseek-v4-flash/endpoints)
- [OpenRouter ZDR endpoint catalog](https://openrouter.ai/api/v1/endpoints/zdr)
- [OpenRouter Zero Data Retention](https://openrouter.ai/docs/guides/features/zdr)
- [OpenRouter provider selection](https://openrouter.ai/docs/guides/routing/provider-selection)
