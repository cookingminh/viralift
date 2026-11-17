"""End-to-end smoke tests for the Streamlit UI.

Each test runs the real app script with streamlit.testing's AppTest and checks
that a workspace or wizard step renders without an exception. The data-backed
tests use the git-ignored sample genomes in app/data/ and tblastn; they skip
when either is missing. Logging is stubbed, alias edits go to a temporary copy
and saved references to tmp_path, so the tests never touch logs/ or app/config/.
"""
import json
import shutil
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

import ui.reference_library
import ui.services
import ui.stages.resolve
from app.src.alias.alias_bootstrap import build_seed_alias_config_from_ref
from app.src.features.ref_loader import prepare_reference_features
from app.src.io.genbank_parser import load_genbank_records, load_single_genbank
from app.src.pipeline import PipelineConfig, run_pipeline
from ui.state import REGISTRY_PATH


ROOT = Path(__file__).resolve().parents[3]
APP = str(ROOT / "ui" / "streamlit_app.py")
PRRS = ROOT / "app" / "data" / "PRRS"
REF_FILE = PRRS / "PRRS_ref_test.gb"
# One annotated record (direct path) and one bare genome (tblastn path).
QUERY_FILES = [PRRS / "PRRS_MT746146_Anno.gb", PRRS / "PRRS_PP946131_noAnno.gb"]

requires_sample_data = pytest.mark.skipif(
    shutil.which("tblastn") is None
    or not all(path.exists() for path in [REF_FILE, *QUERY_FILES]),
    reason="needs tblastn and the PRRS sample genomes in app/data/PRRS",
)


@pytest.fixture(autouse=True)
def _quiet_side_effects(monkeypatch, tmp_path):
    monkeypatch.setattr(ui.reference_library, "REFERENCE_DIR", tmp_path / "references")
    for name in ("log_run_start", "log_run_complete", "log_alias_added", "log_canonical_added"):
        monkeypatch.setattr(ui.services, name, lambda *args, **kwargs: None)
    monkeypatch.setattr(ui.stages.resolve, "log_session_decisions", lambda *args, **kwargs: None)
    monkeypatch.delenv("VIRALIFT_LLM_ENABLED", raising=False)


def _app(**state) -> AppTest:
    at = AppTest.from_file(APP, default_timeout=180)
    for key, value in state.items():
        at.session_state[key] = value
    return at


def _assert_clean(at: AppTest) -> None:
    assert not at.exception, [item.value for item in at.exception]


@pytest.fixture(scope="module")
def prrs_run():
    ref_record = load_single_genbank(REF_FILE)
    query_records = [record for path in QUERY_FILES for record in load_genbank_records(path)]
    ref_features, ref_feature_type, alias_config_path, virus_name, alias_lookup = (
        prepare_reference_features(
            ref_record=ref_record,
            alias_config_arg=None,
            alias_registry_arg=str(REGISTRY_PATH),
        )
    )
    result = run_pipeline(
        ref_record=ref_record,
        query_records=query_records,
        ref_features=ref_features,
        ref_feature_type=ref_feature_type,
        alias_lookup=alias_lookup,
        config=PipelineConfig(catch_record_errors=True),
    )
    return {
        "ref_record": ref_record,
        "query_records": query_records,
        "ref_features": ref_features,
        "ref_feature_type": ref_feature_type,
        "alias_config_path": alias_config_path,
        "virus_name": virus_name,
        "alias_lookup": alias_lookup,
        "canonical_list": sorted(set(alias_lookup.values())),
        "all_results": result.all_results,
    }


def test_setup_step_renders_with_continue_disabled():
    at = _app()
    at.run()
    _assert_clean(at)
    continue_button = next(button for button in at.button if button.label == "Continue")
    assert continue_button.disabled


@pytest.mark.parametrize("mode", ["Data crawler", "Alias manager"])
def test_workspace_renders(mode):
    at = _app(app_mode=mode)
    at.run()
    _assert_clean(at)


def test_top_bar_switches_workspace():
    at = _app()
    at.run()
    at.button(key="mode_alias_manager").click().run()
    _assert_clean(at)
    assert at.session_state.app_mode == "Alias manager"


def test_footer_shows_the_image_version(monkeypatch):
    # CI stamps the image with these; the page footer is where users read them.
    monkeypatch.setenv("VIRALIFT_VERSION", "9.9.9")
    monkeypatch.setenv("VIRALIFT_COMMIT", "abcdef1234")
    at = _app()
    at.run()
    _assert_clean(at)
    page_html = " ".join(element.proto.body for element in at.get("html"))
    assert "ViraLift 9.9.9 · abcdef1" in page_html


@pytest.mark.parametrize("mode", ["Run pipeline", "Data crawler", "Alias manager"])
def test_guide_opens_on_every_workspace(mode):
    at = _app(app_mode=mode)
    at.run()
    at.button(key="vl_guide").click().run()
    _assert_clean(at)


@requires_sample_data
@pytest.mark.parametrize("view", ["Features", "Records", "Export"])
def test_results_views_render(prrs_run, view):
    at = _app(stage="results", results_view=view, **prrs_run)
    at.run()
    _assert_clean(at)


@requires_sample_data
def test_results_guide_opens(prrs_run):
    at = _app(stage="results", **prrs_run)
    at.run()
    at.button(key="vl_guide").click().run()
    _assert_clean(at)


@requires_sample_data
def test_results_reference_name_mode_renders(prrs_run):
    at = _app(stage="results", use_ref_names=True, results_view="Export", **prrs_run)
    at.run()
    _assert_clean(at)


@requires_sample_data
def test_virus_review_and_bootstrap_render(prrs_run):
    seed = build_seed_alias_config_from_ref(
        ref_record=prrs_run["ref_record"],
        ref_features=prrs_run["ref_features"],
        virus_name="Test virus",
    )
    shared = {key: prrs_run[key] for key in ("ref_record", "query_records", "ref_features", "ref_feature_type")}

    at = _app(stage="virus_review", virus_review_metadata=["porcine test virus"], virus_review_guess="Test virus", **shared)
    at.run()
    _assert_clean(at)

    at = _app(stage="bootstrap_alias", bootstrap_alias_config=seed, bootstrap_virus_name="Test virus", **shared)
    at.run()
    _assert_clean(at)


@requires_sample_data
def test_review_step_maps_a_name_and_runs_to_results(prrs_run, tmp_path):
    config_copy = tmp_path / "prrsv_alias.json"
    shutil.copy(prrs_run["alias_config_path"], config_copy)
    original_config = Path(prrs_run["alias_config_path"]).read_text(encoding="utf-8")

    unknown = {
        "glycoprotein five": {
            "records": [prrs_run["query_records"][0].id],
            "candidates": ["glycoprotein five", "gp-five envelope"],
        }
    }
    state = {**prrs_run, "alias_config_path": config_copy, "all_results": None}
    at = _app(stage="resolve", unknown_names=unknown, unknown_ref_names=[], **state)
    at.run()
    _assert_clean(at)

    at.selectbox(key="resolve_glycoprotein five").set_value("ORF5").run()
    _assert_clean(at)
    next(button for button in at.button if button.label == "Run annotation").click().run()
    _assert_clean(at)

    assert at.session_state.stage == "results"
    assert at.session_state.resolver == {"glycoprotein five": "ORF5", "gp-five envelope": "ORF5"}
    saved = json.loads(config_copy.read_text(encoding="utf-8"))
    assert "glycoprotein five" in saved["canonical_names"]["ORF5"]
    assert "gp-five envelope" not in saved["canonical_names"]["ORF5"]
    assert Path(prrs_run["alias_config_path"]).read_text(encoding="utf-8") == original_config


@requires_sample_data
def test_query_only_run_uses_the_saved_reference_for_its_virus(prrs_run):
    # A PRRSV reference saved by an earlier run; this time only the query is given.
    ref_record = prrs_run["ref_record"]
    ui.reference_library.save_reference(REF_FILE, ref_record, "PRRSV", "CDS", len(prrs_run["ref_features"]))

    at = _app(crawler_query_path=str(QUERY_FILES[0]))
    at.run()
    _assert_clean(at)
    assert at.selectbox(key="ref_choice").value == ref_record.id

    next(button for button in at.button if button.label == "Continue").click().run()
    _assert_clean(at)
    assert at.session_state.stage != "upload"
    assert at.session_state.ref_saved_id == ref_record.id


@requires_sample_data
def test_alias_manager_lists_the_virus_references(prrs_run):
    ref_record = prrs_run["ref_record"]
    ui.reference_library.save_reference(REF_FILE, ref_record, "PRRSV", "CDS", len(prrs_run["ref_features"]))
    at = _app(app_mode="Alias manager")
    at.run()
    _assert_clean(at)
    page_html = " ".join(element.proto.body for element in at.get("html"))
    assert ref_record.id in page_html and "Default" in page_html
