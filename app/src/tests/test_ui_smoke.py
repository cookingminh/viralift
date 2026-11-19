"""End-to-end smoke tests for the Streamlit UI.

Each test runs the real app script with streamlit.testing's AppTest and checks
that a workspace or wizard step renders without an exception. The data-backed
tests use the git-ignored sample genomes in app/data/ and tblastn; they skip
when either is missing. Logging is stubbed, alias edits go to a temporary copy
and saved references to tmp_path, so the tests never touch logs/ or app/config/.
"""
import dataclasses
import json
import shutil
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

import ui.fasta_names
import ui.genome_map
import ui.reference_library
import ui.services
import ui.stages.resolve
from app.src.alias.alias_bootstrap import build_seed_alias_config_from_ref
from app.src.features.ref_loader import prepare_reference_features
from app.src.io.genbank_parser import load_genbank_records, load_single_genbank
from app.src.pipeline import PipelineConfig, PipelineRunResult, run_pipeline
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
    monkeypatch.setattr(ui.fasta_names, "SETTINGS_FILE", tmp_path / "export_settings.json")
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


@pytest.mark.parametrize("label, key", [
    ("Lift genes the annotation is missing", "lift_missing"),
    ("Check annotations against the reference", "check_annotations"),
])
def test_setup_options_are_on_by_default(label, key):
    at = _app()
    at.run()
    toggle = next(t for t in at.toggle if t.label == label)
    assert toggle.value is True
    toggle.set_value(False).run()
    _assert_clean(at)
    assert at.session_state[key] is False


@requires_sample_data
@pytest.mark.parametrize("choice", [True, False])
def test_run_uses_the_setup_choices(prrs_run, monkeypatch, choice):
    seen = []

    def fake_run_pipeline(**kwargs):
        seen.append((kwargs["config"].lift_missing, kwargs["config"].check_annotations))
        return PipelineRunResult(all_results=prrs_run["all_results"])

    monkeypatch.setattr(ui.services, "run_pipeline", fake_run_pipeline)
    at = _app(**prrs_run, stage="running", lift_missing=choice, check_annotations=choice)
    at.run()
    _assert_clean(at)
    assert seen == [(choice, choice)]


def _replaced(prrs_run):
    """prrs_run with its first annotated gene replaced by a tblastn row, as the
    annotation check does for an annotation longer than the gene."""
    record_id, features = next((rid, fs) for rid, fs in prrs_run["all_results"] if fs and fs[0].method == "direct")
    annotated = dataclasses.replace(features[0], status="overlong_annotation", annotation_check="overlong")
    lifted = dataclasses.replace(
        features[0], method="tblastn", query_end=features[0].query_end - 30, annotation_check="overlong",
        annotation=annotated,
    )
    all_results = [
        (rid, [lifted, *fs[1:]] if rid == record_id else fs) for rid, fs in prrs_run["all_results"]
    ]
    return {**prrs_run, "all_results": all_results}, record_id, lifted


@requires_sample_data
@pytest.mark.parametrize("view", ["Genome map", "Features", "Export"])
def test_results_show_the_annotation_check(prrs_run, view):
    state, _, _ = _replaced(prrs_run)
    at = _app(stage="results", results_view=view, **state)
    at.run()
    _assert_clean(at)
    assert any("Annotation check" in block.proto.body for block in at.get("html"))


def _detail_script():
    import streamlit as st
    from ui.stages.results import _render_feature_detail
    from ui.state import _init_state

    _init_state()
    _render_feature_detail(st.session_state.detail_record, st.session_state.detail_row, st.session_state.detail_row.name)


@requires_sample_data
def test_detail_panel_switches_between_annotation_and_tblastn(prrs_run):
    state, record_id, lifted = _replaced(prrs_run)
    at = AppTest.from_function(_detail_script, default_timeout=180)
    for key, value in {**state, "detail_record": record_id, "detail_row": lifted}.items():
        at.session_state[key] = value
    at.run()
    _assert_clean(at)
    at.button(key=f"check_choice_{record_id}_{lifted.name}").click().run()
    choice = at.session_state["annotation_choices"][f"{record_id}\x1f{lifted.name}"]
    assert choice == lifted.annotation

    # Shown the annotation now, the panel offers tblastn back, which clears the choice.
    at.session_state["detail_row"] = choice
    at.run()
    at.button(key=f"check_choice_{record_id}_{lifted.name}").click().run()
    assert at.session_state["annotation_choices"] == {}


@requires_sample_data
def test_results_have_no_records_tab(prrs_run):
    # The genome map's matrix took over the record table.
    at = _app(stage="results", **prrs_run)
    at.run()
    _assert_clean(at)
    assert [tab.label for tab in at.tabs] == ["Genome map", "Features", "Export"]


@requires_sample_data
def test_detail_panel_draws_the_gene_and_links_to_the_map(prrs_run):
    record_id, features = next((rid, fs) for rid, fs in prrs_run["all_results"] if fs and fs[0].method == "tblastn")
    gene = next(f for f in features if f.query_start is not None)
    at = AppTest.from_function(_detail_script, default_timeout=180)
    for key, value in {**prrs_run, "detail_record": record_id, "detail_row": gene}.items():
        at.session_state[key] = value
    at.run()
    _assert_clean(at)
    page = " ".join(element.proto.body for element in at.get("html"))
    assert "vl-place" in page and "of the reference gene" in page and "vl-meter" in page
    assert "Raw name" not in page  # no empty "—" fields any more

    at.button(key=f"show_on_map_{record_id}_{gene.name}").click().run()
    _assert_clean(at)
    assert (at.session_state.map_record, at.session_state.map_gene) == (record_id, gene.name)
    assert at.session_state.results_view == "Genome map"


@requires_sample_data
def test_detail_panel_checks_an_annotated_gene_with_tblastn(prrs_run):
    record_id, features = next((rid, fs) for rid, fs in prrs_run["all_results"] if fs and fs[0].method == "direct")
    at = AppTest.from_function(_detail_script, default_timeout=180)
    for key, value in {**prrs_run, "detail_record": record_id, "detail_row": features[0]}.items():
        at.session_state[key] = value
    at.run()
    at.button(key=f"check_tblastn_{record_id}_{features[0].name}").click().run()
    _assert_clean(at)
    assert record_id in at.session_state["manual_lifts"]


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
@pytest.mark.parametrize("view", ["Genome map", "Features", "Export"])
def test_results_views_render(prrs_run, view):
    at = _app(stage="results", results_view=view, **prrs_run)
    at.run()
    _assert_clean(at)


@requires_sample_data
def test_export_names_sequences_and_remembers_the_choice(prrs_run, tmp_path):
    at = _app(stage="results", results_view="Export", **prrs_run)
    at.run()
    _assert_clean(at)
    first = next(r for r in prrs_run["query_records"] if any(f.type == "source" for f in r.features))
    assert at.code[0].value.startswith(f">{first.id}|")          # default: accession|gene|start|end|strand

    at.button(key="fasta_preset_isolate_host").click().run()
    _assert_clean(at)
    assert at.code[0].value.split("\n")[0].startswith(f">{first.id}_")
    saved = json.loads((tmp_path / "export_settings.json").read_text())["fasta_header"]
    assert saved == {"fields": ["accession", "isolate", "host"], "separator": "_", "missing": "NA"}

    # A new session starts from the saved choice.
    again = _app(stage="results", results_view="Export", **prrs_run)
    again.run()
    assert again.session_state["fasta_name_fields"] == ["accession", "isolate", "host"]


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


# ── genome map ───────────────────────────────────────────────────────────

def _page_html(at: AppTest) -> str:
    return " ".join(element.proto.body for element in at.get("html"))


@requires_sample_data
def test_results_open_on_the_genome_map(prrs_run):
    at = _app(stage="results", **prrs_run)
    at.run()
    _assert_clean(at)
    first = prrs_run["all_results"][0][0]
    assert at.session_state.map_record == first
    assert "Every record against the reference" in _page_html(at)


@requires_sample_data
def test_genome_map_opens_the_selected_gene(prrs_run):
    record_id = prrs_run["all_results"][-1][0]
    at = _app(stage="results", map_record=record_id, map_gene="ORF5", **prrs_run)
    at.run()
    _assert_clean(at)
    assert f"{record_id} · ORF5" in _page_html(at)


@requires_sample_data
def test_gene_focus_exports_that_gene(prrs_run):
    at = _app(stage="results", map_focus="ORF5", **prrs_run)
    at.run()
    _assert_clean(at)
    at.button(key="map_export_gene").click().run()
    _assert_clean(at)
    assert at.session_state.results_view == "Export"
    assert at.session_state.fasta_genes == ["ORF5"]


@requires_sample_data
def test_export_picks_genes_on_the_reference_only(prrs_run):
    at = _app(stage="results", results_view="Export", **prrs_run)
    at.run()
    _assert_clean(at)
    genes = sorted({f["name"] for f in prrs_run["ref_features"]})
    assert at.session_state.fasta_genes == genes  # everything picked to start with
    assert not [m for m in at.multiselect if m.label == "Genes to extract"]

    at.button(key="fasta_pick_none").click().run()
    _assert_clean(at)
    assert at.session_state.fasta_genes == []
    assert next(b for b in at.button if b.label == "Generate FASTA").disabled

    at.button(key="fasta_pick_all").click().run()
    _assert_clean(at)
    assert at.session_state.fasta_genes == genes
    # The choice is not a widget's, so it survives a visit to another tab.
    at.button(key="fasta_pick_none").click().run()
    at.session_state["results_view"] = "Genome map"
    at.run()
    at.session_state["results_view"] = "Export"
    at.run()
    assert at.session_state.fasta_genes == []


def _map_event_script():
    import streamlit as st
    from ui.stages import results
    from ui.state import _init_state

    _init_state()
    getattr(results, st.session_state.handler)()


@requires_sample_data
@pytest.mark.parametrize("handler, event, before, after", [
    ("_on_matrix_select", {"record": "Q.2", "gene": "ORF5"}, {}, {"map_record": "Q.2", "map_gene": "ORF5"}),
    ("_on_matrix_select", {"record": "Q.2", "gene": None}, {"map_gene": "ORF3"}, {"map_record": "Q.2", "map_gene": "ORF3"}),
    ("_on_matrix_focus", "ORF5", {}, {"map_focus": "ORF5"}),
    ("_on_matrix_focus", "ORF5", {"map_focus": "ORF5"}, {"map_focus": None}),  # a second click closes it
    ("_on_tracks_select", "ORF5", {"map_gene": "ORF3"}, {"map_gene": "ORF5"}),
    ("_on_tracks_select", "ORF5", {"map_gene": "ORF5"}, {"map_gene": None}),
    ("_on_pick", "ORF5", {"fasta_genes": ["ORF3", "ORF5"]}, {"fasta_genes": ["ORF3"]}),
    ("_on_pick", "ORF2a", {"fasta_genes": ["ORF3"]}, {"fasta_genes": ["ORF2a", "ORF3"]}),
])
def test_map_events_update_one_shared_selection(prrs_run, monkeypatch, handler, event, before, after):
    monkeypatch.setattr(ui.genome_map, "event_value", lambda key, name: event)
    at = AppTest.from_function(_map_event_script, default_timeout=60)
    for key, value in {**prrs_run, **before, "handler": handler}.items():
        at.session_state[key] = value
    at.run()
    _assert_clean(at)
    for key, value in after.items():
        assert at.session_state[key] == value


@requires_sample_data
def test_setup_previews_the_reference_before_the_run(prrs_run):
    ref_record = prrs_run["ref_record"]
    ui.reference_library.save_reference(REF_FILE, ref_record, "PRRSV", "CDS", len(prrs_run["ref_features"]))
    at = _app(crawler_query_path=str(QUERY_FILES[0]))
    at.run()
    _assert_clean(at)
    preview = next(iter(at.session_state["ref_preview_cache"].values()))
    assert "error" not in preview
    assert preview["genes"] == len(prrs_run["ref_features"])
    assert [gene[0] for gene in preview["ref"]["genes"]][:2] == ["ORF1a", "ORF1b"]
    assert "What this reference will look for" in _page_html(at)
    assert any("Query: 1 record(s)" in caption.value for caption in at.caption)


@requires_sample_data
def test_review_rows_draw_where_the_name_sits(prrs_run, tmp_path):
    config_copy = tmp_path / "prrsv_alias.json"
    shutil.copy(prrs_run["alias_config_path"], config_copy)
    record_id = prrs_run["query_records"][0].id
    unknown = {"ORF5a": {"records": [record_id], "candidates": ["ORF5a", "5a"]}}
    state = {**prrs_run, "alias_config_path": config_copy, "all_results": None}
    at = _app(stage="resolve", unknown_names=unknown, unknown_ref_names=[], **state)
    at.run()
    _assert_clean(at)
    context = at.session_state["review_context"]
    assert record_id in context["lifted"]
    evidence = context["evidence"]["ORF5a"]
    # ORF5a (13,778-13,933) lies inside ORF5 on the record.
    assert (evidence["verdict"], evidence["gene"], evidence["start"]) == ("inside", "ORF5", 13778)
