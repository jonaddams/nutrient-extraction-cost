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

## Accuracy

Three modes, in increasing order of what they need from you.

**Cross-provider agreement** needs nothing at all, and is the default on your own documents. It
reports every field where two configurations returned different answers. This is the part worth
dwelling on: looking at two different values, you cannot tell which is right without a citation
back to the page — and a citation is exactly what the grounded half returns and the direct half
does not.

**The bundled answer key** scores true accuracy on the 17 shipped documents. Every value in it was
read directly off the document and carries the line it came from.

**Your own answer key** scores true accuracy on your documents:

    costlab --corpus ./my-docs --answers ./my-key.csv --mode accuracy

CSV columns are `docId,field,value,source`. JSON is also accepted, in the shape of
`costlab/corpus/answers.json`.

Three things the scoring deliberately does:

- **A field with no answer key is never counted against a provider.** Your score should not depend
  on how complete the key is.
- **A field the key covers that came back empty counts as wrong**, not as unknown. "Didn't answer"
  and "answered wrong" both mean a human still has to go and check.
- **Anything not confidently comparable is reported as unverified rather than as an error.** Every
  reported mismatch is a claim that a provider got something wrong, so the bar for making one is
  deliberately high.

Accuracy mode gives each document its own schema, taken from the answer key, so its token counts
are **not** comparable with a cost run's. Run them separately.

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
| `--mode cost\|accuracy` | `cost` (default): one shared schema for every document. `accuracy`: each document's own answer-key fields — see [Accuracy](#accuracy). |
| `--answers PATH` | Score against this answer key instead of the bundled one. JSON or CSV (`docId,field,value,source`). Rescopes every document's request to that key's fields **regardless of `--mode`** — a cost-mode run supplying `--answers` still asks each document only for the key's fields, so its token counts are no longer comparable with an ordinary cost run's. |
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

All four providers honour the SDK's endpoint override and return a usage block the proxy can read,
so all four are measurable. The three cloud providers also **extract** correctly; LM Studio's
with-Nutrient cells return zero fields for a reason that is not the SDK's or this tool's, described
under [Local runtimes](#local-runtimes).

| Provider | Credential | Wire protocol | Priced in the bundled table | Extraction verified |
|---|---|---|---|---|
| Anthropic | `ANTHROPIC_API_KEY` | `POST /v1/messages` | yes | yes |
| OpenAI | `OPENAI_API_KEY` | `POST /v1/chat/completions` | no — see below | yes |
| Bedrock | `BEDROCK_API_KEY` | `POST /v1/chat/completions` | yes | yes |
| Local runtime | none | `POST /v1/chat/completions` | no — no per-token price exists | **no — tokens only, see below** |

A provider missing from the price table reports its token counts and **"not priced"** rather than
`$0.00`. A zero would assert the calls were free, which is a different claim from not knowing what
they cost. Add your own rates with `--prices`.

### Local runtimes

Defaults to LM Studio on `http://localhost:1234`. Ollama exposes the same dialect on `11434`:

```bash
export LOCAL_BASE=http://localhost:11434
export LOCAL_MODEL=your-model-id
```

**The with-Nutrient cells do not currently work against LM Studio, and the failure is silent.**
Measured 2026-08-17 against LM Studio serving `qwen/qwen3-vl-8b` and `qwen/qwen3-vl-30b`: the SDK
requests structured output (`response_format: json_schema`) together with `logprobs`, and LM Studio
then omits the grammar-forced tokens from the assembled `content` string. What comes back is the
model's own words with every schema-determined span deleted —

```
 "Progress Invoice - Riverside Mixed-Use Development — Phase 2"},b2", "b3", "b4"]
```

— which is not parseable, so the SDK reports a successful call that extracted **zero fields**. Same
request minus `logprobs` returns well-formed JSON from the same model, and Bedrock answers the
identical `logprobs` + `json_schema` pair correctly, so this is LM Studio's assembly of `content`
rather than the pair being unsupportable. Until it is fixed, a local run measures **tokens only**:
the input-token delta is still exact, and the direct cells still return values, but treat any
accuracy or agreement number from a local run as meaningless rather than as a poor score.

**On macOS, a local runtime on another host needs Local Network permission — and there is usually
no checkbox to grant it.** If the runtime is plainly up and reachable in a browser but the tool
reports `[Errno 65] No route to host`, macOS is denying that specific interpreter local-network
access; the connection is refused before it leaves the machine. The permission is **per binary**,
and only bundled GUI apps ever get prompted, so an unbundled CLI interpreter is denied by default
and never appears in System Settings › Privacy & Security › Local Network at all. Measured on one
machine: Apple's `/usr/bin/python3` reached the host, while the uv-managed CPython 3.11 in this
project's venv and Homebrew's 3.12 and 3.14 all failed instantly with `Errno 65`.

Loopback is exempt from the permission, so the workarounds all end in talking to `127.0.0.1`:

- run the runtime on the same machine, or
- `ssh -N -L 1235:127.0.0.1:1234 you@that-host`, then `export LOCAL_BASE=http://127.0.0.1:1235`
  (Apple's `ssh` is permitted; the host needs Remote Login enabled), or
- relay the port with a permitted binary — a dozen-line `socket` forwarder run under
  `/usr/bin/python3` listening on `127.0.0.1:1235` and connecting to the runtime's host is enough.

Nothing in the failure names the permission: the SDK surfaces it as
`502 Bad Gateway (Error Code: 3026) [Source: Vision]`, which reads like the model rejecting the
request. If every cell fails instantly and identically, test the route from the *same interpreter*
the tool runs under before suspecting the model.

## Reading the results honestly

Four things that will mislead you if you skip them.

**Token counts do not compare across providers.** The same document measured 1,800 prompt tokens
on OpenAI, 2,282 on Bedrock and 2,540 on Anthropic. A cross-provider token column compares
tokenizers, not efficiency. Compare tokens *within* a provider, and cost *across* providers.

**The overhead is a constant per call, not a percentage — and the constant is per provider.** On
the bundled 17-document corpus, measured 2026-08-17, the SDK added the same number of input tokens
to *every* document, from a one-page receipt to a 40-page medical record, but that number differs by
provider:

| Provider | Δ input per document | Spread across 17 docs | Per 100k documents (input) |
|---|---|---|---|
| Claude Sonnet 5 | +1,226 | +1,226 to +1,226 | $367.80 |
| Qwen3-VL 235B (Bedrock) | +468 | +468 to +468 | $24.80 |
| OpenAI | +748 | +748 to +748 | not priced |
| Qwen3-VL (LM Studio, local) | +468 | +468 to +468 | not priced — no per-token price exists |

So quote a figure with its provider attached or not at all: the same scaffolding is **15× more per
100k documents** on Claude Sonnet 5 than on Bedrock's Qwen3-VL. The local Qwen matching Bedrock's
Qwen token-for-token is the tokenizer, not a coincidence — the SDK sends the same extracted text
both times.

Two runs against Bedrock an hour apart also showed the absolute counts moving slightly on 2 of 17
documents (1,049 → 1,058 input tokens on one), because the SDK's own text extraction is not
bit-deterministic. **The delta was +468 in both runs regardless.** What the tool measures is stable
even where its inputs are not.

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
