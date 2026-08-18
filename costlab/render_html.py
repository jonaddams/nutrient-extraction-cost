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
from costlab.report import (
    COORDINATES_CAVEAT,
    OUTPUT_CAVEAT,
    THINKING_CAVEAT,
    TOKENIZER_CAVEAT,
    _money,
)

# No figures here: this sentence is read on every run, including a prospect's
# own, and the tables above are the only place on the page allowed to state a
# measured number. See tests/test_render_html.py's
# test_the_constant_is_labelled_as_per_model for the guard that keeps a future
# edit from reintroducing one.
PER_MODEL_NOTE = (
    "The overhead is a constant per call, and the constant is per model — not "
    "per vendor, and not per tokenizer generation. A different model, "
    "including a sibling from the same family, is a new measurement: the "
    "figures above do not transfer to it."
)


CAVEAT_TITLES = {
    COORDINATES_CAVEAT: "The delta is not waste",
    OUTPUT_CAVEAT: "Output tokens are not comparable",
    TOKENIZER_CAVEAT: "Tokens do not compare across providers",
    THINKING_CAVEAT: "Thinking tokens are billed as output",
}


_WORDS = (
    "zero one two three four five six seven eight nine ten eleven twelve "
    "thirteen fourteen fifteen sixteen seventeen eighteen nineteen twenty"
).split()


def _spellable(*counts: int) -> bool:
    """True only when EVERY count in one sentence can be a word."""
    return all(0 <= n < len(_WORDS) for n in counts)


def _plural(n: int, one: str, many: str | None = None, *, spell: bool = False) -> str:
    """A counted noun. `spell` writes small numbers as words.

    The design's prose reads "Seventeen documents, three models" — words in
    sentences, digits in tables and figures. Spelling is cosmetic, so it is
    opt-in and never reaches a measurement: cards, tiles and table cells always
    print the numeral.

    Use `_spellable` to decide for a whole sentence rather than per number.
    Spelling one count and not its neighbour ("17 documents, three models")
    reads worse than either choice made consistently.
    """
    count = _WORDS[n] if spell and n < len(_WORDS) else f"{n:,}"
    return f"{count} {one}" if n == 1 else f"{count} {many or one + 's'}"


def _distinct(row: dict[str, Any]) -> int:
    """How many different answers one field actually drew."""
    return len({str(v) for v in row["values"].values()})


def _by_provider_half(row: dict[str, Any]) -> list[tuple[str, str | None, str | None]]:
    """One entry per provider: (providerId, direct value, sdk value).

    Agreement keys are `providerId:half`, so a comparison table is a regroup of
    what is already there — no new measurement, and nothing inferred.
    """
    grouped: dict[str, dict[str, Any]] = {}
    for key, value in row["values"].items():
        provider, _, half = key.rpartition(":")
        grouped.setdefault(provider or key, {})[half] = value
    return [
        (provider, halves.get("direct"), halves.get("sdk"))
        for provider, halves in sorted(grouped.items())
    ]


def _header(summary: dict[str, Any], e) -> str:
    block = summary.get("provenance") or {}
    documents = block.get("documentCount")
    models = summary["byProvider"]

    # Every figure in the standfirst is this run's. The design's own copy said
    # "Seventeen documents, three models" — true of the run it was drawn from,
    # false of a prospect's, and asserting it would repeat the defect this
    # project has now fixed nine times.
    if documents and models:
        spell = _spellable(documents, len(models))
        stand = (
            f"{_plural(documents, 'document', spell=spell).capitalize()}, "
            f"{_plural(len(models), 'model', spell=spell)}, "
            "each run twice: once through the Nutrient SDK and once as a direct "
            "model call. The SDK's token overhead is a constant per call, and "
            "the two halves do not return the same thing."
        )
    else:
        stand = (
            "Each document is run twice: once through the Nutrient SDK and once "
            "as a direct model call. The SDK's token overhead is a constant per "
            "call, and the two halves do not return the same thing."
        )

    cells = ""
    if block:
        model_list = " · ".join(
            f"{m['providerId']} / {m['model']}" for m in block.get("models", [])
        )
        # (label, value, monospace?, spans two columns?) — machine-shaped values
        # are set in mono, the way the design does; the two long facts span two
        # columns so the six cells tile the four-column grid exactly.
        facts = [
            ("Documents run", f"{block['documentCount']} from {block['corpusName']}", False, False),
            ("Run", block["runDate"], True, False),
            ("Price table checked", block["priceTableDate"], True, False),
            ("Tool version", f"nutrient-extraction-cost {block['toolVersion']}", True, False),
            ("Models compared", model_list or "not recorded", True, True),
            ("Credentials used", " · ".join(block["keySources"]), True, True),
        ]
        cells = "\n".join(
            f"<div class='prov-cell{' wide' if wide else ''}'>"
            f"<span class=prov-k>{e(k)}</span>"
            f"<span class='prov-v{' mono' if mono else ''}'>{e(str(v))}</span></div>"
            for k, v, mono, wide in facts
        )
        cells = f"<div class=prov-grid>{cells}</div>"

    return f"""
<header>
<p class=eyebrow>Extraction cost and accuracy · measured run</p>
<h1>What document extraction costs, with and without the Nutrient SDK</h1>
<p class=standfirst>{e(stand)}</p>
</header>
{cells}
"""


NO_DELTA_NOTE = (
    "No document produced both halves of the comparison, so there is no delta "
    "to report. The appendix lists what each cell returned."
)


def _cost_band(summary: dict[str, Any], e) -> str:
    rows = summary["byProvider"]
    if not rows:
        return f"""
<section class=band id="cost">
<p class=eyebrow>01 — Cost</p>
<h2>No paired measurement in this run</h2>
<p class=standfirst>{e(NO_DELTA_NOTE)}</p>
</section>
"""

    cards = "\n".join(
        f"<div class=card><span class=card-model>{e(r['label'])}</span>"
        f"<div class=card-figure><span class=figure-lg>"
        f"{round(r['deltaInputTokens'] / max(r['documents'], 1)):+,}</span>"
        f"<span class=figure-note>input tokens per document</span></div>"
        f"<div class='card-figure split'><span class=figure-md>"
        f"{e(_money(r['deltaCostPer100k']))}</span>"
        f"<span class=figure-note>"
        + ("per 100k documents" if r["deltaCostPer100k"] is not None
           else "no list price confirmed")
        + "</span></div></div>"
        for r in rows
    )
    spread = ", ".join(
        f"{r['label']} {r['deltaMin']:+,} to {r['deltaMax']:+,}"
        for r in rows
        if r["deltaMin"] is not None
    )
    return f"""
<section class=band id="cost">
<p class=eyebrow>01 — Cost</p>
<h2>The SDK adds a fixed number of input tokens per call</h2>
<p class=standfirst>The overhead is the same on the smallest document and the
largest. It is a constant per model, not a percentage of the document, so it
matters most on short documents and fades on long ones. Per-call spread across
this run: {e(spread or "not measurable")}.</p>
<div class=cards>
{cards}
</div>
<p class=standfirst>{e(PER_MODEL_NOTE)} Per-document detail is in
<a href="#appendix-a">Appendix A</a>; provider totals in
<a href="#appendix-b">Appendix B</a>.</p>
</section>
"""


AGREEMENT_FRAMING = (
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
    field. The appendix always carries the complete list and the summary always
    states the omitted count — a rule that happened to hide the least
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
    a = summary["agreementSummary"]
    if not a["fields"]:
        return ""
    judged = a["agreed"] + a["disagreed"]
    if "rate" in a:
        rate = "not comparable" if a["rate"] is None else f"{a['rate']:.0%}"
    else:
        rate = f"{a['agreed'] / judged:.0%}" if judged else "not comparable"
    excluded = a.get("ambiguous", 0) + a.get("unanswered", 0)

    shown, _ = representative_disagreements(summary["agreement"], limit=1)
    configurations = max(
        (len(r["values"]) for r in summary["agreement"] if r.get("state") == "disagreed"),
        default=0,
    )

    spell_h2 = _spellable(configurations, a["fields"], a["disagreed"])

    in_full = ""
    if shown:
        row = shown[0]
        cells = ""
        for provider, direct, sdk in _by_provider_half(row):
            if direct is not None and sdk is not None and str(direct) == str(sdk):
                cells += (
                    f"<div class=p>{e(provider)}</div>"
                    f"<div class=v>{e(str(direct))}</div>"
                    f"<div class='v same'>both halves identical</div>"
                )
            else:
                cells += (
                    f"<div class=p>{e(provider)}</div>"
                    f"<div class=v>{e('—' if direct is None else str(direct))}</div>"
                    f"<div class=v>{e('—' if sdk is None else str(sdk))}</div>"
                )
        in_full = f"""
<p class=eyebrow>One disagreement in full</p>
<article class=cmp>
<div class=cmp-head>
<span class=cmp-doc>{e(row['docId'])}</span>
<span class=pill>{e(row['field'])}</span>
<span class=figure-note>{_distinct(row)} distinct answers across {_plural(len(row['values']), 'configuration')}</span>
</div>
<div class=cmp-grid>
<div class=h></div><div class=h>Direct call</div><div class=h>With Nutrient SDK</div>
{cells}
</div>
</article>
"""

    ranked, _ = representative_disagreements(summary["agreement"], limit=10_000)
    ranked_rows = "\n".join(
        f"<tr><td>{e(r['docId'])}</td><td>{e(r['field'])}</td>"
        f"<td class=n>{_distinct(r)} distinct answers</td></tr>"
        for r in ranked
    )
    all_ranked = ""
    if ranked:
        all_ranked = f"""
<p class=eyebrow>All {len(ranked)}, by spread</p>
<div class=scroll>
<table>
<thead><tr><th>document</th><th>field</th><th class=n>distinct answers</th></tr></thead>
{ranked_rows}
</table>
</div>
<p class=standfirst>Every value each configuration returned is in
<a href="#appendix-c">Appendix C</a>.</p>
"""

    return f"""
<section class=band id="agreement">
<p class=eyebrow>02 — Accuracy</p>
<h2>{_plural(configurations, 'configuration', spell=spell_h2).capitalize()}, {_plural(a['fields'], 'field', spell=spell_h2)}, {_plural(a['disagreed'], 'disagreement', spell=spell_h2)}</h2>
<p class=standfirst>{e(AGREEMENT_FRAMING)}</p>
<div class=cards>
<div class='card accent'><span class=figure-xl>{e(rate)}</span>
<span class=figure-note>of judged fields agreed — {a['agreed']} of {judged}</span></div>
<div class=card><span class=figure-xl>{a['disagreed']}</span>
<span class=figure-note>fields where configurations differed</span></div>
<div class=card><span class=figure-xl>{excluded}</span>
<span class=figure-note>fields excluded as unjudgeable or unanswered</span></div>
</div>
{in_full}
{all_ranked}
</section>
"""


def _caveats_band(summary: dict[str, Any], e) -> str:
    items = ""
    for n, caveat in enumerate(summary["caveats"], start=1):
        title = CAVEAT_TITLES.get(caveat, "Read this before quoting a figure")
        items += (
            f"<div class=caveat><span class=caveat-n>{n:02d}</span>"
            f"<h3>{e(title)}</h3><p>{e(caveat)}</p></div>"
        )

    notices = ""
    if summary["unmeasurable"]:
        retried = (
            f" {summary['retried']} of them because the SDK retried: their "
            "tokens are the sum of several attempts, so the difference between "
            "the two halves is not a per-call figure."
            if summary.get("retried")
            else ""
        )
        notices += (
            f"<p class=warn>{summary['unmeasurable']} cell(s) are not "
            f"measurable and are excluded from every total on this page."
            f"{retried}</p>"
        )
    if summary["mixedSchemas"]:
        notices += (
            "<p class=warn>These records mix a shared cost-mode schema with "
            "answer-key schemas, so their token counts are not comparable with "
            "each other.</p>"
        )

    return f"""
<section class=band id="caveats">
<p class=eyebrow>03 — Caveats</p>
<h2>Reading this honestly</h2>
<p class=standfirst>{_plural(len(summary['caveats']), 'thing', spell=True).capitalize()} that would make
the numbers say something they do not say.</p>
{notices}
<div class=cards>
{items}
</div>
<p class=eyebrow>On the prices used</p>
<p class=standfirst>{e(summary['priceNote'])}</p>
</section>
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
    def _doc_table(rows: list[dict[str, Any]]) -> str:
        body = "\n".join(
            f"<tr><td>{e(r['docId'])}</td><td>{e(r['providerId'])}</td>"
            f"<td class=n>{r['sdkInputTokens']:,}</td>"
            f"<td class=n>{r['directInputTokens']:,}</td>"
            f"<td class='n d'>{r['deltaInputTokens']:+,}</td>"
            f"<td class='n d'>{e(_money(r['deltaInputCost']))}</td>"
            f"<td class=n>{e(_money(r['deltaCost']))}</td></tr>"
            for r in rows
        )
        return f"""<div class=scroll>
<table>
  <tr><th>document</th><th>provider</th><th class=n>SDK input</th>
      <th class=n>direct input</th><th class=n>delta</th>
      <th class=n>delta $ (input)</th>
      <th class=n>delta $ incl. output (not like-for-like)</th></tr>
{body}
</table>
</div>"""

    # Grouped by model, because the constant is per model: a reader comparing
    # two providers' rows in one undivided table is comparing tokenizers.
    doc_groups = ""
    for provider in summary["byProvider"]:
        rows = [
            r for r in summary["byDocument"]
            if r["providerId"] == provider["providerId"]
        ]
        if not rows:
            continue
        each = round(provider["deltaInputTokens"] / max(provider["documents"], 1))
        doc_groups += (
            f"<p class=group-head>{e(provider['label'])} · "
            f"{_plural(provider['documents'], 'document')} · "
            f"{each:+,} input tokens each</p>\n{_doc_table(rows)}"
        )
    if not doc_groups:
        doc_groups = _doc_table(summary["byDocument"])

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
<details class=panel id="appendix-accuracy">
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
<details class=panel id="appendix-c">
<summary>C · Every disagreement, in full</summary>
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

<details class=panel id="appendix-a">
<summary>A · Per document, input tokens</summary>
{doc_groups}
<p class=sub>The <strong>delta $ (input)</strong> column prices the input-token
delta, which measures the same document on both sides. The column beside it adds
the output-token difference and is not like-for-like — the two calls are asked
for different things, and output is priced several times higher than input.</p>
</details>

<details class=panel id="appendix-b">
<summary>B · Per provider</summary>
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

<details class=panel id="prices">
<summary>Price table</summary>
<p class=sub>List prices checked {e(summary['checkedOn'])}. Replace them with
your negotiated rates using <code>--prices</code>.</p>
</details>
"""


CONTENT_NOTICE = (
    "This file includes values extracted from the documents that were run, so "
    "handle it the way you would handle those documents. Nothing was sent to "
    "Nutrient: the tool has no telemetry and no Nutrient endpoint."
)


def _footer(summary: dict[str, Any], e) -> str:
    """States what the file contains and what produced it.

    No redaction mode: a report with its disagreements blacked out cannot make
    the argument it exists to make, so this says plainly that the file carries
    document content instead of hiding it.
    """
    block = summary.get("provenance") or {}
    version = block.get("toolVersion") or "not recorded"
    return f"""
<footer>
<p>{e(CONTENT_NOTICE)}</p>
<p>Measured by nutrient-extraction-cost {e(version)} · list prices checked
{e(summary['checkedOn'])} · Nutrient, nutrient.io</p>
</footer>
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
<div class=logo>{logo}</div>
{_header(summary, e)}
{_cost_band(summary, e)}
{_accuracy_band(summary, e)}
{_caveats_band(summary, e)}
<section class=band id="appendix-band">
{_appendix(summary, e)}
</section>
{_footer(summary, e)}
</div>
</html>
"""
