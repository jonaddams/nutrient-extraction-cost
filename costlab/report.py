"""Turns records into a comparison a prospect can read without being misled.

Three renderings, one summary. The summary is where every judgement lives; the
renderers only lay it out.

Tokens are the primary result and dollars are secondary, because tokens are what
was measured and dollars are computed from a list price that may not be the
reader's. But tokens carry their own trap: the same document tokenises
differently on every provider (measured: 1,800 on OpenAI, 2,282 on Bedrock,
2,540 on Anthropic), so a reader comparing token columns across providers is
comparing tokenizers. Within one provider the SDK-versus-direct delta is exact,
and that delta is the measurement this tool exists to produce.
"""

from __future__ import annotations

import html as html_mod
import json
from typing import Any

from .agreement import agreement, agreement_summary
from .answers import AnswerKey
from .prices import PriceTable
from .providers import PROVIDERS
from .score import score_records, score_summary

# Stated wherever the two halves are compared on price. They are not
# feature-equivalent, and a comparison that omits this is the most misleading
# thing this tool could publish.
COORDINATES_CAVEAT = (
    "The “without Nutrient” calls return no reliable page coordinates. "
    "They are cheaper because they do less: no grounded source locations, no "
    "confidence components. Do not read the delta as waste."
)

TOKENIZER_CAVEAT = (
    "Token counts are not comparable across providers — each tokenises the "
    "same document differently, so a cross-provider token column compares "
    "tokenizers rather than efficiency. Compare tokens within a provider, and "
    "cost across them."
)

THINKING_CAVEAT = (
    "Anthropic bills thinking tokens inside output tokens, itemised separately "
    "in its usage block. Output cost is not proportional to returned text."
)

# The reason the headline projection is priced from INPUT tokens only.
OUTPUT_CAVEAT = (
    "Output tokens are not comparable between the two halves. The SDK asks for "
    "grounded metadata the direct call does not, and a direct call is free to "
    "be verbose — in one measured run a single document's direct call emitted "
    "about 7,500 more output tokens than its SDK counterpart, which alone was "
    "enough to flip the aggregate and make the SDK look cheaper overall. The "
    "headline figure is therefore priced from input tokens, which measure the "
    "same document on both sides. The total including output is shown "
    "separately and should not be read as a like-for-like saving."
)


def summarise(
    records: list[dict[str, Any]],
    table: PriceTable,
    models: dict[str, str] | None = None,
    key: AnswerKey | None = None,
) -> dict[str, Any]:
    """Per-document and per-provider totals, with the unmeasurable set aside.

    A row needs both halves. A cell that reported no usage is counted in
    `unmeasurable` and excluded from every total, so an unmeasurable provider
    cannot become a zero-token row that drags the averages down.
    """
    models = models or {}

    def model_for(provider_id: str) -> str:
        if provider_id in models:
            return models[provider_id]
        provider = PROVIDERS.get(provider_id)
        return provider.default_model if provider else ""

    unmeasurable = sum(1 for r in records if not r.get("usage"))

    pairs: dict[tuple[str, str], dict[bool, dict[str, Any]]] = {}
    for r in records:
        if not r.get("usage"):
            continue
        pairs.setdefault((r["docId"], r["providerId"]), {})[
            bool(r["withNutrient"])
        ] = r

    by_document: list[dict[str, Any]] = []
    for (doc_id, provider_id), halves in pairs.items():
        sdk, direct = halves.get(True), halves.get(False)
        if not sdk or not direct:
            continue
        model = model_for(provider_id)
        sdk_in = sdk["usage"]["inputTokens"]
        sdk_out = sdk["usage"]["outputTokens"]
        direct_in = direct["usage"]["inputTokens"]
        direct_out = direct["usage"]["outputTokens"]
        sdk_cost = table.cost(provider_id, model, sdk_in, sdk_out)
        direct_cost = table.cost(provider_id, model, direct_in, direct_out)
        priced = sdk_cost is not None and direct_cost is not None
        # Priced from input tokens alone. Input measures the same document on
        # both sides; output does not, because the two calls are asked for
        # different things. See OUTPUT_CAVEAT.
        delta_input_cost = table.cost(provider_id, model, sdk_in - direct_in, 0)
        by_document.append(
            {
                "docId": doc_id,
                "providerId": provider_id,
                "model": model,
                "sdkInputTokens": sdk_in,
                "directInputTokens": direct_in,
                "deltaInputTokens": sdk_in - direct_in,
                "deltaInputPct": (
                    round((sdk_in - direct_in) / direct_in * 100, 1)
                    if direct_in
                    else None
                ),
                "sdkOutputTokens": sdk_out,
                "directOutputTokens": direct_out,
                "sdkCost": sdk_cost,
                "directCost": direct_cost,
                "deltaCost": (
                    sdk_cost - direct_cost if priced else None
                ),
                "deltaInputCost": delta_input_cost,
                "priced": priced,
            }
        )

    by_document.sort(key=lambda row: (row["providerId"], row["docId"]))

    by_provider: list[dict[str, Any]] = []
    for provider_id in sorted({row["providerId"] for row in by_document}):
        rows = [r for r in by_document if r["providerId"] == provider_id]
        deltas = [r["deltaInputTokens"] for r in rows]
        priced_rows = [r for r in rows if r["priced"]]
        by_provider.append(
            {
                "providerId": provider_id,
                "label": (
                    PROVIDERS[provider_id].label
                    if provider_id in PROVIDERS
                    else provider_id
                ),
                "documents": len(rows),
                "sdkInputTokens": sum(r["sdkInputTokens"] for r in rows),
                "directInputTokens": sum(r["directInputTokens"] for r in rows),
                "deltaInputTokens": sum(deltas),
                # Output differs too — the SDK asks for grounding metadata the
                # direct call does not — and output is priced several times
                # higher than input. Without this column the dollar figures
                # cannot be reconciled against the token columns, which reads as
                # an arithmetic error in the report rather than a real cost.
                "deltaOutputTokens": sum(
                    r["sdkOutputTokens"] - r["directOutputTokens"] for r in rows
                ),
                # The finding this reproduces is that the delta is a CONSTANT per
                # call, not a multiplier. Showing its spread is what lets a
                # reader see that for themselves rather than taking it on trust.
                "deltaMin": min(deltas) if deltas else None,
                "deltaMax": max(deltas) if deltas else None,
                "deltaCost": (
                    sum(r["deltaCost"] for r in priced_rows) if priced_rows else None
                ),
                # A per-document delta of $0.0003 is true and useless. The
                # decision a reader is actually making is at volume, so the mean
                # is projected to 100k documents. Linear extrapolation is only
                # legitimate here BECAUSE the delta is a constant per call — if
                # deltaMin and deltaMax diverge, this projection is not safe and
                # the spread column is the warning.
                "deltaCostPer100k": (
                    sum(r["deltaInputCost"] for r in priced_rows)
                    / len(priced_rows)
                    * 100_000
                    if priced_rows
                    else None
                ),
                "deltaCostPer100kIncludingOutput": (
                    sum(r["deltaCost"] for r in priced_rows)
                    / len(priced_rows)
                    * 100_000
                    if priced_rows
                    else None
                ),
                "priced": len(priced_rows) == len(rows) and bool(rows),
            }
        )

    scored = score_records(records, key) if key else []
    accuracy = score_summary(scored) if scored else []
    agreement_rows = agreement(records)

    # A key-derived schema gives each document its own field count, and that is
    # EXPECTED and correct within a single accuracy run — one document's key
    # entry may cover one field, another six, and that must never warn. What
    # must warn is a report that genuinely mixes a shared cost-mode schema
    # with key-derived schemas in the same set of records, because THAT mix is
    # what makes token counts incomparable. So the warning is keyed on
    # `schemaSource` ("shared" vs "answer-key"), never on the field count
    # itself — the earlier, field-count-based version of this check fired on
    # every ordinary multi-document accuracy run, since the bundled corpus's
    # key entries alone span 1 to 6 fields.
    schema_sources = {r.get("schemaSource") for r in records if r.get("schemaSource")}
    mixed_schemas = len(schema_sources) > 1

    return {
        "checkedOn": table.checked_on,
        "priceNote": table.note,
        "byDocument": by_document,
        "byProvider": by_provider,
        "unmeasurable": unmeasurable,
        "accuracy": accuracy,
        "agreement": agreement_rows,
        "agreementSummary": agreement_summary(agreement_rows),
        "mixedSchemas": mixed_schemas,
        "caveats": [
            COORDINATES_CAVEAT,
            OUTPUT_CAVEAT,
            TOKENIZER_CAVEAT,
            THINKING_CAVEAT,
        ],
    }


def _money(value: float | None) -> str:
    return "not priced" if value is None else f"${value:,.4f}"


def render_terminal(summary: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("Per document (input tokens)")
    lines.append(
        f"  {'document':28} {'provider':10} {'SDK':>9} {'direct':>9} "
        f"{'delta':>8} {'delta $ (input)':>16} {'incl. output':>14}"
    )
    for row in summary["byDocument"]:
        # `deltaInputCost`, not `deltaCost`. This table is headed "(input
        # tokens)" and every other column in it is an input-token measurement;
        # pricing the row from the output-INCLUSIVE delta put a figure of the
        # opposite sign under an input heading. A reader saw "the SDK sent 468
        # more tokens and cost two cents less" — exactly the not-like-for-like
        # reading OUTPUT_CAVEAT exists to head off. The output-inclusive figure
        # is still shown, in its own labelled column, mirroring how the
        # per-provider table already separates the two.
        lines.append(
            f"  {row['docId'][:28]:28} {row['providerId']:10} "
            f"{row['sdkInputTokens']:>9,} {row['directInputTokens']:>9,} "
            f"{row['deltaInputTokens']:>+8,} {_money(row['deltaInputCost']):>16} "
            f"{_money(row['deltaCost']):>14}"
        )
    lines.append(
        "  'delta $ (input)' prices the input-token delta, which measures the "
        "same document on both sides. 'incl. output' adds the output-token "
        "difference and is not like-for-like."
    )

    lines.append("")
    lines.append("Per provider")
    for row in summary["byProvider"]:
        spread = (
            f"{row['deltaMin']:+,} to {row['deltaMax']:+,}"
            if row["deltaMin"] is not None
            else "n/a"
        )
        per_100k = (
            f"{_money(row['deltaCostPer100k'])} per 100k docs (input)"
            if row["deltaCostPer100k"] is not None
            else "not priced"
        )
        lines.append(
            f"  {row['label']:28} {row['documents']:>3} doc(s)  "
            f"delta in {row['deltaInputTokens']:>+8,} / out "
            f"{row['deltaOutputTokens']:>+6,} "
            f"({spread} in per call)  {per_100k}"
        )
        if row["deltaCostPer100kIncludingOutput"] is not None:
            lines.append(
                f"  {'':28} including output (not like-for-like): "
                f"{_money(row['deltaCostPer100kIncludingOutput'])} per 100k docs"
            )

    if summary["unmeasurable"]:
        lines.append("")
        lines.append(
            f"{summary['unmeasurable']} cell(s) reported no usage and are "
            "excluded from every total above."
        )

    if summary["accuracy"]:
        lines.append("")
        lines.append("Accuracy (fields the answer key covers)")
        # The two halves of a provider are shown side by side, but they are not
        # guaranteed to be computed over the same documents: the harness skips
        # a direct cell whenever its SDK cell failed (there is then no captured
        # document text to send), and either half can be unscoreable on a given
        # document. Reading the two figures as a like-for-like difference when
        # they cover different document counts would be exactly the kind of
        # unmeasured claim this tool must not make, so say so rather than
        # leaving the reader to assume.
        lines.append(
            "  The two halves of a provider may be computed over different "
            "document counts when a cell was unscoreable; 'not scoreable' "
            "below shows how many."
        )
        for row in summary["accuracy"]:
            half = "with Nutrient" if row["withNutrient"] else "direct       "
            if row["accuracy"] is None:
                shown = "not scoreable"
            else:
                shown = f"{row['matched']}/{row['verified']} ({row['accuracy']:.0%})"
            lines.append(f"  {row['providerId']:10} {half}  {shown}")
            if row["unscoreable"]:
                lines.append(
                    f"  {'':10} {'':13}  {row['unscoreable']} cell(s) not scoreable"
                )
            if row["unverifiedFields"]:
                lines.append(
                    f"  {'':10} {'':13}  {row['unverifiedFields']} field(s) the key "
                    "covers but could not be confidently compared, excluded from "
                    "accuracy"
                )

    if summary["agreementSummary"]["fields"]:
        a = summary["agreementSummary"]
        lines.append("")
        # None, never 0.0 — nothing judged is not total disagreement. See
        # agreement_summary's own docstring.
        rate_shown = "not comparable" if a["rate"] is None else f"{a['rate']:.0%}"
        lines.append(
            f"Agreement: {a['agreed']}/{a['fields']} fields "
            f"({rate_shown}) — {a['disagreed']} disagreement(s), "
            f"{a['ambiguous']} ambiguous (excluded from the rate above; the "
            "comparator could not confidently judge them)"
        )
        # Filtered on `state`, never on the legacy `agree` boolean: `agree` is
        # False for BOTH disagreed and ambiguous rows, and an ambiguous row is
        # a pair the comparator explicitly could not judge — listing it here
        # would fabricate a disagreement.
        for row in summary["agreement"]:
            if row["state"] != "disagreed":
                continue
            shown = ", ".join(f"{k}={v!r}" for k, v in sorted(row["values"].items()))
            lines.append(f"  {row['docId']}.{row['field']}: {shown}")

    if summary["mixedSchemas"]:
        lines.append("")
        lines.append(
            "These records mix a shared cost-mode schema with answer-key-derived "
            "schemas, so their token counts are not comparable. Run cost and "
            "accuracy separately."
        )

    lines.append("")
    lines.append(f"Dollar figures use list prices checked {summary['checkedOn']}.")
    for caveat in summary["caveats"]:
        lines.append(f"- {caveat}")
    return "\n".join(lines)


def render_json(summary: dict[str, Any]) -> str:
    return json.dumps(summary, indent=2)


def render_html(summary: dict[str, Any]) -> str:
    """A self-contained page. No external requests, so it can be mailed on."""
    e = html_mod.escape

    # `deltaInputCost` in the headline delta $ column, `deltaCost` beside it and
    # explicitly labelled — see render_terminal for why publishing the
    # output-inclusive figure under an input-token heading misleads.
    doc_rows = "\n".join(
        f"<tr><td>{e(r['docId'])}</td><td>{e(r['providerId'])}</td>"
        f"<td class=n>{r['sdkInputTokens']:,}</td>"
        f"<td class=n>{r['directInputTokens']:,}</td>"
        f"<td class='n d'>{r['deltaInputTokens']:+,}</td>"
        f"<td class='n d'>{e(_money(r['deltaInputCost']))}</td>"
        f"<td class=n>{e(_money(r['deltaCost']))}</td></tr>"
        for r in summary["byDocument"]
    )

    prov_rows = "\n".join(
        f"<tr><td>{e(r['label'])}</td><td class=n>{r['documents']}</td>"
        f"<td class='n d'>{r['deltaInputTokens']:+,}</td>"
        f"<td class=n>{r['deltaOutputTokens']:+,}</td>"
        f"<td class=n>"
        + (
            f"{r['deltaMin']:+,} to {r['deltaMax']:+,}"
            if r["deltaMin"] is not None
            else "n/a"
        )
        + f"</td><td class='n d'>{e(_money(r['deltaCostPer100k']))}</td>"
        f"<td class=n>{e(_money(r['deltaCostPer100kIncludingOutput']))}</td></tr>"
        for r in summary["byProvider"]
    )

    caveats = "\n".join(f"<li>{e(c)}</li>" for c in summary["caveats"])
    unmeasurable = (
        f"<p class=warn>{summary['unmeasurable']} cell(s) reported no usage and "
        "are excluded from every total on this page.</p>"
        if summary["unmeasurable"]
        else ""
    )

    accuracy_section = ""
    if summary["accuracy"]:
        accuracy_rows = "\n".join(
            f"<tr><td>{e(r['providerId'])}</td>"
            f"<td>{'with Nutrient' if r['withNutrient'] else 'direct'}</td>"
            f"<td class=n>"
            + (
                "not scoreable"
                if r["accuracy"] is None
                else f"{r['matched']}/{r['verified']} ({r['accuracy']:.0%})"
            )
            + f"</td><td class=n>{r['unscoreable']}</td>"
            f"<td class=n>{r['unverifiedFields']}</td></tr>"
            for r in summary["accuracy"]
        )
        accuracy_section = f"""
<h2>Accuracy</h2>
<p class=sub>Scored against the answer key. A field the key does not cover is
never counted against a provider, and a cell the harness could not read
counts as "not scoreable" rather than as a zero. A field the key DOES cover,
but whose comparison could not be made confidently — an ambiguous date or
number format — is excluded from the accuracy figure and counted separately
below, not treated as a mismatch and not treated as missing from the key.</p>
<p class=sub>The two halves of a provider are listed side by side but may be
computed over <strong>different document counts</strong>: the harness skips a
direct cell whenever its SDK cell failed, and either half can be unscoreable on
a given document. The <em>not scoreable</em> column shows how many cells
contributed nothing, so a difference between the two halves should be read
alongside it rather than as a like-for-like comparison.</p>
<div class=scroll>
<table>
  <tr><th>provider</th><th>half</th><th class=n>accuracy</th>
      <th class=n>not scoreable</th><th class=n>not confidently compared</th></tr>
{accuracy_rows}
</table>
</div>
"""

    agreement_section = ""
    if summary["agreementSummary"]["fields"]:
        agreement_note = (
            "<h2>Where the providers disagree</h2><p class=sub>Each row is a field "
            "where two configurations returned different answers. This is the part "
            "worth dwelling on: looking at two different values, you cannot tell "
            "which is right without a citation back to the page to check — and a "
            "citation is exactly what the grounded half returns and the direct half "
            "does not.</p>"
        )
        a = summary["agreementSummary"]
        rate_shown = "not comparable" if a["rate"] is None else f"{a['rate']:.0%}"
        # Filtered on `state`, never on the legacy `agree` boolean: `agree` is
        # False for both disagreed AND ambiguous rows, and listing an ambiguous
        # row here — a pair the comparator explicitly could not judge — would
        # fabricate a disagreement in the exact artifact this feature exists to
        # produce.
        disagreement_rows = "\n".join(
            f"<tr><td>{e(row['docId'])}</td><td>{e(row['field'])}</td>"
            f"<td>{e(', '.join(f'{k}={v!r}' for k, v in sorted(row['values'].items())))}</td></tr>"
            for row in summary["agreement"]
            if row["state"] == "disagreed"
        )
        agreement_section = f"""
{agreement_note}
<p class=sub>{a['agreed']}/{a['fields']} fields agreed ({rate_shown}) — {a['disagreed']}
disagreement(s) below, and {a['ambiguous']} ambiguous field(s) excluded from the rate
because the comparator could not confidently judge them.</p>
<div class=scroll>
<table>
  <tr><th>document</th><th>field</th><th>values</th></tr>
{disagreement_rows}
</table>
</div>
"""

    mixed_note = (
        "<p class=warn>These records mix a shared cost-mode schema with "
        "answer-key-derived schemas, so their token counts are not comparable. "
        "Run cost and accuracy separately.</p>"
        if summary["mixedSchemas"]
        else ""
    )

    return f"""<!doctype html>
<meta charset="utf-8">
<title>Extraction cost comparison</title>
<style>
  :root {{ color-scheme: light dark; }}
  body {{ font: 15px/1.5 ui-sans-serif, system-ui, sans-serif; margin: 2rem auto;
         max-width: 60rem; padding: 0 1rem; }}
  h1 {{ font-size: 1.4rem; }}
  h2 {{ font-size: 1.05rem; margin-top: 2rem; }}
  table {{ border-collapse: collapse; width: 100%; margin-top: .5rem; }}
  th, td {{ border-bottom: 1px solid #8883; padding: .35rem .5rem; text-align: left; }}
  .n {{ text-align: right; font-variant-numeric: tabular-nums; }}
  .d {{ font-weight: 600; }}
  .sub {{ opacity: .75; font-size: .9rem; }}
  .warn {{ padding: .5rem .75rem; border-left: 3px solid #c80; }}
  ul {{ padding-left: 1.2rem; }}
  .scroll {{ overflow-x: auto; }}
</style>
<h1>Extraction cost, with and without the Nutrient SDK</h1>
<p class=sub>Input tokens are the measurement. Dollars are computed from list
prices checked <strong>{e(summary['checkedOn'])}</strong> and are secondary —
substitute your own negotiated rates before quoting them.</p>
{unmeasurable}

<h2>Per document</h2>
<div class=scroll>
<table>
  <tr><th>document</th><th>provider</th><th class=n>SDK input</th>
      <th class=n>direct input</th><th class=n>delta</th>
      <th class=n>delta $ (input)</th>
      <th class=n>delta $ incl. output (not like-for-like)</th></tr>
{doc_rows}
</table>
</div>
<p class=sub>The <strong>delta $ (input)</strong> column prices the input-token
delta, which measures the same document on both sides. The column beside it adds
the output-token difference and is not like-for-like — the two calls are asked
for different things, and output is priced several times higher than input.</p>

<h2>Per provider</h2>
<div class=scroll>
<table>
  <tr><th>provider</th><th class=n>docs</th><th class=n>delta input</th>
      <th class=n>delta output</th><th class=n>per-call spread</th>
      <th class=n>$ / 100k docs (input)</th>
      <th class=n>$ / 100k incl. output</th></tr>
{prov_rows}
</table>
</div>
<p class=sub>A narrow per-call spread is the point: the SDK's overhead behaves as
a constant number of tokens per call rather than a percentage of the document,
so it matters most on the smallest documents and fades on the largest. The
100k-document column is a linear projection of the measured mean, and it is only
meaningful while that spread stays narrow — if it widens, read the per-document
rows instead.</p>
{mixed_note}
{accuracy_section}
{agreement_section}

<h2>Reading this honestly</h2>
<ul>
{caveats}
</ul>
<p class=sub>{e(summary['priceNote'])}</p>
"""
