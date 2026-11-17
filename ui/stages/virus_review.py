# Step 2 · Review — the reference did not match a registered virus.
import pandas as pd
import streamlit as st
from app.src.alias.alias_manager import list_registry_entries
from ui.components import _card, _render_callout, _render_context_panel, _render_page_intro, _render_section_title
from ui.guide import _open_guide
from ui.i18n import _t
from ui.services import _continue_with_existing_alias_config
from ui.state import REGISTRY_PATH, _reset


USE_EXISTING = "Use an existing virus config"
CREATE_NEW = "Create a new virus config"


def stage_virus_review():
    _render_page_intro(
        _t("run_setup"),
        "Which virus is this?",
        "Pick the alias config to use for this reference, or start a new one.",
        step_note="Virus not recognised",
        guide=_open_guide,
    )

    metadata = st.session_state.virus_review_metadata or []
    _render_callout(
        "The reference metadata did not match any registered virus keyword. "
        "If this is a known virus with new metadata, reuse its config and save a keyword "
        "so it is detected next time. Otherwise create a new config.",
        tone="warn",
        icon="!",
    )
    _render_context_panel([
        (_t("reference"), st.session_state.ref_record.id),
        ("Suggested name", st.session_state.virus_review_guess),
        ("Metadata candidates", len(metadata)),
    ])

    choice = st.segmented_control(
        "What do you want to do?",
        [USE_EXISTING, CREATE_NEW],
        default=USE_EXISTING,
        required=True,
        key="virus_review_choice",
    )

    entries = list_registry_entries(REGISTRY_PATH)
    if choice == USE_EXISTING:
        with _card("virus_existing"):
            _render_section_title("Reuse a registered virus", "Its alias config is applied to this run.")
            options = [
                f"{entry.get('virus_name', 'unknown')} — {entry.get('alias_config', '')}"
                for entry in entries
            ]
            selected = st.selectbox("Existing virus", options)
            entry = entries[options.index(selected)]

            keyword_col, custom_col = st.columns(2)
            keyword_to_save = keyword_col.selectbox(
                "Save a metadata value as a new keyword",
                [""] + metadata,
                help="Optional. Saving a keyword lets ViraLift auto-detect this metadata next time.",
            )
            custom_keyword = custom_col.text_input("Or type a custom keyword", value="")
            final_keyword = custom_keyword.strip() or keyword_to_save.strip()

        if metadata:
            with st.expander(f"Reference metadata ({len(metadata)})", expanded=False):
                st.dataframe(pd.DataFrame({"candidate_keyword": metadata}), hide_index=True, width="stretch")

        with st.container(horizontal=True, horizontal_alignment="distribute", vertical_alignment="center"):
            st.button(_t("back"), icon=":material/arrow_back:", on_click=_reset)
            if st.button("Use this config", icon=":material/arrow_forward:", type="primary"):
                try:
                    _continue_with_existing_alias_config(entry, save_keyword=final_keyword or None)
                    st.rerun()
                except Exception as e:
                    st.error(f"Could not continue with selected config: {e}")
    else:
        _render_callout(
            "ViraLift seeds a new alias config from the reference feature names, then "
            "uses tblastn coordinate evidence to suggest which query names are safe aliases.",
            tone="info",
        )
        with st.container(horizontal=True, horizontal_alignment="distribute", vertical_alignment="center"):
            st.button(_t("back"), icon=":material/arrow_back:", on_click=_reset)
            if st.button("Create new virus config", icon=":material/arrow_forward:", type="primary"):
                st.session_state.stage = "bootstrap_alias"
                st.rerun()
