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
    generalising the constant to a sibling model, then a pointer down to the
    full per-document detail — safe to add only now that Task 8 gives
    `#appendix` a target to land on.
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
<p class=sub>Full per-document detail is in the
<a href="#appendix">appendix</a>.</p>
</section>
"""


AGREEMENT_FRAMING = (
    "Each row is a field where two configurations returned different answers. "
    "Looking at two values, you cannot tell which is right without a citation "
    "back to the page — and a citation is exactly what the grounded half "
    "returns and the direct half does not. Agreement is agreement, not "
    "correctness: two models can agree and both be wrong."
)


def representative_disagreements(
    rows: list[dict[str, Any]], limit: int = 3
) -> tuple[list[dict[str, Any]], int]:
    """A few disagreements worth reading, and how many were left out.

    Deterministic by construction: most distinct values, then the widest
    character span between the shortest and longest value, then docId, then
    field — two disagreements from the same document differing only by field
    must not fall back to input order, which this function's caller does not
    control. The appendix always carries the complete list and the summary
    always states the omitted count — a rule that happened to hide the least
    flattering disagreement would be precisely the quiet dishonesty this tool
    exists to remove.
    """
    disagreed = [r for r in rows if r.get("state") == "disagreed"]

    def key(row: dict[str, Any]) -> tuple[int, int, str, str]:
        rendered = [str(v) for v in row["values"].values()]
        span = max(map(len, rendered)) - min(map(len, rendered)) if rendered else 0
        return (-len(set(rendered)), -span, row["docId"], row["field"])

    ordered = sorted(disagreed, key=key)
    return ordered[:limit], max(len(ordered) - limit, 0)


def _accuracy_band(summary: dict[str, Any], e) -> str:
    """Band 2: the agreement rate and a representative sample of disagreements.

    Reuses `agreementSummary["rate"]` when present rather than recomputing
    agreed/judged — this project has already fixed six defects that were
    exactly two definitions of the same number disagreeing with each other.
    Guarded on `"rate" in a`, never on truthiness, because a measured rate of
    0.0 is real and must not be treated as absent.
    """
    a = summary["agreementSummary"]
    if not a["fields"]:
        return ""
    judged = a["agreed"] + a["disagreed"]
    if "rate" in a:
        rate = "n/a" if a["rate"] is None else f"{a['rate']:.0%}"
    else:
        rate = f"{a['agreed'] / judged:.0%}" if judged else "n/a"
    chosen, omitted = representative_disagreements(summary["agreement"])
    rows = "\n".join(
        f"<tr><td>{e(r['docId'])}</td><td>{e(r['field'])}</td>"
        f"<td class=v>{e(', '.join(f'{k}={v!r}' for k, v in sorted(r['values'].items())))}</td></tr>"
        for r in chosen
    )
    more = (
        f'<p class=sub>{omitted} more disagreement(s) are listed in full in the '
        '<a href="#disagreements">appendix</a>.</p>'
        if omitted
        else ""
    )
    return f"""
<h2>Where the models disagree</h2>
<p class=sub>{e(AGREEMENT_FRAMING)}</p>
<p class=sub><strong>{a['agreed']}/{judged} judged fields agreed ({rate})</strong>
— {a['disagreed']} disagreement(s). Fields nobody answered are excluded from
that rate.</p>
<table>
<thead><tr><th>document</th><th>field</th><th>what each returned</th></tr></thead>
{rows}
</table>
{more}
"""


def _honesty_band(summary: dict[str, Any], e) -> str:
    """Band 3: the caveats, kept out of any collapsible element.

    A caveat a reader has to click for is a caveat we did not really make, so
    this band renders in the document flow — no <details>, no accordion —
    above the appendix built by `_appendix`. This used to be rendered a second
    time, verbatim, in a legacy "Reading this honestly" section further down
    the page; Task 8 deleted that duplicate once this band covered the same
    ground, so there is now exactly one copy of every caveat on the page.
    """
    caveats = "\n".join(f"<li>{e(c)}</li>" for c in summary["caveats"])
    notices = []
    if summary["unmeasurable"]:
        retried = (
            f" {summary['retried']} of them because the SDK retried: their "
            "tokens are the sum of several attempts, so the difference between "
            "the two halves is not a per-call figure."
            if summary.get("retried")
            else ""
        )
        notices.append(
            f"<p class=warn>{summary['unmeasurable']} cell(s) are not "
            f"measurable and are excluded from every total on this page."
            f"{retried}</p>"
        )
    if summary["mixedSchemas"]:
        notices.append(
            "<p class=warn>These records mix a shared cost-mode schema with "
            "answer-key schemas, so their token counts are not comparable with "
            "each other.</p>"
        )
    return f"""
<h2>Reading this honestly</h2>
{"".join(notices)}
<ul class=sub>
{caveats}
</ul>
<p class=sub>{e(summary['priceNote'])}</p>
"""


def _appendix(summary: dict[str, Any], e) -> str:
    """Band 4: everything the summary bands are derived from.

    Every table here used to open the page. Each one now sits behind a
    <details> with a stable anchor, so a reader who wants the 51-row wall can
    get to it in one click while everyone else stops at Band 3. The markup and
    wording of each moved section are carried across verbatim from the
    pre-Task-8 page — this is a relocation, not a rewrite, and
    `tests/test_report.py` pins nine reader-facing strings across these
    sections specifically so a future edit here cannot quietly reword one.
    """
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

    mixed_note = (
        "<p class=warn>These records mix a shared cost-mode schema with "
        "answer-key-derived schemas, so their token counts are not comparable. "
        "Run cost and accuracy separately.</p>"
        if summary["mixedSchemas"]
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
<details id="accuracy">
<summary>Accuracy, scored against the answer key</summary>
{mixed_note}
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
</details>
"""

    disagreements_section = ""
    if summary["agreementSummary"]["fields"]:
        agreement_note = (
            "<p class=sub>Each row is a field "
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
        disagreements_section = f"""
<details id="disagreements">
<summary>Every disagreement</summary>
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
</details>
"""

    return f"""
<h2 id="appendix">Appendix</h2>
<p class=sub>Everything the summary above is derived from.</p>

<details id="per-document">
<summary>Per document (input tokens)</summary>
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
</details>

<details id="per-provider">
<summary>Per provider</summary>
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
</details>
{accuracy_section}
{disagreements_section}

<details id="prices">
<summary>Price table</summary>
<p class=sub>List prices checked {e(summary['checkedOn'])}. Replace them with
your negotiated rates using <code>--prices</code>.</p>
</details>
"""


def render(summary: dict[str, Any]) -> str:
    """A self-contained page. No external requests, so it can be mailed on."""
    e = html_mod.escape

    logo = brand.asset("nutrient-logo.svg")
    styles = brand.asset("theme.css") + "\n" + brand.asset("print.css")

    return f"""<!doctype html>
<html lang=en>
<meta charset=utf-8>
<title>Extraction cost and accuracy — Nutrient SDK</title>
<style>
{styles}
</style>
<div class=wrap>
{logo}
<h1>What document extraction costs, with and without the Nutrient SDK</h1>
{_provenance_table(summary.get("provenance"), e)}
{_answer_band(summary, e)}
{_accuracy_band(summary, e)}
{_honesty_band(summary, e)}
{_appendix(summary, e)}
</div>
</html>
"""
