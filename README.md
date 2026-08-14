# nutrient-extraction-cost

Measure what document extraction actually costs — on your documents, with your API keys, with
and without the Nutrient SDK in the path.

Every number this tool reports is one it observed. It does not estimate, and where it cannot
measure something it says so instead of substituting a zero.

## What it measures

Four cells. Two model tiers, each run twice:

|  | with the Nutrient SDK | direct to the model |
|---|---|---|
| **Frontier** (Claude, OpenAI) | SDK-mediated extraction | minimal request, same document text |
| **Open-weight** (Bedrock, local runtime) | SDK-mediated extraction | minimal request, same document text |

For each cell it records exact input and output token counts taken from the provider's own usage
block, then prices them from a dated table you can replace.

**The "direct to the model" cells produce no reliable page coordinates.** They are cheaper because
they do less: no grounded source locations, no confidence components. The delta is the price of
those features, not waste. Every surface that compares the two says so.

## Install and run

Requires Python 3.10 or newer.

```bash
pip install -e .

export BEDROCK_API_KEY=...          # or ANTHROPIC_API_KEY / OPENAI_API_KEY
export NUTRIENT_LICENSE_KEY=...     # required for the with-Nutrient cells only

costlab --corpus costlab/corpus --providers bedrock
```

It prints the plan and the number of calls, then asks before spending anything. Add `--yes` to
skip the prompt in a script.

Output lands in `out/`: `records.json` (one record per document per cell), `report.html`,
`report.json`, and the captured request bodies.

### Options

| | |
|---|---|
| `--corpus DIR` | Documents to run. A bare directory of PDFs or images works; a `manifest.json` lets you set per-document schemas. |
| `--providers a,b` | Restrict to specific providers. Default is every one whose credential is set. |
| `--prices FILE` | Use your negotiated rates instead of the bundled list prices. |
| `--no-capture-bodies` | Do not write request or response bodies to disk. |
| `--out DIR` | Where to write results. Defaults to `out/`. |
| `--yes` | Skip the confirmation prompt. |

## Your documents and where they go

Stated plainly rather than implying documents stay local, because they do not:

- **No telemetry.** The tool sends nothing to Nutrient — no documents, no results, no usage, no
  crash reports. There is no Nutrient endpoint anywhere in the codebase. Grep for one.
- **Documents go to whichever model you configure**, cloud or local, using your own credentials
  and your existing provider relationship. Your decision about your data.
- **The local-runtime path is the one where documents genuinely never leave the building.** Any
  cloud provider — Anthropic, OpenAI, Bedrock — receives your document content. That is inherent
  to measuring what those providers charge for it.
- **Captured request bodies are written to local disk** for auditability, and they contain
  document content. Disable with `--no-capture-bodies`; the token measurements still work.
- **Credentials are never written.** The proxy handles live keys and redacts every credential
  header before anything reaches disk.

## Dependencies

One, and a reason for it:

| | |
|---|---|
| `nutrient-sdk` | The thing being measured. |

Everything else is the Python standard library — `http.server` for the proxy, `urllib.request` for
outbound calls. No web framework, no provider SDKs, no HTTP client library. The dependency list is
short because you should be able to audit this before running it against your documents.

## How it works, and why a proxy

The Nutrient SDK surfaces no token usage of its own, so the only way to learn what an
SDK-mediated call cost is to observe the call. A recording proxy binds an OS-chosen port on
loopback, the SDK is pointed at it, and it forwards to your real provider while reading the usage
block out of the response. The direct calls go through the same proxy, so both halves produce one
record format and neither is measured more generously than the other.

The direct call reuses **the document text the SDK actually sent**, taken from the captured
request, rather than extracting its own. Holding the extracted content constant is what makes the
difference attributable to the SDK's request scaffolding instead of to two different text
extractions. This is why the with-Nutrient cell for a document runs before its direct cell.

## Provider support

All four providers were verified end to end: each honours the SDK's endpoint override, and each
returns a usage block the proxy can read.

| Provider | Credential | Wire protocol | Priced in the bundled table |
|---|---|---|---|
| Anthropic | `ANTHROPIC_API_KEY` | `POST /v1/messages` | yes |
| OpenAI | `OPENAI_API_KEY` | `POST /v1/chat/completions` | no — see below |
| Bedrock | `BEDROCK_API_KEY` | `POST /v1/chat/completions` | yes |
| Local runtime | none | `POST /v1/chat/completions` | no — no per-token price exists |

A provider missing from the price table reports its token counts and **"not priced"** rather than
`$0.00`. A zero would assert the calls were free, which is a different claim from not knowing what
they cost. Add your own rates with `--prices`.

### Local runtimes

Defaults to LM Studio on `http://localhost:1234`, the runtime verified end to end. Ollama exposes
the same dialect on `11434`:

```bash
export LOCAL_BASE=http://localhost:11434
export LOCAL_MODEL=your-model-id
```

**On macOS, a local runtime on another host needs Local Network permission.** If the runtime is
plainly up and reachable in a browser but the tool reports `[Errno 65] No route to host`, macOS is
denying your Python interpreter local-network access — the connection is refused before it leaves
the machine. Grant it in System Settings › Privacy & Security › Local Network, or run the runtime
on the same machine, where loopback is unaffected.

## Reading the results honestly

Four things that will mislead you if you skip them.

**Token counts do not compare across providers.** The same document measured 1,800 prompt tokens
on OpenAI, 2,282 on Bedrock and 2,540 on Anthropic. A cross-provider token column compares
tokenizers, not efficiency. Compare tokens *within* a provider, and cost *across* providers.

**The overhead is a constant per call, not a percentage.** On the bundled 17-document corpus
against Bedrock Qwen3-VL, the SDK added **exactly 468 input tokens to every single document** — a
one-page receipt and a 40-page medical record alike, spread +468 to +468. That works out to about
**$25 per 100,000 documents** at the bundled list price. Your own numbers will differ by provider
and by document, which is why the tool exists rather than a published figure.

That constant is also why the bundled corpus deliberately mixes one-page receipts with a 40-page
record: the same 468 tokens are a large fraction of a small document and a rounding error on a
large one, so a corpus of only small documents overstates the overhead and only large ones
understate it. The report shows the
per-call spread beside every total: while that spread stays narrow, the at-volume projection is
sound. If it widens, read the per-document rows instead.

**Output tokens are not comparable between the halves, and the headline price ignores them.** The
SDK requests grounding metadata the direct call does not, and an unconstrained direct call is free
to be verbose. On the bundled corpus one document's direct call emitted about 7,500 more output
tokens than its SDK counterpart — and because output prices roughly five times input, that single
outlier moved the aggregate from +$25 to −$87 per 100k documents, i.e. it made the SDK look
cheaper overall. The headline figure is therefore priced from input tokens, which measure the same
document on both sides. The output-inclusive total is still shown, labelled, and should not be read
as a like-for-like saving.

**Anthropic bills thinking tokens inside output tokens.** A measured extraction spent 52 of its 87
output tokens thinking, with no thinking requested. Output cost is not proportional to returned
text.

**A retry is not a call.** The SDK retries a failing request up to four times, and each attempt
reaches the proxy. Records carry an attempt count alongside a successful-call count, so a retry
storm cannot inflate a token total unnoticed.

## The bundled corpus

Seventeen documents: fourteen single-page ones across invoices, claims, healthcare, finance,
logistics and handwriting, plus three larger synthetic records at 12, 25 and 40 pages. Point
`--corpus` at your own directory to run this on documents that look like yours — which is the
point of the tool.

Handwritten samples are included on purpose and they score poorly for every provider. Those are
genuine misreads, not a bug in the harness.

## Prices

`costlab/prices.json` carries every rate with the date it was checked, and the report prints that
date beside any dollar figure. Rates move: Claude Sonnet 5's introductory input rate ends
2026-08-31, and Bedrock is partner-priced by AWS and is not interchangeable with Anthropic
first-party rates. Replace the file, or pass `--prices`, and the report will say which table it
used.

## Tests

```bash
python -m pytest tests/
```

No network and no credentials required — every provider is stubbed.
