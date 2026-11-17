# Step 2 · Review names — map unknown query names, optionally register ref names.
import html
import streamlit as st
from pathlib import Path
from typing import Dict, List
from app.src.alias.gene_alias import normalize_text
from app.src.llm.alias_review import review_unresolved_names
from app.src.io.run_logger import log_session_decisions
from ui.components import _card, _chips_html, _render_callout, _render_page_intro, _render_section_title
from ui.guide import _open_guide
from ui.i18n import _t
from ui.services import _add_new_canonicals_to_config, _load_excluded_names, _save_to_alias_config
from ui.state import _reset


def _llm_review_for_row(llm_reviews: Dict, rep: str, info: Dict) -> Dict:
    """Find an LLM review even when the representative differs from candidates."""
    if not llm_reviews:
        return {}
    lookup_values = [rep, normalize_text(rep)]
    for candidate in info.get("candidates", []) or []:
        text = str(candidate or "").strip()
        if text:
            lookup_values.extend([text, normalize_text(text)])
    for value in lookup_values:
        if value and value in llm_reviews:
            return llm_reviews[value]
    return {}


def _short(value: str, limit: int = 42) -> str:
    return value if len(value) <= limit else value[: limit - 1] + "…"


def _render_ref_side(unknown_ref: List[str]) -> None:
    with _card("ref_names"):
        _render_section_title(
            _t("ref_missing_title", count=len(unknown_ref)),
            _t("ref_missing_body"),
        )
        to_add = st.pills(
            _t("ref_names_pick"),
            unknown_ref,
            selection_mode="multi",
            key="ref_add_names",
        )
        if st.button(
            _t("save_ref_names"),
            icon=":material/add:",
            key="save_ref_canonicals",
            disabled=not to_add,
        ):
            if to_add and st.session_state.alias_config_path:
                added = _add_new_canonicals_to_config(
                    Path(st.session_state.alias_config_path), list(to_add)
                )
                if added:
                    # also add them to the canonical_list for the query resolver below
                    st.session_state.canonical_list = sorted(
                        set(st.session_state.canonical_list) | set(to_add)
                    )
                    st.toast(_t("canonicals_added", count=added))
                else:
                    st.info(_t("already_exists"))


def _render_add_canonical_popover() -> None:
    with st.popover(_t("add_canonical_target"), icon=":material/add:"):
        st.caption(_t("add_canonical_caption"))
        new_canonical = st.text_input(
            "New canonical name",
            value="",
            placeholder="e.g. ORF1ab",
            key="resolve_new_canonical_name",
        ).strip()
        if st.button(
            "Add canonical",
            type="primary",
            disabled=not new_canonical,
            width="stretch",
            key="resolve_add_canonical",
        ):
            already_exists = new_canonical in st.session_state.canonical_list
            if st.session_state.alias_config_path:
                added = _add_new_canonicals_to_config(
                    Path(st.session_state.alias_config_path),
                    [new_canonical],
                )
            else:
                added = 0
            st.session_state.canonical_list = sorted(
                set(st.session_state.canonical_list) | {new_canonical}
            )
            if added and not already_exists:
                st.session_state.resolve_canonical_notice = (
                    "success",
                    f"Added `{new_canonical}` successfully.",
                )
            else:
                st.session_state.resolve_canonical_notice = (
                    "info",
                    f"`{new_canonical}` already exists.",
                )
            st.session_state.resolve_llm_reviews = {}
            st.session_state.resolve_llm_diagnostics = {}
            st.rerun()


def _run_llm_review(unknown_items: Dict, virus: str, canonicals: List[str]) -> None:
    with st.spinner("Reviewing unresolved names with LLM..."):
        excluded = (
            _load_excluded_names(Path(st.session_state.alias_config_path))
            if st.session_state.alias_config_path
            else set()
        )
        reviews, diagnostics = review_unresolved_names(
            unknown_items=unknown_items,
            ambiguous_items={},
            virus_name=virus,
            canonical_names=canonicals,
            excluded_names=excluded,
            cache=st.session_state.llm_alias_review_cache,
        )
    st.session_state.resolve_llm_reviews = reviews
    st.session_state.resolve_llm_diagnostics = diagnostics
    ignore_option = _t("ignore_option")
    for representative, info in unknown_items.items():
        review = _llm_review_for_row(reviews, representative, info)
        if not review:
            continue
        action = review.get("action")
        canonical = review.get("canonical_name")
        key = f"resolve_{representative}"
        if action == "save_alias" and canonical in canonicals:
            st.session_state[key] = canonical
        elif action in {"ignore", "skip", "move_to_ambiguous"}:
            st.session_state[key] = ignore_option
    st.rerun()


def _render_llm_status(llm_diagnostics: Dict) -> None:
    status = llm_diagnostics.get("status")
    if status == "reviewed":
        cache_note = " cached" if llm_diagnostics.get("cache_hit") else ""
        st.success(
            "LLM reviewed "
            f"{llm_diagnostics.get('reviewed_rows', 0)} / "
            f"{llm_diagnostics.get('submitted_rows', 0)} submitted row(s){cache_note}."
        )
    elif status == "missing_api_key":
        st.warning("LLM review is enabled but no API key is configured.")
    elif status == "disabled":
        st.info("LLM review is disabled. Set `VIRALIFT_LLM_ENABLED=true` to use this assist.")
    elif status == "error":
        st.error(f"LLM review failed: {llm_diagnostics.get('error')}")
    elif status:
        st.caption(f"LLM review status: {status}")


def stage_resolve():
    unknown     = st.session_state.unknown_names
    unknown_ref = st.session_state.unknown_ref_names
    virus       = st.session_state.virus_name or "unknown virus"

    _render_page_intro(
        _t("alias_review"),
        _t("resolve_title"),
        _t("resolve_body"),
        guide=_open_guide,
    )

    config_path = st.session_state.alias_config_path
    _render_callout(
        _t(
            "virus_banner",
            virus=html.escape(virus),
            config=html.escape(Path(config_path).name if config_path else "none"),
            count=len(st.session_state.canonical_list),
        ),
        tone="info",
    )

    # ── Ref-side names ──────────────────────────────────────────────────
    if unknown_ref:
        _render_ref_side(unknown_ref)

    # ── Query-side resolver ──────────────────────────────────────────────
    unknown_items = dict(unknown)
    canonicals = st.session_state.canonical_list

    if not unknown_items:
        _render_callout(html.escape(_t("all_known")), tone="ok", icon="✓")
    else:
        with st.container(horizontal=True, horizontal_alignment="distribute", vertical_alignment="center"):
            st.html(
                f"<div class='vl-section-title'>{html.escape(_t('names_to_decide'))} "
                f"<span class='vl-chip is-primary'>{len(unknown_items)}</span></div>",
                width="content",
            )
            with st.container(horizontal=True, horizontal_alignment="right", width="content"):
                _render_add_canonical_popover()
                if st.button(
                    _t("llm_suggest"),
                    icon=":material/auto_awesome:",
                    key="resolve_run_llm_review",
                ):
                    _run_llm_review(unknown_items, virus, canonicals)
        st.caption(
            _t("unknown_query_intro", count=len(unknown_items), virus=virus)
            + " " + _t("llm_caption")
        )

        notice = st.session_state.pop("resolve_canonical_notice", None)
        if notice:
            kind, message = notice
            getattr(st, kind)(message)

        llm_diagnostics = st.session_state.get("resolve_llm_diagnostics", {}) or {}
        if llm_diagnostics:
            _render_llm_status(llm_diagnostics)

    llm_reviews = st.session_state.get("resolve_llm_reviews", {}) or {}
    decisions = {}
    save_candidates = {}
    options    = [_t("ignore_option")] + canonicals

    def _default_save_candidate(candidate: str, representative: str) -> bool:
        """Persist only the clean representative by default."""
        text = str(candidate or "").strip()
        if not text or ";" in text:
            return False
        return text == representative

    def _render_resolver_row(index: int, rep: str, info: Dict) -> None:
        record_ids = info["records"]
        candidates = info["candidates"]

        with _card(f"resolve_row_{index}"):
            col_name, col_action, col_save = st.columns([3, 2.2, 2.6], gap="medium")

            col_name.html(
                _chips_html(candidates)
                + "<div class='vl-meta'>"
                + html.escape(
                    _t("unknown_prefix") + " · "
                    + f"{_t('appears_in')} {', '.join(record_ids[:5])}"
                    + (f" +{len(record_ids) - 5} more" if len(record_ids) > 5 else "")
                )
                + "</div>"
            )

            choice = col_action.selectbox(
                _t("map_to_canonical"),
                options,
                key=f"resolve_{rep}",
                label_visibility="collapsed",
            )
            mapped = None if choice.startswith("--") else choice
            decisions[rep] = mapped

            review = _llm_review_for_row(llm_reviews, rep, info)
            if review:
                action = review.get("action")
                canonical = review.get("canonical_name") or "none"
                confidence = review.get("confidence") or "unknown"
                reason = review.get("reason") or "No reason returned."
                col_action.caption(
                    f":material/auto_awesome: LLM: `{action}` → `{canonical}` ({confidence}). {reason}"
                )

            if mapped:
                pill_options = list(dict.fromkeys(str(candidate) for candidate in candidates))
                selected = col_save.pills(
                    _t("save_aliases"),
                    pill_options,
                    selection_mode="multi",
                    default=[c for c in pill_options if _default_save_candidate(c, rep)],
                    format_func=_short,
                    key=f"save_{rep}",
                    help=_t("save_candidate_help"),
                )
                save_candidates[rep] = list(selected or [])
            else:
                col_save.caption(_t("keep_raw_note"))

    # Unknown names (completely unrecognised)
    for index, (rep, info) in enumerate(unknown_items.items()):
        _render_resolver_row(index, rep, info)

    mapped_count = sum(1 for canonical in decisions.values() if canonical)
    with st.container(horizontal=True, horizontal_alignment="distribute", vertical_alignment="center"):
        back_clicked = st.button(_t("back"), icon=":material/arrow_back:")
        with st.container(horizontal=True, horizontal_alignment="right", vertical_alignment="center", width="content"):
            if decisions:
                st.caption(_t("decision_summary", mapped=mapped_count, raw=len(decisions) - mapped_count))
            run_clicked = st.button(_t("continue"), icon=":material/play_arrow:", type="primary")

    if back_clicked:
        _reset()
        st.rerun()

    if run_clicked:
        # Expand all candidates for each group into flat {candidate: canonical} dicts.
        # This ensures every variant name (product, note, etc.) is covered, both
        # for the session-only effective lookup and for permanent alias config saves.

        # Session resolver: all candidates of every decided group
        resolver_expanded: Dict[str, str] = {}
        for rep, canonical in decisions.items():
            if canonical:
                for candidate in unknown[rep]["candidates"]:
                    resolver_expanded[candidate] = canonical

        # Persist to alias config: only candidate aliases explicitly selected
        # by the user. Session resolution remains broader than permanent saves.
        to_save: Dict[str, str] = {}
        for rep, canonical in decisions.items():
            if canonical:
                for candidate in save_candidates.get(rep, []):
                    to_save[candidate] = canonical

        if to_save and st.session_state.alias_config_path:
            written = _save_to_alias_config(
                Path(st.session_state.alias_config_path), to_save
            )
            if written:
                st.toast(_t("aliases_saved", count=written))

        # log ALL decisions so there is always a trace
        if decisions:
            log_session_decisions(
                decisions=resolver_expanded,
                saved_names=list(to_save.keys()),
            )

        st.session_state.resolver = resolver_expanded
        st.session_state.stage    = "running"
        st.rerun()
