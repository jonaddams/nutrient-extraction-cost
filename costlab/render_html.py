"""The prospect-facing report. One self-contained file, no external requests.

Split out of report.py, which keeps data shaping (`summarise`) and the terminal
renderer. Organised as four bands in document order — Answer, Accuracy, Reading
this honestly, Appendix — so a reader who stops after the first band still has
the answer.
"""

from __future__ import annotations

import html as html_mod
from typing import Any

from costlab import brand
from costlab.report import _money

# Measured on this corpus: 468 input tokens on Qwen3-VL, 479 on Qwen3.5 9B,
# 1,226 on Claude Sonnet 5. The overhead is a constant per call, and the
# constant is per model — not per vendor and not per tokenizer generation. A
# different model, including a sibling from the same family, is a new
# measurement, so the figure never transfers across the "per model" line.
PER_MODEL_NOTE = (
    "The overhead is a constant per call, and the constant is per model — not "
    "per vendor and not per tokenizer generation. Measured on this corpus it "
    "was 468 input tokens on Qwen3-VL, 479 on Qwen3.5 9B and 1,226 on Claude "
    "Sonnet 5. A different model, including a sibling from the same family, is "
    "a new measurement."
)


def _provenance_table(block: dict[str, Any] | None, e) -> str:
    """The run's provenance, named plainly enough to be checked by a reader.

    Returns "" when no provenance was recorded — an older or synthetic summary
    should not render a table of blanks.
    """
    if not block:
        return ""
    models = ", ".join(
        f"{m['providerId']} / {m['model']}" for m in block["models"]
    ) or "not recorded"
    rows = [
        ("Documents run", f"{block['documentCount']} from {block['corpusName']}"),
        ("Models compared", models),
        ("Credentials used", ", ".join(block["keySources"])),
        ("Run", block["runDate"]),
        ("Price table checked", block["priceTableDate"]),
        ("Tool version", block["toolVersion"]),
    ]
    body = "\n".join(
        f"<tr><td>{e(k)}</td><td>{e(str(v))}</td></tr>" for k, v in rows
    )
    return f"<table class=prov>{body}</table>"


def _answer_band(summary: dict[str, Any], e) -> str:
    """Band 1: the answer, before any of the supporting detail.

    One tile per model with its per-call constant and cost per 100k, then a
    table with the per-call spread, then the sentence that keeps a reader from
    generalising the constant to a sibling model.
    """
    tiles = "\n".join(
        f"<div class=tile><div class=k>{e(r['label'])}</div>"
        f"<div class=v>{r['deltaInputTokens'] // max(r['documents'], 1):+,} tokens</div>"
        f"<div class=k>{e(_money(r['deltaCostPer100k']))} per 100k docs</div></div>"
        for r in summary["byProvider"]
    )
    prov_rows = "\n".join(
        f"<tr><td>{e(r['label'])}</td><td class=n>{r['documents']}</td>"
        f"<td class='n d'>"
        + (
            f"{r['deltaMin']:+,} to {r['deltaMax']:+,}"
            if r["deltaMin"] is not None
            else "n/a"
        )
        + f"</td><td class='n d'>{e(_money(r['deltaCostPer100k']))}</td></tr>"
        for r in summary["byProvider"]
    )
    return f"""
<section class=answer>
<p class=supertitle>Nutrient SDK overhead</p>
<div class=tiles>
{tiles}
</div>
<table>
<thead><tr><th>model</th><th>documents measured</th><th>per-call spread</th>
<th>cost per 100k docs (input)</th></tr></thead>
{prov_rows}
</table>
<p class=sub>{e(PER_MODEL_NOTE)}</p>
</section>
"""


def render(summary: dict[str, Any]) -> str:
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
    retried_note = (
        f" {summary['retried']} of them because the SDK retried: their tokens "
        "are the sum of several attempts, so the difference between the two "
        "halves is not a per-call figure."
        if summary.get("retried")
        else ""
    )
    unmeasurable = (
        f"<p class=warn>{summary['unmeasurable']} cell(s) are not measurable "
        f"and are excluded from every total on this page.{retried_note}</p>"
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
<p class=sub>{a['agreed']}/{a['agreed'] + a['disagreed']} judged fields agreed
({rate_shown}) — {a['disagreed']} disagreement(s) below. Excluded from that rate:
{a['ambiguous']} field(s) the comparator could not confidently judge, and
{a.get('unanswered', 0)} that no provider answered at all — nobody answered, so there is
nothing to agree about. {a['fields']} field(s) were considered in total.</p>
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

    logo = brand.asset("nutrient-logo.svg")
    styles = brand.asset("theme.css") + "\n" + brand.asset("print.css")

    return f"""<!doctype html>
<html lang=en>
<meta charset=utf-8>
<title>Extraction cost and accuracy — Nutrient SDK</title>
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
<style>
{styles}
</style>
<div class=wrap>
{logo}
<h1>What document extraction costs, with and without the Nutrient SDK</h1>
{_provenance_table(summary.get("provenance"), e)}
{_answer_band(summary, e)}

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
</div>
</html>
"""
