# Step 1 · Setup — upload reference + query and configure the run.
import html
import streamlit as st
import tempfile
from pathlib import Path
from app.src.alias.alias_bootstrap import build_seed_alias_config_from_ref
from app.src.features.ref_loader import prepare_reference_features
from app.src.io.genbank_parser import load_genbank_records, load_single_genbank
from app.src.io.run_logger import log_error
from ui.components import _card, _render_callout, _render_page_intro, _render_section_title
from ui.guide import _open_guide
from ui.i18n import _t
from ui.services import _load_excluded_names, _record_metadata_candidates, _save_upload, _scan_unknown_names, _scan_unknown_ref_names, _suggest_virus_name
from ui.state import REGISTRY_PATH


def _clear_crawler_query() -> None:
    st.session_state.crawler_query_path = None
    st.session_state.crawler_query_label = ""


def stage_upload():
    _render_page_intro(
        _t("run_setup"),
        _t("upload_title"),
        _t("upload_body"),
        guide=_open_guide,
    )

    col_ref, col_query = st.columns(2, gap="medium")
    with col_ref, _card("ref"):
        _render_section_title(_t("reference_record"), _t("reference_caption"))
        ref_file = st.file_uploader("Reference GenBank (.gb)", type=["gb", "gbk"], label_visibility="collapsed")
    with col_query, _card("query"):
        _render_section_title(_t("query_records"), _t("query_caption"))
        crawled_query_path = st.session_state.get("crawler_query_path")
        if crawled_query_path:
            _render_callout(
                f"<b>{html.escape(_t('crawler_query_ready'))}</b><br>"
                f"<span class='vl-mono'>{html.escape(Path(crawled_query_path).name)}</span>",
                tone="ok",
                icon="✓",
            )
            st.button(_t("clear_crawler_query"), key="clear_crawler_query", on_click=_clear_crawler_query)
            query_file = None
        else:
            query_file = st.file_uploader("Query GenBank (.gb)", type=["gb", "gbk"], label_visibility="collapsed")

    with _card("options"):
        _render_section_title(_t("run_options"), _t("run_options_caption"))
        st.session_state.use_ref_names = st.toggle(
            _t("use_ref_names"),
            value=False,
            help=_t("use_ref_names_help"),
        )
        with st.expander(_t("lifting_thresholds"), expanded=False):
            st.caption(_t("threshold_caption"))
            c1, c2, c3, c4 = st.columns(4)
            st.session_state.min_coverage   = c1.number_input(_t("min_coverage"),  0.0, 1.0, 0.5, 0.05)
            st.session_state.min_identity   = c2.number_input(_t("min_identity"),  0.0, 1.0, 0.3, 0.05)
            st.session_state.evalue         = c3.number_input(_t("evalue"),       value=1e-5, format="%.0e")
            st.session_state.rescue_window  = c4.number_input(_t("rescue_window"), 10,  500,   200,   10)
        with st.expander(_t("file_requirements"), expanded=False):
            st.markdown(_t("file_requirements_body"))

    ready = ref_file and (query_file or st.session_state.get("crawler_query_path"))
    with st.container(horizontal=True, horizontal_alignment="distribute", vertical_alignment="center"):
        if ready:
            query_label = query_file.name if query_file else Path(st.session_state.crawler_query_path).name
            st.caption(_t("ready_to_run", ref=ref_file.name, query=query_label))
        else:
            st.caption(_t("add_files_hint"))
        run_clicked = st.button(
            _t("run_button"),
            icon=":material/arrow_forward:",
            disabled=not ready,
            type="primary",
        )

    if run_clicked:
        # persist files to temp dir
        if st.session_state.tmp is None:
            st.session_state.tmp = tempfile.TemporaryDirectory()

        with st.spinner(_t("loading_files")):
            try:
                ref_path = _save_upload(ref_file)
                if query_file:
                    query_path = _save_upload(query_file)
                else:
                    query_path = Path(st.session_state.crawler_query_path)

                ref_record    = load_single_genbank(ref_path)
                query_records = load_genbank_records(query_path)

                ref_features, ref_feature_type, alias_config_path, virus_name, alias_lookup = (
                    prepare_reference_features(
                        ref_record=ref_record,
                        alias_config_arg=None,
                        alias_registry_arg=str(REGISTRY_PATH),
                    )
                )

                if alias_config_path is None:
                    virus_guess = _suggest_virus_name(ref_record)
                    seed_config = build_seed_alias_config_from_ref(
                        ref_record=ref_record,
                        ref_features=ref_features,
                        virus_name=virus_guess,
                    )

                    st.session_state.ref_record        = ref_record
                    st.session_state.query_records     = query_records
                    st.session_state.ref_features      = ref_features
                    st.session_state.ref_feature_type  = ref_feature_type
                    st.session_state.alias_lookup      = {}
                    st.session_state.alias_config_path = None
                    st.session_state.virus_name        = virus_guess
                    st.session_state.canonical_list    = sorted(seed_config["canonical_names"])
                    st.session_state.unknown_names     = {}
                    st.session_state.unknown_ref_names = []
                    st.session_state.bootstrap_alias_config = seed_config
                    st.session_state.bootstrap_virus_name = virus_guess
                    st.session_state.bootstrap_keywords = virus_guess
                    st.session_state.bootstrap_suggestions = []
                    st.session_state.bootstrap_diagnostics = {}
                    st.session_state.virus_review_metadata = _record_metadata_candidates(ref_record)
                    st.session_state.virus_review_guess = virus_guess
                    st.session_state.stage = "virus_review"
                    st.rerun()

                # canonical list for resolver dropdowns
                canonical_list = sorted(set(alias_lookup.values())) if alias_lookup else []

                # scan for unknown names in query records AND in ref
                excluded = _load_excluded_names(alias_config_path)
                unknown     = _scan_unknown_names(query_records, alias_lookup, excluded)
                unknown_ref = _scan_unknown_ref_names(ref_features, excluded)
            except Exception as e:
                log_error("loading UI inputs", e)
                st.error(f"{_t('load_error')}: {e}")
                return

        # store to session state
        st.session_state.ref_record        = ref_record
        st.session_state.query_records     = query_records
        st.session_state.ref_features      = ref_features
        st.session_state.ref_feature_type  = ref_feature_type
        st.session_state.alias_lookup      = alias_lookup
        st.session_state.alias_config_path = alias_config_path
        st.session_state.virus_name        = virus_name
        st.session_state.canonical_list    = canonical_list
        st.session_state.unknown_names     = unknown
        st.session_state.unknown_ref_names = unknown_ref

        if unknown or unknown_ref:
            st.session_state.stage = "resolve"
        else:
            st.session_state.stage = "running"

        st.rerun()
