# nutrient-extraction-cost

Measure what document extraction actually costs — on your documents, with your API keys, with
and without the Nutrient SDK in the path.

Every number this tool reports is one it observed. It does not estimate, and where it cannot
measure something it says so instead of substituting a zero.

Provided to Nutrient customers for evaluation under the [Nutrient Reference-Use
License](LICENSE) — not open source. See [Licence and distribution](#licence-and-distribution).

**See the output before you run anything:** [`examples/example-report.html`](examples/example-report.html)
is a real 102-call run on the bundled sample corpus across three providers. Every
figure in it is measured, and the provenance block at the top of the page says
exactly which documents, models and price table produced it.

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
are **not** comparable with a cost run's. Run each mode separately, then put both in one report with
[`--join`](#joining-runs): a joined report computes the cost band from the shared-schema records and
the accuracy band from the answer-key records, so the two are never compared, and it states on the
page how many documents each band covers.

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
| `--join DIR,DIR` | Combine previous runs into one report instead of calling anything. See [Joining runs](#joining-runs). |
| `--no-capture-bodies` | Do not write request or response bodies to disk. |
| `--out DIR` | Where to write results. Defaults to `out/`. |
| `--yes` | Skip the confirmation prompt. |

### Joining runs

One report can be built from several previous runs, calling nothing and spending
nothing:

```bash
costlab --join out/frontier-run,out/local-run --out out/joined
```

This exists because the accuracy comparison a buyer wants — frontier models down
to a self-hosted one — is not something one invocation can produce. The frontier
models need three hosted credentials; a self-hosted model needs a runtime you
control, serving one model at a time. Joining lets each run happen when it can
and still be read together.

The joined report **says that it is joined**: the provenance grid lists every
run's date, and a caveat states that figures gathered at different times are
close to like-for-like rather than exactly so.

It **refuses** a merge where one provider id covers different models. A provider
id is a route, not a model — every local runtime in this project reports as
`local` — so combining two local runs would sum two different sets of weights
into one row and label it with whichever run's provenance came last. If a run did
not record which model it used, that counts as unconfirmed and is refused too:

```
cannot join these runs: 'local' ran 'qwen/qwen3-vl-8b' in run 'a' and
'qwen/qwen3-vl-30b' in run 'b'. Merging would present two models as one row.
```

**Joining a cost run to an accuracy run is how one report carries both.** When a
report holds both kinds of record, each band takes only what it is entitled to:
the cost band the shared-schema records, so a payload difference stays
attributable to the document, and the accuracy band the answer-key records, which
are the only ones that were actually asked the key's fields. Nothing is blended,
and the page states how many documents each band covers — narrowing a band to a
subset and saying nothing would read as covering everything.

`examples/example-report.html` is exactly this: three runs joined, cost measured
over 17 documents in cost mode and accuracy scored over 17 in accuracy mode.

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
so all four are measurable, and all four **extract** correctly. A local runtime needs two request
keys stripped before it will, for a reason that is not this tool's, described under
[Local runtimes](#local-runtimes).

| Provider | Credential | Wire protocol | Priced in the bundled table | Extraction verified |
|---|---|---|---|---|
| Anthropic | `ANTHROPIC_API_KEY` | `POST /v1/messages` | yes | yes |
| OpenAI | `OPENAI_API_KEY` | `POST /v1/chat/completions` | no — see below | yes |
| Bedrock | `BEDROCK_API_KEY` | `POST /v1/chat/completions` | yes | yes |
| Local runtime | none | `POST /v1/chat/completions` | no — no per-token price exists | yes — with two request keys stripped, see below |

A provider missing from the price table reports its token counts and **"not priced"** rather than
`$0.00`. A zero would assert the calls were free, which is a different claim from not knowing what
they cost. Add your own rates with `--prices`.

### Local runtimes

Defaults to LM Studio on `http://localhost:1234`. Ollama exposes the same dialect on `11434`:

```bash
export LOCAL_BASE=http://localhost:11434
export LOCAL_MODEL=your-model-id
```

**The with-Nutrient cells work against LM Studio, but only because this tool strips two request
keys before forwarding.** Measured 2026-08-17 against LM Studio serving `qwen/qwen3-vl-8b` and
`qwen/qwen3-vl-30b`: the SDK requests structured output (`response_format: json_schema`) together
with `logprobs`, and LM Studio then omits the grammar-forced tokens from the assembled `content`
string. What comes back is the model's own words with every schema-determined span deleted —

```
 "Progress Invoice - Riverside Mixed-Use Development — Phase 2"},b2", "b3", "b4"]
```

— which is not parseable, and the SDK reports a **successful** call anyway. Across a corpus run that
surfaced as zero extracted fields; on a single document printing `TOTAL $4,201.45` it surfaced as an
extracted total of `201.45`. A wrong number that looks right is a different class of problem from a
visible failure, which is why this is worth the workaround rather than a caveat.

The proxy therefore removes `logprobs` and `top_logprobs` from a local runtime's requests before
forwarding them. **Neither key contributes to prompt tokens, so the measurement this tool exists to
make is unaffected** — and with them gone the same model returns correct values, source blocks and
bounding boxes, verified across a 17-document corpus run on 2026-08-20 in which every with-Nutrient
cell parsed. Bedrock answers the identical `logprobs` + `json_schema` pair correctly, so the
dropped tokens are LM Studio's assembly of `content` rather than the pair being unsupportable.

Nutrient's SDK team has reproduced the unconditional `logprobs` request and fixed it upstream; once
you are on a release carrying that fix, the strip is no longer needed. Until then leave it in place:
without it a local run's extracted values are silently wrong rather than visibly missing.

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

| Provider / model | Δ input per document | Spread across 17 docs | Per 100k documents (input) |
|---|---|---|---|
| Claude Sonnet 5 | +1,226 | +1,226 to +1,226 | $367.80 |
| Qwen3-VL 235B (Bedrock) | +468 | +468 to +468 | $24.80 |
| OpenAI | +748 | +748 to +748 | not priced |
| Qwen3-VL 8B / 30B (LM Studio) | +468 | +468 to +468 | not priced — no per-token price exists |
| Qwen3.5 9B (LM Studio) | +479 | +479 to +479 | not priced |
| Qwen3.5 35B-A3B (LM Studio) | +478 | +478 to +478 (12 of 17 docs) | not priced |

So quote a figure with its provider *and model* attached, or not at all. The spread is real: the same
scaffolding costs **15× more per 100k documents** on Claude Sonnet 5 than on Bedrock's Qwen3-VL.

**The unit is the model, not the vendor and not the tokenizer generation.** Qwen3.5 9B and Qwen3.5
35B-A3B are the same generation on the same host, sent identical text by the same SDK, and they
differ — 479 against 478. Each model applies its own chat template around the SDK's scaffolding, so
even a sibling model is a new measurement. Meanwhile Qwen3-VL reads that same text as 468 whether the
weights run on Bedrock or on a laptop, so *where* a model runs changes nothing.

Which is the whole argument for measuring instead of quoting: there is no single number to publish.

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

## Licence and distribution

This tool is **not open source.** It is provided under the [Nutrient Reference-Use
License](LICENSE) to a recipient named in an applicable Nutrient agreement, and the licence
file governs — the summary here is orientation, not terms.

What that means in practice:

- **You may** run it, read it, and modify it for your own internal, non-production evaluation
  of Nutrient products. Auditing it before you point it at your documents is exactly the
  intended use.
- **You may not** redistribute, publish, sell or sublicense it, or otherwise make it
  available to anyone else.
- **It is confidential.** Do not share the code with third parties without Nutrient's prior
  written consent.
- **The reports you generate are yours.** They are your measurements of your documents; the
  licence covers this tool, not its output. Note that a report's appendix embeds values
  extracted from the documents you ran, so handle the file the way you would handle those
  documents.

Questions about the licence, or about wider rights to use the tool: talk to your Nutrient
contact.
