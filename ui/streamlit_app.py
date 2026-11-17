"""
ViraLift Streamlit Web UI — application entry point.

This file is intentionally thin: it wires together the ui/ package
(theme, i18n, state, components, services, stages, alias manager) and
routes to the active stage. All real logic lives in the submodules.

Run pipeline is a three-step wizard (see components.PIPELINE_STEPS):
    Setup        upload: user uploads ref + query, pipeline is configured
    Review names virus_review / bootstrap_alias: unknown virus, user picks or
                 creates an alias config; resolve: user maps unknown names
    Results      running: pipeline runs; results: review + export
"""

import os
import sys
from pathlib import Path

import streamlit as st

# project root on path (before importing ui.* which pull in app.src)
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ui.state import _init_state
from ui.theme import _inject_css, _nav_active_css
from ui.i18n import _t
from ui.components import _render_brand, _render_footer, _render_topbar_context
from ui.stages.upload import stage_upload
from ui.stages.virus_review import stage_virus_review
from ui.stages.bootstrap_alias import stage_bootstrap_alias
from ui.stages.resolve import stage_resolve
from ui.stages.running import stage_running
from ui.stages.results import stage_results
from ui.alias_manager_page import page_alias_manager
from ui.data_crawler_page import _sync_crawler_credentials, page_data_crawler


APP_MODES = {
    "Run pipeline": ":material/conversion_path:",
    "Data crawler": ":material/cloud_download:",
    "Alias manager": ":material/menu_book:",
}


def _mode_key(label: str) -> str:
    return label.lower().replace(" ", "_")


def _set_app_mode(mode: str) -> None:
    _sync_crawler_credentials()
    st.session_state.app_mode = mode


def _build_label() -> str:
    """Which build is running: the image's version stamp (set by CI), or
    "source" when started with `streamlit run` from a checkout."""
    label = f"ViraLift {os.environ.get('VIRALIFT_VERSION') or 'source'}"
    commit = os.environ.get("VIRALIFT_COMMIT", "")
    if commit and commit != "unknown":
        label += f" · {commit[:7]}"
    return label


def _run_context() -> list:
    """The current run in a few words, for the top bar (the stepper shows the step)."""
    items = []
    if st.session_state.virus_name:
        items.append(st.session_state.virus_name)
    if st.session_state.ref_record:
        items.append(st.session_state.ref_record.id)
    if st.session_state.query_records:
        items.append(_t("records_loaded", count=f"{len(st.session_state.query_records):,}"))
    return items


# ═══════════════════════════════════════════════════════════════════
# App entry point
# ═══════════════════════════════════════════════════════════════════

st.set_page_config(
    page_title="ViraLift",
    page_icon=":material/genetics:",
    layout="wide",
    initial_sidebar_state="collapsed",
)

_init_state()
_inject_css()

# Top bar instead of a sidebar, so pages get the full width. theme.py pins it
# into Streamlit's header band, next to the ⋮ menu.
with st.container(horizontal=True, vertical_alignment="center", gap="small", key="vl_topbar"):
    _render_brand()
    for mode, icon in APP_MODES.items():
        st.button(
            mode,
            key=f"mode_{_mode_key(mode)}",
            icon=icon,
            type="tertiary",
            on_click=_set_app_mode,
            args=(mode,),
        )
    if st.session_state.app_mode == "Run pipeline":
        _render_topbar_context(_run_context())
_nav_active_css(f"mode_{_mode_key(st.session_state.app_mode)}")

# route to current stage
if st.session_state.app_mode == "Alias manager":
    page_alias_manager()
elif st.session_state.app_mode == "Data crawler":
    page_data_crawler()
else:
    stage = st.session_state.stage
    if stage == "upload":
        stage_upload()
    elif stage == "virus_review":
        stage_virus_review()
    elif stage == "bootstrap_alias":
        stage_bootstrap_alias()
    elif stage == "resolve":
        stage_resolve()
    elif stage == "running":
        stage_running()
    elif stage == "results":
        stage_results()

_render_footer(_t("theme_hint"), _build_label())
