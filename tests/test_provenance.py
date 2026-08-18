from costlab import provenance


def _rec(doc, pid):
    return {"docId": doc, "providerId": pid, "withNutrient": True}


def test_build_names_the_corpus_and_counts_distinct_documents():
    out = provenance.build(
        corpus_dir="/some/where/acme-invoices",
        records=[_rec("a", "bedrock"), _rec("a", "openai"), _rec("b", "bedrock")],
        models={"bedrock": "qwen3-vl", "openai": "gpt-x"},
        credential_envs=["BEDROCK_API_KEY"],
        run_started="2026-08-18T09:30:00-04:00",
        checked_on="2026-08-14",
    )
    assert out["corpusName"] == "acme-invoices"
    assert out["documentCount"] == 2


def test_the_corpus_path_never_appears():
    """A prospect's directory path is theirs, and ours is noise. Name only."""
    out = provenance.build(
        corpus_dir="/Users/someone/private/q3-claims",
        records=[_rec("a", "bedrock")],
        models={"bedrock": "qwen3-vl"},
        credential_envs=[],
        run_started="2026-08-18T09:30:00-04:00",
        checked_on="2026-08-14",
    )
    assert out["corpusName"] == "q3-claims"
    assert "/Users/" not in repr(out)


def test_the_bundled_corpus_is_labelled_as_ours():
    """A report on our sample documents must never read as a report on theirs."""
    out = provenance.build(
        corpus_dir="/anything/costlab/corpus",
        records=[_rec("a", "bedrock")],
        models={"bedrock": "qwen3-vl"},
        credential_envs=[],
        run_started="2026-08-18T09:30:00-04:00",
        checked_on="2026-08-14",
    )
    assert out["corpusName"] == "Nutrient sample corpus"


def test_models_are_listed_per_provider_in_the_run():
    out = provenance.build(
        corpus_dir="/x/docs",
        records=[_rec("a", "bedrock"), _rec("a", "anthropic")],
        models={"bedrock": "qwen3-vl", "anthropic": "claude-sonnet-5", "openai": "unused"},
        credential_envs=[],
        run_started="2026-08-18T09:30:00-04:00",
        checked_on="2026-08-14",
    )
    listed = {m["providerId"]: m["model"] for m in out["models"]}
    assert listed == {"bedrock": "qwen3-vl", "anthropic": "claude-sonnet-5"}


def test_key_sources_name_the_variable_and_never_a_value():
    out = provenance.build(
        corpus_dir="/x/docs",
        records=[_rec("a", "bedrock")],
        models={"bedrock": "qwen3-vl"},
        credential_envs=["BEDROCK_API_KEY", "NUTRIENT_LICENSE_KEY"],
        run_started="2026-08-18T09:30:00-04:00",
        checked_on="2026-08-14",
    )
    assert out["keySources"] == ["BEDROCK_API_KEY (set)", "NUTRIENT_LICENSE_KEY (set)"]


def test_missing_fields_say_so_rather_than_guessing():
    """A report that infers its own provenance is the same defect class as one
    that infers a token count."""
    out = provenance.build(
        corpus_dir=None,
        records=[],
        models={},
        credential_envs=[],
        run_started="",
        checked_on=None,
    )
    assert out["corpusName"] == provenance.UNKNOWN
    assert out["runDate"] == provenance.UNKNOWN
    assert out["priceTableDate"] == provenance.UNKNOWN
    assert out["documentCount"] == 0
    assert out["keySources"] == [provenance.UNKNOWN]


def test_tool_version_is_a_string_and_never_raises():
    assert isinstance(provenance.tool_version(), str)
    assert provenance.tool_version()
