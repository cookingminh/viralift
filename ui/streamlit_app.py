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

import sys
from pathlib import Path

import streamlit as st

# project root on path (before importing ui.* which pull in app.src)
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ui.state import _init_state
from ui.theme import _inject_css, _nav_active_css
from ui.i18n import _t
from ui.components import (
    PIPELINE_STEP_KEYS,
    _pipeline_step_index,
    _render_brand,
    _render_nav_label,
    _render_sidebar_context,
)
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


def _run_context() -> list:
    items = []
    if st.session_state.ref_record:
        items.append((_t("reference"), st.session_state.ref_record.id))
    if st.session_state.query_records:
        items.append((_t("query_records"), _t("loaded", count=len(st.session_state.query_records))))
    if st.session_state.virus_name:
        items.append((_t("detected_virus"), st.session_state.virus_name))
    if st.session_state.alias_config_path:
        items.append((_t("alias_config"), Path(st.session_state.alias_config_path).name))
    step = _pipeline_step_index(st.session_state.stage)
    items.append((_t("step"), _t("step_of", index=step + 1, name=_t(PIPELINE_STEP_KEYS[step]))))
    return items


# ═══════════════════════════════════════════════════════════════════
# App entry point
# ═══════════════════════════════════════════════════════════════════

st.set_page_config(
    page_title="ViraLift",
    page_icon=":material/genetics:",
    layout="wide",
)

_init_state()
_inject_css()

with st.sidebar:
    _render_brand()
    _render_nav_label(_t("nav_workspace"))
    for mode, icon in APP_MODES.items():
        st.button(
            mode,
            key=f"mode_{_mode_key(mode)}",
            icon=icon,
            type="tertiary",
            width="stretch",
            on_click=_set_app_mode,
            args=(mode,),
        )
    _nav_active_css(f"mode_{_mode_key(st.session_state.app_mode)}")

    if st.session_state.app_mode == "Run pipeline":
        st.space("small")
        _render_nav_label(_t("nav_this_run"))
        _render_sidebar_context(_run_context())

    st.space("medium")
    st.html(f"<div class='vl-sidebar-foot'>{_t('sidebar_theme_hint')}</div>")

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
