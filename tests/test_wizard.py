"""The no-argument wizard: `costlab` with nothing after it.

Whoever runs this tool needs their own API keys, which makes them technical, so
the wizard's job is not hand-holding — it is making the cost of the next keypress
visible before it is spent. Every call it is about to make is billed to the
reader, so it states the exact call count, names every provider it is about to
bill, and refuses to invent a dollar figure it cannot support.

No test here touches a network. The wizard is pure stdlib and takes its input,
output, environment and price table as arguments.
"""

from pathlib import Path

import pytest

from costlab import wizard
from costlab.prices import PriceTable


class Asker:
    """Canned answers, and a record of what was asked."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.prompts = []

    def __call__(self, prompt):
        self.prompts.append(prompt)
        if not self.answers:
            raise AssertionError(f"wizard asked more than expected: {prompt!r}")
        return self.answers.pop(0)


class Emitter:
    def __init__(self):
        self.lines = []

    def __call__(self, line=""):
        self.lines.append(str(line))

    @property
    def text(self):
        return "\n".join(self.lines)


def _priced():
    return PriceTable(
        checked_on="2026-08-14",
        rates={
            "bedrock": {
                "qwen.qwen3-vl-235b-a22b-instruct": {
                    "inputPerMTok": 0.53,
                    "outputPerMTok": 2.66,
                }
            }
        },
    )


def _corpus_of(n, *, only="costlab/corpus"):
    """A loader that behaves like the real one.

    `load_corpus` ends in `corpus_dir.iterdir()`, which raises FileNotFoundError
    on a path that does not exist — so a fake that cheerfully returns documents
    for any path describes a state the real code cannot produce, and the
    re-ask-on-bad-path branch would never be exercised.
    """

    def load(path):
        if str(path) != only:
            raise FileNotFoundError(f"No such file or directory: '{path}'")
        return [object()] * n

    return load


def _env(**kw):
    return kw


def test_no_credentials_at_all_stops_before_asking_to_spend():
    """Nothing can be measured, so the wizard must not walk someone through
    four questions and then fail."""
    ask = Asker()
    emit = Emitter()
    # Even the local runtime is excluded here by pointing at no providers.
    out = wizard.run(
        ask=ask,
        emit=emit,
        env=_env(),
        table=_priced(),
        load_corpus=_corpus_of(3),
        providers=[],
    )
    assert out is None
    assert ask.prompts == [], "must not ask anything it cannot act on"
    assert "no providers" in emit.text.lower()


def test_it_offers_only_the_providers_whose_credential_is_set():
    ask = Asker("", "", "", "y")
    emit = Emitter()
    out = wizard.run(
        ask=ask,
        emit=emit,
        env=_env(BEDROCK_API_KEY="x"),
        table=_priced(),
        load_corpus=_corpus_of(2),
    )
    assert out is not None
    # local needs no credential, bedrock's is set, the other two are not.
    assert set(out["providers"]) == {"bedrock", "local"}
    assert "anthropic" not in emit.text
    assert "openai" not in emit.text


def test_a_blank_provider_answer_means_every_one_detected():
    out = wizard.run(
        ask=Asker("", "", "", "y"),
        emit=Emitter(),
        env=_env(BEDROCK_API_KEY="x"),
        table=_priced(),
        load_corpus=_corpus_of(2),
    )
    assert set(out["providers"]) == {"bedrock", "local"}


def test_a_subset_can_be_chosen_which_is_how_a_costly_provider_is_excluded():
    """The reason this question exists: a provider you do not want billed today
    has to be removable without editing the environment."""
    out = wizard.run(
        ask=Asker("bedrock", "", "", "y"),
        emit=Emitter(),
        env=_env(BEDROCK_API_KEY="x"),
        table=_priced(),
        load_corpus=_corpus_of(2),
    )
    assert out["providers"] == ["bedrock"]


def test_an_unknown_provider_is_re_asked_rather_than_silently_dropped():
    """Silently ignoring a typo would run a different, cheaper set than the
    reader asked for and report it as what they asked for."""
    ask = Asker("bedrok", "bedrock", "", "", "y")
    emit = Emitter()
    out = wizard.run(
        ask=ask,
        emit=emit,
        env=_env(BEDROCK_API_KEY="x"),
        table=_priced(),
        load_corpus=_corpus_of(2),
    )
    assert out["providers"] == ["bedrock"]
    assert "bedrok" in emit.text


def test_a_missing_documents_folder_is_re_asked():
    ask = Asker("", "/definitely/not/here", "", "", "y")
    emit = Emitter()
    out = wizard.run(
        ask=ask,
        emit=emit,
        env=_env(BEDROCK_API_KEY="x"),
        table=_priced(),
        load_corpus=_corpus_of(2),
    )
    assert out is not None
    assert "not" in emit.text.lower()


def test_the_exact_call_count_is_stated():
    """documents x cells, computed, not estimated. bedrock has both halves and
    local has both, so two providers over three documents is twelve calls."""
    emit = Emitter()
    wizard.run(
        ask=Asker("", "", "", "y"),
        emit=emit,
        env=_env(BEDROCK_API_KEY="x"),
        table=_priced(),
        load_corpus=_corpus_of(3),
    )
    assert "12 call" in emit.text


def test_a_hosted_provider_with_no_list_price_is_named_as_unquotable():
    """A zero would assert the calls are free. Anthropic is absent from this
    table, and it bills per token, so its spend is real but unquotable — the
    warning that matters when a budget is nearly spent."""
    emit = Emitter()
    wizard.run(
        ask=Asker("", "", "", "y"),
        emit=emit,
        env=_env(ANTHROPIC_API_KEY="x"),
        table=_priced(),
        load_corpus=_corpus_of(2),
    )
    assert "$0.00" not in emit.text
    assert "no list price" in emit.text.lower()
    assert "cannot be quoted" in emit.text.lower()


def test_a_self_hosted_runtime_is_not_described_as_unquotable_spend():
    """Distinct from the above: a local runtime has no per-token price because no
    vendor is billing, not because our table is missing a rate. Lumping the two
    together tells someone watching their spend to worry about the one line that
    cannot add to it."""
    emit = Emitter()
    wizard.run(
        ask=Asker("local", "", "", "y"),
        emit=emit,
        env=_env(ANTHROPIC_API_KEY="x"),
        table=_priced(),
        load_corpus=_corpus_of(2),
    )
    text = emit.text.lower()
    assert "your own hardware" in text
    assert "cannot be quoted" not in text
    assert "$0.00" not in emit.text


def test_it_never_quotes_a_total_it_cannot_know():
    """Spend depends on how long the documents are, which is unknown until they
    are read. Printing a confident total before the run would be the exact
    unsupported figure this project keeps removing from the report."""
    emit = Emitter()
    wizard.run(
        ask=Asker("", "", "", "y"),
        emit=emit,
        env=_env(BEDROCK_API_KEY="x"),
        table=_priced(),
        load_corpus=_corpus_of(2),
    )
    text = emit.text.lower()
    assert "depends on" in text
    assert "estimated total" not in text


def test_anything_other_than_yes_cancels():
    for reply in ("", "n", "no", "later", "Y E S"):
        out = wizard.run(
            ask=Asker("", "", "", reply),
            emit=Emitter(),
            env=_env(BEDROCK_API_KEY="x"),
            table=_priced(),
            load_corpus=_corpus_of(2),
        )
        assert out is None, f"{reply!r} must not start a billed run"


def test_yes_returns_the_chosen_settings():
    out = wizard.run(
        ask=Asker("", "", "", "yes"),
        emit=Emitter(),
        env=_env(BEDROCK_API_KEY="x"),
        table=_priced(),
        load_corpus=_corpus_of(2),
    )
    assert out["confirmed"] is True
    assert out["documents"] == 2
    assert isinstance(out["corpus"], (str, Path))


def test_the_rates_it_shows_carry_the_date_they_were_checked():
    """A dollar figure without the date it was priced on is the report's oldest
    rule; the wizard states prices too, so it inherits the rule."""
    emit = Emitter()
    wizard.run(
        ask=Asker("", "", "", "y"),
        emit=Emitter() and emit,
        env=_env(BEDROCK_API_KEY="x"),
        table=_priced(),
        load_corpus=_corpus_of(2),
    )
    assert "2026-08-14" in emit.text


# --- Opening the finished report -----------------------------------------
#
# Spec B's last clause was "runs, opens the report". The report on disk is the
# deliverable; opening it is a convenience, so nothing here may turn a completed,
# paid-for run into a failure.


def test_the_report_is_opened_as_a_file_url():
    from costlab import runner

    opened = []
    runner._open_report(
        Path("/tmp/somewhere/report.html"), lambda *a: None, opener=opened.append
    )
    # Asserted by property, not as a literal: the path is resolved, and on macOS
    # /tmp is a symlink to /private/tmp, so a hardcoded URL tests the platform
    # rather than the code.
    assert len(opened) == 1
    assert opened[0].startswith("file:///")
    assert opened[0].endswith("/somewhere/report.html")


def test_a_path_with_spaces_is_still_a_valid_url():
    """A prospect's folder is called "Q3 Claims", not "q3-claims"."""
    from costlab import runner

    opened = []
    runner._open_report(
        Path("/tmp/Q3 Claims/report.html"), lambda *a: None, opener=opened.append
    )
    assert opened[0].endswith("/Q3%20Claims/report.html"), opened
    assert " " not in opened[0]


def test_a_failing_opener_does_not_sink_a_finished_run():
    """Headless box, no browser, locked-down desktop. The calls are already paid
    for and the file already written — raising here would report the whole run as
    a failure over a convenience."""
    from costlab import runner

    said = []

    def explode(url):
        raise OSError("no display")

    runner._open_report(Path("/tmp/x/report.html"), said.append, opener=explode)
    assert any("/tmp/x/report.html" in line for line in said)


def test_an_opener_that_finds_no_browser_says_where_the_file_is():
    """webbrowser.open returns False rather than raising when it cannot find a
    browser, which is easy to treat as success."""
    from costlab import runner

    said = []
    runner._open_report(Path("/tmp/x/report.html"), said.append, opener=lambda url: False)
    assert any("/tmp/x/report.html" in line for line in said)


def test_the_wizard_asks_for_the_report_to_be_opened():
    from costlab import runner

    argvs = runner._wizard_argvs(
        {"providers": ["bedrock"], "corpus": "costlab/corpus", "mode": "cost",
         "answers": None, "out": "out"}
    )
    assert "--open" in argvs[-1]


def test_a_flag_driven_run_does_not_open_a_browser_by_default():
    """Scripted and CI runs must not launch anything. Opening is opt-in, and the
    wizard is the thing that opts in."""
    from costlab import runner

    assert runner._build_parser().parse_args(["--corpus", "x"]).open is False
    assert runner._build_parser().parse_args(["--open"]).open is True


def test_bare_argv_routes_to_the_wizard():
    """`costlab` with nothing after it. Checked against real argv rather than a
    parsed namespace, because every flag has a default and a namespace cannot
    tell "unset" from "set to the default"."""
    from costlab import runner

    called = {}

    def fake(**kw):
        called["yes"] = True
        return None

    original = runner.wizard.run
    runner.wizard.run = fake
    try:
        assert runner.main([]) == 1
    finally:
        runner.wizard.run = original
    assert called.get("yes"), "bare invocation must go through the wizard"


def test_a_cancelled_wizard_never_reaches_the_run():
    """The failure that would matter most: cancelling and being billed anyway."""
    from costlab import runner

    original_wizard, original_run = runner.wizard.run, runner.run

    def exploding_run(*a, **kw):
        raise AssertionError("a cancelled wizard must not call any provider")

    runner.wizard.run = lambda **kw: None
    runner.run = exploding_run
    try:
        assert runner.main([]) == 1
    finally:
        runner.wizard.run, runner.run = original_wizard, original_run


def test_a_keyboard_interrupt_at_a_prompt_cancels_cleanly():
    """Ctrl-C at "proceed?" must not read as a yes."""

    def ask(prompt):
        raise KeyboardInterrupt

    out = wizard.run(
        ask=ask,
        emit=Emitter(),
        env=_env(BEDROCK_API_KEY="x"),
        table=_priced(),
        load_corpus=_corpus_of(2),
    )
    assert out is None


# --- What to measure: cost, accuracy, or both ----------------------------
#
# The wizard could only ever produce a cost run: it re-entered `main` with
# --providers/--corpus/--yes/--open and never --mode or --answers, so the one
# artifact it could not build was the cost+accuracy report that is now the
# committed example. Choosing "both" doubles the calls a run makes, which is
# exactly the kind of decision this wizard exists to put in front of someone
# before it is billed — so the choice is asked, and priced per run.


def _scoreable_of(n):
    """A stand-in for "how many of these documents can the key score".

    Takes the same two things the real one needs — where the documents are and
    which key to score against — so a test can describe a corpus the bundled
    key only partly covers.
    """

    def scoreable(corpus_path, answers_path):
        return n

    return scoreable


def test_blank_measures_cost_which_is_the_cheaper_run():
    """The default must be the run that spends least. Someone hitting enter
    through the wizard has not asked to double their bill."""
    out = wizard.run(
        ask=Asker("", "", "", "y"),
        emit=Emitter(),
        env=_env(BEDROCK_API_KEY="x"),
        table=_priced(),
        load_corpus=_corpus_of(2),
    )
    assert out["mode"] == "cost"


def test_the_wizard_asks_what_to_measure():
    ask = Asker("", "", "", "y")
    wizard.run(
        ask=ask,
        emit=Emitter(),
        env=_env(BEDROCK_API_KEY="x"),
        table=_priced(),
        load_corpus=_corpus_of(2),
    )
    asked = " ".join(ask.prompts).lower()
    assert "cost" in asked and "accuracy" in asked and "both" in asked


def test_choosing_accuracy_records_the_mode():
    out = wizard.run(
        ask=Asker("", "", "accuracy", "", "y"),
        emit=Emitter(),
        env=_env(BEDROCK_API_KEY="x"),
        table=_priced(),
        load_corpus=_corpus_of(2),
        scoreable=_scoreable_of(2),
    )
    assert out["mode"] == "accuracy"


def test_an_unrecognised_mode_is_re_asked_rather_than_defaulted():
    """The same rule the provider question follows: quietly running something
    other than what was typed, then reporting it as what was typed, is the
    failure this tool exists to remove."""
    ask = Asker("", "", "acuracy", "accuracy", "", "y")
    emit = Emitter()
    out = wizard.run(
        ask=ask,
        emit=emit,
        env=_env(BEDROCK_API_KEY="x"),
        table=_priced(),
        load_corpus=_corpus_of(2),
        scoreable=_scoreable_of(2),
    )
    assert out["mode"] == "accuracy"
    assert "acuracy" in emit.text


def test_cost_mode_never_asks_for_an_answer_key():
    """A cost run does not score, so a key question there is a question about
    nothing."""
    ask = Asker("", "", "", "y")
    wizard.run(
        ask=ask,
        emit=Emitter(),
        env=_env(BEDROCK_API_KEY="x"),
        table=_priced(),
        load_corpus=_corpus_of(2),
    )
    assert not any("answer key" in p.lower() for p in ask.prompts)


def test_a_blank_answer_key_means_the_bundled_one():
    out = wizard.run(
        ask=Asker("", "", "accuracy", "", "y"),
        emit=Emitter(),
        env=_env(BEDROCK_API_KEY="x"),
        table=_priced(),
        load_corpus=_corpus_of(2),
        scoreable=_scoreable_of(2),
    )
    assert out["answers"] is None


def test_a_supplied_answer_key_is_carried_into_the_run():
    out = wizard.run(
        ask=Asker("", "", "accuracy", "mine.csv", "y"),
        emit=Emitter(),
        env=_env(BEDROCK_API_KEY="x"),
        table=_priced(),
        load_corpus=_corpus_of(2),
        scoreable=_scoreable_of(2),
    )
    assert out["answers"] == "mine.csv"


def test_accuracy_prices_only_the_documents_the_key_can_score():
    """`rescope_to_key` drops any document the key has no entry for. Quoting the
    whole corpus would overstate the run the reader is about to authorise."""
    emit = Emitter()
    out = wizard.run(
        ask=Asker("", "", "accuracy", "", "y"),
        emit=emit,
        env=_env(BEDROCK_API_KEY="x"),
        table=_priced(),
        load_corpus=_corpus_of(17),
        scoreable=_scoreable_of(3),
    )
    # bedrock and local are both detected here and both have a grounded half,
    # so four calls per document — over the 3 scoreable ones, not all 17.
    assert out["calls"] == 12
    assert "3 of 17" in emit.text


def test_a_corpus_the_key_cannot_score_at_all_is_refused_not_scheduled():
    """Today this exits 2 after the wizard has already promised a run. The
    wizard knows enough to say so before asking for a yes."""
    emit = Emitter()
    out = wizard.run(
        ask=Asker("", "", "accuracy", "", "cost", "y"),
        emit=emit,
        env=_env(BEDROCK_API_KEY="x"),
        table=_priced(),
        load_corpus=_corpus_of(17),
        scoreable=_scoreable_of(0),
    )
    assert "nothing an accuracy run could score" in emit.text
    assert out["mode"] == "cost", "it must fall back to a question, not a run"


def test_both_states_each_run_and_the_combined_total():
    emit = Emitter()
    out = wizard.run(
        ask=Asker("", "", "both", "", "y"),
        emit=emit,
        env=_env(BEDROCK_API_KEY="x"),
        table=_priced(),
        load_corpus=_corpus_of(10),
        scoreable=_scoreable_of(10),
    )
    assert out["mode"] == "both"
    # 10 documents x 4 calls, twice over: a cost run and an accuracy run.
    assert out["calls"] == 80
    assert "40 call" in emit.text, "each run's own count"
    assert "80 call" in emit.text, "and the total they add up to"


def test_both_says_out_loud_that_it_is_two_runs():
    """The doubling is the whole reason this question exists. It must be stated,
    not left to be inferred from a larger number."""
    emit = Emitter()
    wizard.run(
        ask=Asker("", "", "both", "", "y"),
        emit=emit,
        env=_env(BEDROCK_API_KEY="x"),
        table=_priced(),
        load_corpus=_corpus_of(10),
        scoreable=_scoreable_of(10),
    )
    text = emit.text.lower()
    assert "two runs" in text or "two separate runs" in text


def test_both_still_quotes_no_total_in_dollars():
    """The rule the wizard was built on survives the larger number."""
    emit = Emitter()
    wizard.run(
        ask=Asker("", "", "both", "", "y"),
        emit=emit,
        env=_env(BEDROCK_API_KEY="x"),
        table=_priced(),
        load_corpus=_corpus_of(10),
        scoreable=_scoreable_of(10),
    )
    assert "estimated total" not in emit.text.lower()
    assert "depends on" in emit.text.lower()


# --- The wizard's answers as commands ------------------------------------
#
# The wizard re-enters the same parser a typed command uses, so it cannot become
# a second, differently-behaved way to start a run. "Both" is therefore not a
# new code path through the runner — it is three ordinary commands in order: a
# cost run, an accuracy run, and a --join of the two.


def _chosen(**kw):
    base = {
        "providers": ["bedrock"],
        "corpus": "costlab/corpus",
        "mode": "cost",
        "answers": None,
        "out": "out",
        "confirmed": True,
    }
    base.update(kw)
    return base


def test_a_cost_wizard_run_is_one_command():
    from costlab import runner

    argvs = runner._wizard_argvs(_chosen(mode="cost"))
    assert len(argvs) == 1
    assert argvs[0][argvs[0].index("--mode") + 1] == "cost"
    assert "--open" in argvs[0]


def test_an_accuracy_wizard_run_carries_its_key():
    from costlab import runner

    argvs = runner._wizard_argvs(_chosen(mode="accuracy", answers="mine.csv"))
    assert len(argvs) == 1
    assert argvs[0][argvs[0].index("--mode") + 1] == "accuracy"
    assert argvs[0][argvs[0].index("--answers") + 1] == "mine.csv"


def test_the_bundled_key_is_left_unstated_rather_than_guessed_at():
    """--mode accuracy already defaults to the bundled key. Passing a path we
    invented would hardcode its location into the wizard."""
    from costlab import runner

    argvs = runner._wizard_argvs(_chosen(mode="accuracy"))
    assert "--answers" not in argvs[0]


def test_both_is_a_cost_run_an_accuracy_run_and_a_join():
    from costlab import runner

    argvs = runner._wizard_argvs(_chosen(mode="both"))
    assert len(argvs) == 3
    assert [a[a.index("--mode") + 1] for a in argvs[:2]] == ["cost", "accuracy"]
    assert "--join" in argvs[2]


def test_the_two_runs_of_both_write_to_different_directories():
    """One --out for both would have the accuracy run overwrite the cost run's
    records, and the join would then be a run joined with itself."""
    from costlab import runner

    argvs = runner._wizard_argvs(_chosen(mode="both"))
    first = argvs[0][argvs[0].index("--out") + 1]
    second = argvs[1][argvs[1].index("--out") + 1]
    assert first != second


def test_the_join_reads_exactly_the_two_directories_just_written():
    from costlab import runner

    argvs = runner._wizard_argvs(_chosen(mode="both"))
    cost_out = argvs[0][argvs[0].index("--out") + 1]
    acc_out = argvs[1][argvs[1].index("--out") + 1]
    joined = argvs[2][argvs[2].index("--join") + 1].split(",")
    assert joined == [cost_out, acc_out]


def test_only_the_last_command_of_both_opens_a_browser():
    """Three commands must not open three tabs. The joined report is the
    deliverable; the two runs behind it are intermediate."""
    from costlab import runner

    argvs = runner._wizard_argvs(_chosen(mode="both"))
    assert [("--open" in a) for a in argvs] == [False, False, True]


def test_a_custom_key_reaches_the_join_so_the_report_scores_against_it():
    """The joined report is the one someone reads. Scoring it against the
    bundled key when the run used a different one would report the wrong
    numbers as the answer."""
    from costlab import runner

    argvs = runner._wizard_argvs(_chosen(mode="both", answers="mine.csv"))
    assert argvs[2][argvs[2].index("--answers") + 1] == "mine.csv"


def test_main_runs_every_wizard_command_in_order():
    from costlab import runner

    seen = []
    original_wizard, original_main = runner.wizard.run, runner.main
    runner.wizard.run = lambda **kw: _chosen(mode="both")
    try:

        def fake_main(argv=None):
            if argv == []:
                return original_main([])
            seen.append(argv)
            return 0

        runner.main = fake_main
        assert fake_main([]) == 0
    finally:
        runner.wizard.run, runner.main = original_wizard, original_main
    assert len(seen) == 3, "a both-run is three commands"
    assert "--join" in seen[-1]


def test_a_failed_run_stops_the_sequence_before_the_join():
    """Joining a directory the failed run never wrote would report a partial
    measurement as a complete one."""
    from costlab import runner

    seen = []
    original_wizard, original_main = runner.wizard.run, runner.main
    runner.wizard.run = lambda **kw: _chosen(mode="both")
    try:

        def fake_main(argv=None):
            if argv == []:
                return original_main([])
            seen.append(argv)
            return 2

        runner.main = fake_main
        assert fake_main([]) == 2
    finally:
        runner.wizard.run, runner.main = original_wizard, original_main
    assert len(seen) == 1, "the second command must not run after a failure"
    assert seen[0][seen[0].index("--mode") + 1] == "cost", "it stopped at the first"


def test_offering_accuracy_without_a_way_to_count_it_says_so():
    """A caller that offers accuracy but injects no counter is a programming
    error. It must not quietly price the whole corpus — that is exactly the
    overstatement the count exists to prevent."""
    with pytest.raises(TypeError, match="scoreable"):
        wizard.run(
            ask=Asker("", "", "accuracy", ""),
            emit=Emitter(),
            env=_env(BEDROCK_API_KEY="x"),
            table=_priced(),
            load_corpus=_corpus_of(2),
        )
