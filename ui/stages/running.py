# Auto-split from the original monolithic streamlit_app.py.
import streamlit as st
from pathlib import Path
from app.src.io.run_logger import log_error
from ui.components import _render_page_intro
from ui.i18n import _t
from ui.reference_library import mark_used, save_reference
from ui.services import _build_effective_lookup, _run_pipeline


def _remember_reference() -> None:
    """Keep this run's reference so the next run only needs the query file."""
    source = st.session_state.get("ref_source_path")
    if not source:
        return
    try:
        if st.session_state.get("ref_saved_id"):
            mark_used(st.session_state.ref_saved_id)
        else:
            save_reference(
                Path(source),
                st.session_state.ref_record,
                st.session_state.virus_name,
                st.session_state.ref_feature_type,
                len(st.session_state.ref_features or []),
            )
    except OSError as e:  # never block a run over the convenience copy
        log_error("saving reference", e)


def stage_running():
    _render_page_intro(
        _t("run_setup"),
        _t("running_title"),
        _t("running_body"),
        step_note=_t("processing"),
    )
    progress = st.progress(0, text=_t("starting"))
    st.session_state.run_errors = []
    _remember_reference()

    effective_lookup = _build_effective_lookup(
        st.session_state.alias_lookup,
        st.session_state.resolver,
    )

    all_results = _run_pipeline(
        ref_record        = st.session_state.ref_record,
        query_records     = st.session_state.query_records,
        ref_features      = st.session_state.ref_features,
        ref_feature_type  = st.session_state.ref_feature_type,
        effective_lookup  = effective_lookup,
        min_coverage      = st.session_state.min_coverage,
        min_identity      = st.session_state.min_identity,
        evalue            = st.session_state.evalue,
        rescue_window     = st.session_state.rescue_window,
        progress_bar      = progress,
        virus_name        = st.session_state.virus_name,
        alias_config_path = st.session_state.alias_config_path,
        run_errors        = st.session_state.run_errors,
    )

    st.session_state.all_results = all_results
    st.session_state.stage       = "results"
    st.rerun()
