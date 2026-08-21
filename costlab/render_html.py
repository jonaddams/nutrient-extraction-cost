"""The prospect-facing report. One self-contained file, no external requests.

Split out of report.py, which keeps data shaping (`summarise`) and the terminal
renderer. Organised as four bands in document order — Answer, Accuracy, Reading
this honestly, Appendix — so a reader who stops after the first band still has
the answer.
"""

from __future__ import annotations

import html as html_mod
import re
from typing import Any

from costlab import agreement, brand
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


def _count(n: int) -> str:
    """A bare count, spelled when small — "All seven", "All 240"."""
    return _WORDS[n] if _spellable(n) else f"{n:,}"


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


def _scope(rows: list[dict[str, Any]]) -> tuple[list[str], int, int]:
    """The shape of what was compared: distinct fields, documents, rows.

    `agreementSummary["fields"]` counts ROWS, and a row is one field on one
    document. Seventeen rows can be seventeen fields on one document or one
    field on seventeen documents, and the summary alone cannot tell them
    apart. The distinction is not cosmetic: a reader shown "seventeen fields,
    seven disagreements" over a list where every disagreement names the same
    field concludes the providers agreed on the OTHER sixteen, when in truth
    there were no others and the ten agreements are that same field too.
    """
    return (
        sorted({r["field"] for r in rows}),
        len({r["docId"] for r in rows}),
        len(rows),
    )


def _scope_sentence(rows: list[dict[str, Any]]) -> str:
    """What the rate was computed over, said plainly enough to prevent the
    misreading. Names the fields while they can be named — a reader can only
    judge whether a field set is representative if they can see it."""
    fields, documents, instances = _scope(rows)
    if not fields:
        return ""
    spell = _spellable(len(fields), documents, instances)
    docs = _plural(documents, "document", spell=spell)
    if len(fields) == 1:
        return (
            f"Every comparison here is of the same single field, {fields[0]}, "
            f"once per document across {docs}. It is the only field this run "
            f"requested, so the rate describes that field and no other — the "
            f"agreements are that field too."
        )
    named = ", ".join(fields)
    if len(fields) > 8:
        named = ", ".join(fields[:8]) + f", and {_count(len(fields) - 8)} more"
    return (
        f"{_plural(instances, 'comparison', spell=spell)} across {docs}, "
        f"covering {_plural(len(fields), 'distinct field', spell=spell)}: {named}."
    )


def _money_at_scale(value: float | None) -> str:
    """Like `_money`, but 2dp at $1 or more.

    `_money`'s fixed 4dp is right for the per-document cent figures it also
    formats ($0.0037) and false precision for a per-100k-document projection
    ($367.8000) — a dollar-scale figure does not need ten-thousandths of a
    cent to be legible. `_money` itself is untouched: the appendix's
    per-document columns and tests/test_report.py's pins on them depend on
    its 4dp. This wraps it rather than duplicating its None/formatting rules.
    """
    if value is None or abs(value) < 1:
        return _money(value)
    return f"${value:,.2f}"


def _spread(dmin: int | None, dmax: int | None) -> str:
    """A per-call range, or the honest single figure when it isn't one.

    "+1,226 to +1,226" is a degenerate range that reads as an error rather
    than as the strongest fact on the page — a constant that never moved.
    """
    if dmin is None:
        return "n/a"
    if dmin == dmax:
        return f"exactly {dmin:+,} on every call"
    return f"{dmin:+,} to {dmax:+,}"


def _distinct(row: dict[str, Any]) -> int:
    """How many different answers one field actually drew.

    The comparator's own count (see agreement.py's module docstring), never a
    recomputation from the raw values here: `{None, "", "."}` is one shared
    "no answer", not three distinct strings, and re-deriving that rule a
    second time in the page is exactly how it would drift from the
    comparator's. Indexed strictly — a row from `agreement()` always carries
    this key, and a fixture that omits it describes a state the comparator
    cannot actually produce.
    """
    return row["distinct"]


def _by_provider_half(row: dict[str, Any]) -> list[tuple[str, str | None, str | None]]:
    """One entry per provider: (providerId, direct value, sdk value).

    Agreement keys are `providerId:half`, so a comparison table is a regroup of
    what is already there — no new measurement, and nothing inferred. A key
    that is not `<provider>:direct` or `<provider>:sdk` is raised on rather
    than silently dropped: this page exists to not lose measurements, and a
    half this function cannot place must not quietly vanish into two dashes
    while the row's own caption still counts it.
    """
    grouped: dict[str, dict[str, Any]] = {}
    for key, value in row["values"].items():
        provider, sep, half = key.rpartition(":")
        if not sep or half not in ("direct", "sdk"):
            raise ValueError(
                f"agreement key {key!r} is not '<provider>:direct' or "
                "'<provider>:sdk' — cannot place it in the comparison table"
            )
        grouped.setdefault(provider, {})[half] = value
    return [
        (provider, halves.get("direct"), halves.get("sdk"))
        for provider, halves in sorted(grouped.items())
    ]


def _header(summary: dict[str, Any], e) -> str:
    block = summary.get("provenance") or {}
    # Strict once `block` is known to exist: `provenance.build` always emits
    # all seven keys, so a present block answering for a missing one would be
    # a real bug worth a KeyError, not something to paper over with `.get`.
    documents = block["documentCount"] if block else None
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
        f"{e(_money_at_scale(r['deltaCostPer100k']))}</span>"
        f"<span class=figure-note>"
        + ("per 100k documents" if r["deltaCostPer100k"] is not None
           else "no list price confirmed")
        + "</span></div></div>"
        for r in rows
    )
    spread = ", ".join(
        f"{r['label']} {_spread(r['deltaMin'], r['deltaMax'])}"
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


# What each rung concedes, spelled out. "frontier" and "self-hosted" alone are
# jargon; the reader needs to see that moving down the table trades a hosted API
# for weights you run, because that trade IS the argument.
_RUNG_LABELS = {
    "frontier": "frontier · hosted API",
    "hosted": "open weights · hosted",
    "self-hosted": "open weights · self-hosted",
}


def _half_figure(half: dict[str, Any] | None) -> str:
    """One half's score, with its own denominator.

    Three outcomes that must stay visibly different: the half never ran (em
    dash), it ran and nothing was scoreable (`not scoreable`), or it has a
    figure. Rendering either of the first two as `0%` would say the model got
    everything wrong, which is a different and much worse claim than not
    knowing.
    """
    if half is None:
        return "—"
    if half["accuracy"] is None:
        return "not scoreable"
    return f"{half['matched']}/{half['verified']} ({half['accuracy']:.0%})"


def _accuracy_rungs(rows: list[dict[str, Any]], e) -> str:
    """One row per model, frontier to self-hosted.

    Organised by model rather than by provider-and-half because the comparison a
    buyer is making is between models, and the on-prem rung is the argument:
    a self-hosted model landing near a frontier one is the finding. Grouped by
    provider-and-half, the reader has to join those rows themselves.

    Each half keeps its own denominator on purpose — the two are routinely
    computed over different document counts, and one shared denominator would
    hide that while inviting a like-for-like reading.
    """
    if not rows:
        return ""
    body = "".join(
        # The model id sits under the label because the label alone is not
        # always a model: two of the four name a vendor or a place, and this
        # tool's own finding is that the overhead constant is per model, so a
        # reader quoting a figure needs to know which weights produced it.
        f"<tr><td>{e(r['label'])}"
        + (
            f"<span class=row-sub>{e(r['model'])}</span>"
            if r.get("model") and r["model"] != r["label"]
            else ""
        )
        + "</td>"
        f"<td><span class=pill>{e(_RUNG_LABELS.get(r['rung'], r['rung']))}</span></td>"
        f"<td class=n>{e(_half_figure(r['direct']))}</td>"
        f"<td class=n>{e(_half_figure(r['sdk']))}</td></tr>"
        for r in rows
    )
    return f"""
<div class=scroll id="accuracy-by-model">
<table>
<thead><tr><th>model</th><th>runs on</th><th class=n>direct call</th>
    <th class=n>with Nutrient SDK</th></tr></thead>
{body}
</table>
</div>
<p class=standfirst>Scored against the answer key: a field the key does not
cover is never counted against a model, and a cell the harness could not read
counts as <em>not scoreable</em> rather than as a zero. The two halves of a row
may be computed over <strong>different document counts</strong>, so each carries
its own denominator — read a difference between them alongside those, not as a
like-for-like comparison. Full per-half detail, including what was excluded as
not confidently compared, is in
<a href="#appendix-accuracy">the accuracy panel</a>.</p>
"""


def _accuracy_band(summary: dict[str, Any], e) -> str:
    a = summary["agreementSummary"]
    rungs = _accuracy_rungs(summary.get("accuracyByModel", []), e)
    # Either half of this band can be empty: a cost-mode run has nothing scored,
    # and a single-configuration run has nothing to compare. The band is only
    # absent when both are.
    if not a["fields"] and not rungs:
        return ""
    judged = a["agreed"] + a["disagreed"]
    if "rate" in a:
        rate = "not comparable" if a["rate"] is None else f"{a['rate']:.0%}"
    else:
        rate = f"{a['agreed'] / judged:.0%}" if judged else "not comparable"
    excluded = a.get("ambiguous", 0) + a.get("unanswered", 0)

    shown, _ = representative_disagreements(summary["agreement"], limit=1)
    # Counted across EVERY row, not only the disagreeing ones. Counting
    # disagreements alone made a run where everything agreed — the best possible
    # outcome — announce "Zero configurations", which is both false and absurd.
    configurations = max(
        (len(r["values"]) for r in summary["agreement"]), default=0
    )

    scope_fields, scope_documents, _ = _scope(summary["agreement"])
    scope_sentence = _scope_sentence(summary["agreement"])
    spell_h2 = _spellable(
        configurations, len(scope_fields), scope_documents, a["disagreed"]
    )
    # "seventeen fields" for one field seen on seventeen documents is the
    # misreading this whole disclosure exists to stop, so the headline counts
    # the fields and the documents separately rather than counting rows.
    headline_scope = (
        f"{_plural(len(scope_fields), 'field', spell=spell_h2)} across "
        f"{_plural(scope_documents, 'document', spell=spell_h2)}"
    )
    # "No disagreements" reads as a clean bill of health -- true when
    # everything was judged and agreed, false and misleading when nothing
    # could be judged at all (every row ambiguous or unanswered). The two
    # cases must not share a headline.
    if judged == 0:
        headline_tail = "nothing could be judged"
        accent_note = "nothing could be judged"
    else:
        headline_tail = (
            "no disagreements" if not a["disagreed"]
            else _plural(a["disagreed"], "disagreement", spell=spell_h2)
        )
        accent_note = f"of judged fields agreed — {a['agreed']} of {judged}"

    in_full = ""
    if shown:
        row = shown[0]
        # The comparator's own normalisation, not `str(a) == str(b)` — the
        # latter calls "Acme Corp." and "acme corp" a disagreement the
        # comparator scored as agreement, accusing the SDK of a difference
        # that was only ever a typography difference. Both an absent value
        # (None, "", ".") and its raw form are handled through the same
        # lookup, so a blank answer reads as the em dash it is rather than an
        # unexplained empty box.
        normalised = agreement.normalise_values(row["values"])
        cells = ""
        for provider, direct, sdk in _by_provider_half(row):
            cells += f"<div class=p>{e(provider)}</div>"
            direct_norm = normalised.get(f"{provider}:direct", agreement._ABSENT)
            sdk_norm = normalised.get(f"{provider}:sdk", agreement._ABSENT)
            direct_shown = "—" if direct_norm is agreement._ABSENT else str(direct)
            sdk_shown = "—" if sdk_norm is agreement._ABSENT else str(sdk)
            if direct_norm == sdk_norm:
                # One box across both columns rather than the same string
                # printed twice — the reader should see agreement, not repetition.
                cells += (
                    f"<div class='val agree'>{e(direct_shown)}"
                    f"<span class=same-note>both halves identical</span></div>"
                )
            else:
                cells += (
                    f"<div class='val diff'>{e(direct_shown)}</div>"
                    f"<div class='val diff'>{e(sdk_shown)}</div>"
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

    def _count_cell(row: dict[str, Any]) -> str:
        """"N of M configurations differed" when nothing agreed, else the count.

        Every configuration returning something different is a stronger
        statement than "N distinct answers", and it is the row a reader should
        look at first — so it says so rather than leaving them to notice that
        the two numbers happen to match.
        """
        distinct, total = _distinct(row), len(row["values"])
        if total <= 1:
            # One configuration cannot differ from itself — "1 of 1
            # configurations differed" is false, not just ungrammatical.
            noun = "distinct answer" if distinct == 1 else "distinct answers"
            return f"<strong>{distinct}</strong> {noun}"
        if distinct == total:
            return f"<strong>{distinct} of {total}</strong> configurations differed"
        return f"<strong>{distinct}</strong> distinct answers"

    ranked_rows = "\n".join(
        f"<tr><td class=doc>{e(r['docId'])}</td>"
        f"<td class=field>{e(r['field'])}</td>"
        f"<td class=count>{_count_cell(r)}</td></tr>"
        for r in ranked
    )
    all_ranked = ""
    if ranked:
        # "All one, by spread" is ungrammatical -- a single item is not "all"
        # of anything worth saying so.
        count_phrase = "The one" if len(ranked) == 1 else f"All {_count(len(ranked))}"
        all_ranked = f"""
<p class=eyebrow>{count_phrase}, by spread</p>
<div class=spread>
<table>
<thead><tr><th>document</th><th>field</th><th>distinct answers</th></tr></thead>
{ranked_rows}
</table>
</div>
<p class=standfirst>Every value each configuration returned is in
<a href="#appendix-c">Appendix C</a>.</p>
"""

    # The agreement sentence carries the scope disclosure that stops "one field
    # on seventeen documents" reading as "seventeen fields". It is the h2 when
    # agreement is all this band has, and a standfirst under the accuracy
    # headline when it is not -- but it is never dropped.
    agreement_sentence = (
        f"{_plural(configurations, 'configuration', spell=spell_h2).capitalize()}, "
        f"{headline_scope}, {headline_tail}"
    )
    agreement_block = ""
    if a["fields"]:
        agreement_block = f"""
<p class=standfirst>{e(scope_sentence)}</p>
<p class=standfirst>{e(AGREEMENT_FRAMING)}</p>
<div class=cards>
<div class='card accent'><span class=figure-xl>{e(rate)}</span>
<span class=figure-note>{accent_note}</span></div>
<div class=card><span class=figure-xl>{a['disagreed']}</span>
<span class=figure-note>fields where configurations differed</span></div>
<div class=card><span class=figure-xl>{excluded}</span>
<span class=figure-note>fields excluded as unjudgeable or unanswered</span></div>
</div>
{in_full}
{all_ranked}
"""

    if rungs:
        # Scored accuracy leads. Agreement is context for it, not a substitute:
        # two models can agree and both be wrong, so a page that opens on an
        # agreement rate has buried the figure a buyer is actually buying.
        scored = summary["accuracyByModel"]
        heading = (
            f"{_plural(len(scored), 'model', spell=_spellable(len(scored))).capitalize()} "
            "scored against the answer key"
        )
        eyebrow = "02 — Accuracy"
        lead = rungs
        follow = (
            f"<p class=eyebrow>Where the configurations disagree</p>"
            f"<p class=standfirst>{e(agreement_sentence)}</p>{agreement_block}"
            if agreement_block
            else ""
        )
    else:
        # Nothing was scored, so the band cannot claim accuracy. Saying
        # "Accuracy" over an agreement rate is the mislabel this restructure
        # exists to remove -- it must not survive in the keyless case either.
        heading = agreement_sentence
        eyebrow = "02 — Agreement"
        lead = ""
        follow = agreement_block

    # Joined rather than interpolated on their own lines: either slot can be
    # empty, and two empty slots left three blank lines in the shipped page.
    body = "\n".join(part for part in (lead, follow) if part.strip())
    return f"""
<section class=band id="accuracy">
<p class=eyebrow>{eyebrow}</p>
<h2>{heading}</h2>
{body}
</section>
"""


def _code_flags(escaped: str) -> str:
    """Set `--flag` names in code, without letting anything else through.

    The price note is prose from prices.json, so it is escaped first; this only
    ever wraps a run of `--word` that survived escaping. Escaping then
    substituting a known-safe pattern keeps the inserted tags the only markup
    that can reach the page.
    """
    return re.sub(r"(--[a-z][a-z-]*)", r"<code>\1</code>", escaped)


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
<div class=price-note>
<p class=eyebrow>On the prices used</p>
<p>{_code_flags(e(summary['priceNote']))}</p>
</div>
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
        meta = (
            f"{provider['label']} · {_plural(provider['documents'], 'document')} · "
            f"{each:+,} input tokens each"
        )
        if provider["deltaCostPer100k"] is None:
            meta += " · not priced"
        # Nested and collapsed: opening A should show which models were measured
        # and what each one's constant was, not 51 rows at once.
        doc_groups += (
            f"<details class=group><summary>"
            f"<span class=group-id>{e(provider['providerId'])}</span>"
            f"<span class=group-meta>{e(meta)}</span></summary>"
            f"{_doc_table(rows)}</details>"
        )
    if not doc_groups:
        doc_groups = _doc_table(summary["byDocument"])

    prov_rows = "\n".join(
        f"<tr><td>{e(r['label'])}</td><td class=n>{r['documents']}</td>"
        f"<td class='n d'>{r['deltaInputTokens']:+,}</td>"
        f"<td class=n>{r['deltaOutputTokens']:+,}</td>"
        f"<td class=n>{e(_spread(r['deltaMin'], r['deltaMax']))}</td>"
        f"<td class='n d'>{e(_money_at_scale(r['deltaCostPer100k']))}</td>"
        f"<td class=n>{e(_money_at_scale(r['deltaCostPer100kIncludingOutput']))}</td></tr>"
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
<p class=sub>{e(_scope_sentence(summary['agreement']))}</p>
<div class=scroll>
<table>
  <tr><th>document</th><th>field</th><th>values</th></tr>
{disagreement_rows}
</table>
</div>
</details>
"""

    return f"""
<p class=eyebrow id="appendix">Appendix</p>
<h2>Everything the summary is derived from</h2>

<details class=panel id="appendix-a" open>
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

<details class=panel id="appendix-d" open>
<summary>D · Price table</summary>
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
