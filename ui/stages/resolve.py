# Step 2 · Review names — map unknown query names, optionally register ref names.
#
# Each row is one exact set of unresolved names (services._scan_unknown_names).
# On entry the reference genes are lifted onto a few records per row and the
# annotated spans compared with them (ui/name_review.py): a span that coincides
# with one gene pre-fills the row, a span over several genes is flagged as a
# precursor. The optional LLM gets that evidence and mainly judges whether names
# are specific enough to save. Decisions are applied so that no other feature
# changes name (plan_session_lookup).
import html
import streamlit as st
from pathlib import Path
from typing import Dict, List, Optional
from app.src.alias.alias_manager import load_alias_config
from app.src.alias.gene_alias import normalize_text
from app.src.llm.alias_review import review_unresolved_names
from app.src.io.run_logger import log_error, log_session_decisions
from app.src.lifting.tblastn_lifter import lift_all_tblastn
from ui.components import _card, _chips_html, _render_callout, _render_page_intro, _render_section_title
from ui.guide import _open_guide
from ui.i18n import _t
from ui.name_review import (
    is_specific_name,
    llm_position_context,
    name_patterns,
    names_shared_elsewhere,
    plan_session_lookup,
    position_evidence,
)
from ui.services import _add_new_canonicals_to_config, _load_excluded_names, _save_to_alias_config
from ui.state import _reset


DECISIVE = "match"


def _llm_review_for_row(llm_reviews: Dict, rep: str) -> Dict:
    """The LLM review of this exact row. Rows that merely share a name with it
    are different decisions, so candidates are deliberately not used as keys."""
    if not llm_reviews:
        return {}
    return llm_reviews.get(rep) or llm_reviews.get(normalize_text(rep)) or {}


def _review_context(unknown: Dict[str, Dict]) -> Dict:
    """Position evidence and name patterns for this review, computed once."""
    cached = st.session_state.get("review_context")
    if cached and cached["for"] is unknown:
        return cached

    config_path = st.session_state.alias_config_path
    excluded = _load_excluded_names(Path(config_path)) if config_path else set()
    lookup = st.session_state.alias_lookup or {}
    records = {record.id: record for record in st.session_state.query_records or []}

    def lift(record):
        return lift_all_tblastn(
            st.session_state.ref_features,
            st.session_state.ref_record,
            record,
            min_coverage=st.session_state.min_coverage,
            min_identity=st.session_state.min_identity,
            evalue=st.session_state.evalue,
            rescue_window=st.session_state.rescue_window,
        )

    bar = st.progress(0.0, text=_t("position_checking"))

    def progress(done: int, total: int, record_id: str) -> None:
        bar.progress(done / total if total else 1.0, text=_t("position_progress", done=done, total=total))

    try:
        evidence = position_evidence(
            unknown, records, lookup, excluded, lift, progress, st.session_state.ref_feature_type,
        )
        status = "ok"
    except Exception as e:  # e.g. BLAST+ missing: the review still works without it
        log_error("position check for review names", e)
        evidence, status = {}, "error"
    bar.empty()

    context = {
        "for": unknown,
        "evidence": evidence,
        "status": status,
        "patterns": name_patterns(records.values(), lookup, excluded, st.session_state.ref_feature_type),
    }
    st.session_state.review_context = context
    # Pre-fill each row once from a decisive position; the user's choice then stands.
    for key, row_evidence in evidence.items():
        if row_evidence.get("verdict") == DECISIVE and row_evidence.get("gene") in st.session_state.canonical_list:
            st.session_state.setdefault(f"resolve_{key}", row_evidence["gene"])
    return context


def _position_note(evidence: Dict) -> Optional[str]:
    verdict = evidence.get("verdict")
    if not verdict:
        return None
    values = {
        "gene": evidence.get("gene"),
        "start": f"{evidence.get('start', 0):,}",
        "end": f"{evidence.get('end', 0):,}",
        "iou": evidence.get("iou"),
        "agree": evidence.get("agree", 0),
        "checked": evidence.get("checked", 0),
    }
    genes = evidence.get("genes") or []
    if genes:
        values.update(first=genes[0], last=genes[-1], count=len(genes))
    return _t(f"position_{verdict}", **values)


def _existing_aliases(config_path: Optional[str], limit: int = 12) -> Dict[str, List[str]]:
    if not config_path:
        return {}
    try:
        canonical_names = load_alias_config(Path(config_path)).get("canonical_names", {})
    except (OSError, ValueError):
        return {}
    return {
        canonical: [str(alias) for alias in (aliases if isinstance(aliases, list) else [])][:limit]
        for canonical, aliases in canonical_names.items()
    }


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


def _run_llm_review(unknown_items: Dict, evidence: Dict, virus: str, canonicals: List[str]) -> None:
    # Rows the coordinates could not settle go first: only VIRALIFT_LLM_MAX_ROWS are sent.
    ordered = sorted(unknown_items, key=lambda key: evidence.get(key, {}).get("verdict") == DECISIVE)
    items = {
        key: {**unknown_items[key], "position": llm_position_context(evidence.get(key, {}))}
        for key in ordered
    }
    with st.spinner("Reviewing unresolved names with LLM..."):
        excluded = (
            _load_excluded_names(Path(st.session_state.alias_config_path))
            if st.session_state.alias_config_path
            else set()
        )
        reviews, diagnostics = review_unresolved_names(
            unknown_items=items,
            ambiguous_items={},
            virus_name=virus,
            canonical_names=canonicals,
            excluded_names=excluded,
            cache=st.session_state.llm_alias_review_cache,
            existing_aliases=_existing_aliases(st.session_state.alias_config_path),
        )
    st.session_state.resolve_llm_reviews = reviews
    st.session_state.resolve_llm_diagnostics = diagnostics
    ignore_option = _t("ignore_option")
    for representative in unknown_items:
        review = _llm_review_for_row(reviews, representative)
        if not review or evidence.get(representative, {}).get("verdict") == DECISIVE:
            continue  # a decisive position sets the mapping; the LLM only advises on saving
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
    context = _review_context(unknown) if unknown_items else {"evidence": {}, "patterns": [], "status": "ok"}
    evidence = context["evidence"]

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
                    _run_llm_review(unknown_items, evidence, virus, canonicals)
        st.caption(
            _t("unknown_query_intro", count=len(unknown_items), virus=virus)
            + " " + _t("llm_caption")
        )
        if context["status"] == "error":
            st.caption(_t("position_unavailable"))
        elif evidence:
            verdicts = [row.get("verdict") for row in evidence.values()]
            st.caption(_t(
                "position_summary",
                match=verdicts.count("match"),
                spans=verdicts.count("spans"),
                other=len(verdicts) - verdicts.count("match") - verdicts.count("spans"),
            ))

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
    base_lookup = st.session_state.alias_lookup or {}

    def _current_choice(rep: str) -> Optional[str]:
        choice = st.session_state.get(f"resolve_{rep}")
        return None if not choice or choice.startswith("--") else choice

    # Names a row shares with features meant to end up as something else are
    # never pre-selected for saving: as an alias they would rename those too.
    shared_names = names_shared_elsewhere(
        unknown_items,
        {rep: _current_choice(rep) for rep in unknown_items},
        context["patterns"],
        base_lookup,
    )

    def _default_save_candidate(candidate: str, rep: str, info: Dict, review: Dict) -> bool:
        """Pre-select only the row's first name, and only when it is specific,
        not shared with other outcomes, and not judged too broad by the LLM."""
        return (
            candidate == info["candidates"][0]
            and is_specific_name(candidate)
            and candidate not in shared_names.get(rep, set())
            and review.get("action") != "ignore"
        )

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

            row_evidence = evidence.get(rep, {})
            note = _position_note(row_evidence)
            if note:
                col_action.caption(f":material/my_location: {note}")

            review = _llm_review_for_row(llm_reviews, rep)
            if review:
                action = review.get("action")
                canonical = review.get("canonical_name") or "none"
                confidence = review.get("confidence") or "unknown"
                reason = review.get("reason") or "No reason returned."
                disagree = (
                    row_evidence.get("verdict") == DECISIVE
                    and action == "save_alias"
                    and canonical != row_evidence.get("gene")
                )
                col_action.caption(
                    f":material/auto_awesome: LLM: `{action}` → `{canonical}` ({confidence}). {reason}"
                    + (" " + _t("llm_disagrees", gene=row_evidence.get("gene")) if disagree else "")
                )

            if mapped:
                pill_options = list(dict.fromkeys(str(candidate) for candidate in candidates))
                selected = col_save.pills(
                    _t("save_aliases"),
                    pill_options,
                    selection_mode="multi",
                    default=[c for c in pill_options if _default_save_candidate(c, rep, info, review)],
                    format_func=_short,
                    key=f"save_{rep}",
                    help=_t("save_candidate_help"),
                )
                save_candidates[rep] = list(selected or [])
                risky = sorted(set(save_candidates[rep]) & shared_names.get(rep, set()))
                if risky:
                    col_save.caption(
                        f":material/warning: {_t('shared_name_warning', names=', '.join(risky))}"
                    )
            else:
                col_save.caption(_t("keep_raw_note"))

    # Unknown names (completely unrecognised)
    for index, (rep, info) in enumerate(unknown_items.items()):
        _render_resolver_row(index, rep, info)

    mapped_count = sum(1 for canonical in decisions.values() if canonical)
    session_lookup, blocked = plan_session_lookup(unknown_items, decisions, context["patterns"], base_lookup)
    if blocked:
        _render_callout(
            html.escape(_t("blocked_rows", rows=", ".join(blocked))),
            tone="warn",
            icon="!",
        )
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
        # Session resolver: the names of every decided row, minus any name whose
        # mapping would also rename features outside that row (plan_session_lookup).
        resolver_expanded: Dict[str, str] = dict(session_lookup)

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
