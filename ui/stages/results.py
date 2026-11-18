# Step 3 · Results — run health, a filterable feature table with a detail panel,
# a per-record view, and TSV / FASTA export.
#
# Partial query records (e.g. VP1-only sequences) are common in NCBI downloads.
# Genes that fall outside such a record are shown as "Not in sequence"
# (app/src/lifting/gene_presence.py) and kept out of the pass rate and review counts; the
# engine's own statuses, used by every export, are left untouched.
import dataclasses
import hashlib
import html
from collections import Counter
import pandas as pd
import streamlit as st
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from app.src.io.result_writer import summarize_counts
from app.src.lifting.base import LiftedFeature, PASS_STATUSES
from app.src.lifting.tblastn_lifter import process_one_query_record
from ui.components import (
    _card,
    _error_by_record,
    _format_fraction_percent,
    _format_percent,
    _kv_html,
    _pill_column,
    _render_callout,
    _render_page_intro,
    _render_section_title,
    _render_stats,
    _render_status_bar,
    _sequence_html,
    _status_badge,
    _status_cell,
    _status_column,
)
from app.src.lifting.gene_presence import NOT_IN_SEQUENCE, missing_genes_outside_record, nothing_located
from ui.fasta_names import FIELDS, MISSING, PRESETS, SEPARATORS, build_header, load_settings, make_unique, record_metadata, save_settings
from ui.guide import FEATURE_COLUMN_HELP, RECORD_COLUMN_HELP, _open_guide, _render_table_help
from ui.i18n import _t
from ui.services import _canonical_to_ref_map, _results_to_df, _selected_dataframe_rows
from ui.state import GOOD_STATUSES, REVIEW_STATUSES, _reset


# (query_id, feature, display gene name) — one entry per feature row.
FeatureRow = Tuple[str, LiftedFeature, str]

MANUALLY_APPROVABLE_STATUSES = {
    "invalid_boundaries",
    "low_coverage",
    "low_identity",
    "low_coverage_and_identity",
    "overlong_annotation",
}

FEATURE_COLUMNS = {
    "Record": st.column_config.TextColumn("Record", help=FEATURE_COLUMN_HELP["Record"]),
    "Gene": st.column_config.TextColumn("Gene", help=FEATURE_COLUMN_HELP["Gene"]),
    "Status": _status_column(FEATURE_COLUMN_HELP["Status"]),
    "Method": st.column_config.TextColumn("Method", width="small", help=FEATURE_COLUMN_HELP["Method"]),
    "Check": st.column_config.TextColumn("Check", width="medium", help=FEATURE_COLUMN_HELP["Check"]),
    "Start": st.column_config.TextColumn("Start", alignment="right", help=FEATURE_COLUMN_HELP["Start"]),
    "End": st.column_config.TextColumn("End", alignment="right", help=FEATURE_COLUMN_HELP["End"]),
    "Length": st.column_config.TextColumn("Length (nt)", alignment="right", help=FEATURE_COLUMN_HELP["Length"]),
    "Strand": st.column_config.TextColumn(
        "Strand", width="small", alignment="center", help=FEATURE_COLUMN_HELP["Strand"]
    ),
    "Coverage": st.column_config.NumberColumn("Coverage", format="%.1f%%", help=FEATURE_COLUMN_HELP["Coverage"]),
    "Identity": st.column_config.TextColumn("Identity", alignment="right", help=FEATURE_COLUMN_HELP["Identity"]),
    "Raw name": st.column_config.TextColumn("Raw name", help=FEATURE_COLUMN_HELP["Raw name"]),
}

RECORD_HEALTH_TONE = {
    "passed": "ok",
    "partial": "info",
    "needs_review": "warn",
    "no_genes": "warn",
    "failed": "danger",
    "empty": "neutral",
}
RECORD_HEALTH_LABELS = {
    "passed": _t("passed"),
    "partial": _t("health_partial"),
    "needs_review": _t("needs_review"),
    "no_genes": _t("health_no_genes"),
    "failed": _t("failed"),
    "empty": _t("empty"),
}
RECORD_COLUMNS = {
    "Record": st.column_config.TextColumn("Record", help=RECORD_COLUMN_HELP["Record"]),
    "Health": _pill_column(
        "Health", RECORD_HEALTH_TONE, RECORD_HEALTH_TONE.get, RECORD_HEALTH_LABELS.get,
        help=RECORD_COLUMN_HELP["Health"], width=140,
    ),
    "Length": st.column_config.NumberColumn("Length (bp)", format="%d", help=RECORD_COLUMN_HELP["Length"]),
    "Features": st.column_config.NumberColumn("Features", format="%d", help=RECORD_COLUMN_HELP["Features"]),
    "In sequence": st.column_config.NumberColumn("In sequence", format="%d", help=RECORD_COLUMN_HELP["In sequence"]),
    "Pass rate": st.column_config.NumberColumn("Pass rate", format="%.0f%%", help=RECORD_COLUMN_HELP["Pass rate"]),
    "Needs review": st.column_config.NumberColumn("Needs review", format="%d", help=RECORD_COLUMN_HELP["Needs review"]),
    "Method": st.column_config.TextColumn("Method", help=RECORD_COLUMN_HELP["Method"]),
    "Error": st.column_config.TextColumn("Error", width="large", help=RECORD_COLUMN_HELP["Error"]),
}
METHOD_TAG_LABELS = {
    "direct": _t("method_direct"),
    "tblastn": _t("method_tblastn"),
    "tblastn + direct": _t("method_both"),
    "none": "—",
}


def _export_key(query_id: str, feature: LiftedFeature, gene: str) -> str:
    return "|".join(
        str(value)
        for value in (
            query_id,
            gene,
            feature.status,
            feature.query_start,
            feature.query_end,
            feature.strand,
        )
    )


def _boundary_check(feature: LiftedFeature) -> str:
    checks = []
    for label, value in (
        ("start", feature.has_start_codon),
        ("stop", feature.has_stop_codon),
        ("frame", feature.in_frame),
    ):
        if value is not None:
            checks.append(f"{label} {'✓' if value else '✗'}")
    return " · ".join(checks)


def _rescue_action(feature: LiftedFeature) -> str:
    if feature.rescue_action:
        return feature.rescue_action
    if feature.rescue_target and feature.rescue_offset is not None:
        return f"{feature.rescue_target} {feature.rescue_offset:+d} bp"
    if feature.rescue_offset is not None:
        return f"start {feature.rescue_offset:+d} bp"
    return ""


def _status_group(status: str) -> str:
    if status == NOT_IN_SEQUENCE:
        return "absent"
    if status in REVIEW_STATUSES:
        return "review"
    if status in GOOD_STATUSES:
        return "passed"
    return "other"


def _record_health(query_id: str, features: List[LiftedFeature], error_map: Dict[str, str]) -> str:
    if query_id in error_map:
        return "failed"
    if not features:
        return "empty"
    if nothing_located(features):
        return "no_genes"
    if any(f.status in REVIEW_STATUSES for f in features):
        return "needs_review"
    if any(f.status == NOT_IN_SEQUENCE for f in features):
        return "partial"
    return "passed"


def _method_tag(features: List[LiftedFeature]) -> str:
    methods = {f.method for f in features if f.method}
    if methods == {"direct"}:
        return "direct"
    if "tblastn" in methods and "direct" not in methods:
        return "tblastn"
    if methods:
        return "tblastn + direct"
    return "none"


Results = List[Tuple[str, List[LiftedFeature]]]


def _choice_key(query_id: str, name: str) -> str:
    return f"{query_id}\x1f{name}"


def _chosen_results(all_results: Results) -> Results:
    """The run's rows with the user's annotation / tblastn choices applied."""
    choices = st.session_state.get("annotation_choices") or {}
    if not choices:
        return all_results
    return [
        (query_id, [
            choices.get(_choice_key(query_id, f.name), f) if f.ref_start is not None else f
            for f in features
        ])
        for query_id, features in all_results
    ]


def _run_views(all_results: Results) -> Tuple[Results, Results]:
    """(chosen, display): the rows every export uses, and the same rows with the
    `no_hit` genes that lie outside their record shown as not_in_sequence.
    Cached per run and choice: placing ~100k features takes a moment."""
    version = st.session_state.get("annotation_choice_version", 0)
    cached = st.session_state.get("display_results")
    if cached and cached[0] is all_results and cached[1] == version:
        return cached[2], cached[3]
    chosen = _chosen_results(all_results)
    lengths = {record.id: len(record.seq) for record in st.session_state.query_records or []}
    ref_strands = {f["name"]: f.get("strand", "+") for f in st.session_state.ref_features or []}
    display = []
    for query_id, features in chosen:
        outside = set(missing_genes_outside_record(features, lengths.get(query_id, 0), ref_strands))
        display.append((query_id, [
            dataclasses.replace(f, status=NOT_IN_SEQUENCE) if index in outside else f
            for index, f in enumerate(features)
        ]))
    st.session_state.display_results = (all_results, version, chosen, display)
    return chosen, display


def _display_results(all_results: Results) -> Results:
    return _run_views(all_results)[1]


def _check_cell(lf: LiftedFeature) -> str:
    """The annotation check's verdict on a gene taken from the record's annotation."""
    if not lf.annotation_check:
        return ""
    label = _t(f"check_{lf.annotation_check}")
    if lf.best_match:
        label = _t("check_looks_like", verdict=label, gene=lf.best_match)
    if lf.annotation is not None:
        label = _t("check_replaced", verdict=label)
    return label


def _method_label(method: Optional[str]) -> str:
    return _t(f"method_{method}") if method in {"direct", "tblastn"} else (method or "")


def _feature_length(feature: LiftedFeature) -> Optional[int]:
    if feature.query_start is None or feature.query_end is None:
        return None
    return feature.query_end - feature.query_start + 1


# Numbers that can be missing are shown as text: st.dataframe prints a null
# number as a literal "None", and unplaced genes have no coordinates. Text
# columns sort with localeCompare, where space-padding to a fixed width keeps
# numeric order and "" sorts first.
def _identity_cell(identity: Optional[float]) -> str:
    return f"{identity:5.1f}%" if identity is not None else ""


def _position_cell(value: Optional[int]) -> str:
    return f"{value:9d}" if value is not None else ""


def _feature_frame(rows: List[FeatureRow]) -> pd.DataFrame:
    frame = pd.DataFrame(
        [
            {
                "Record": query_id,
                "Gene": gene,
                "Status": _status_cell(lf.status),
                "Method": _method_label(lf.method),
                "Check": _check_cell(lf),
                "Start": _position_cell(lf.query_start),
                "End": _position_cell(lf.query_end),
                "Length": _position_cell(_feature_length(lf)),
                # A gene that was never placed has no strand on this record.
                "Strand": "" if lf.query_start is None else "−" if lf.strand == "-" else lf.strand,
                "Coverage": lf.coverage * 100 if lf.coverage is not None else None,
                "Identity": _identity_cell(lf.identity),
                "Raw name": lf.source_name or "",
            }
            for query_id, lf, gene in rows
        ],
        columns=list(FEATURE_COLUMNS),
    )
    frame["Coverage"] = pd.to_numeric(frame["Coverage"], errors="coerce")
    return frame


def _table_height(rows: int, cap: int = 520) -> int:
    return min(cap, 38 + 35 * max(rows, 1))


def _approved_export_keys() -> set:
    return set(st.session_state.get("approved_export_features", []))


def _save_approved_export_keys(keys: set) -> None:
    st.session_state.approved_export_features = sorted(keys)


def _clear_approvals() -> None:
    st.session_state.approved_export_features = []
    st.session_state.pop("fasta_approval_editor", None)


def _render_feature_detail(query_id: str, lf: LiftedFeature, gene: str) -> None:
    approved = _export_key(query_id, lf, gene) in _approved_export_keys()
    coords = (
        f"{lf.query_start:,}–{lf.query_end:,} ({lf.strand})"
        if lf.query_start is not None and lf.query_end is not None
        else "not mapped"
    )
    ref_coords = (
        f"{lf.ref_start:,}–{lf.ref_end:,}"
        if lf.ref_start is not None and lf.ref_end is not None
        else "—"
    )
    items = [
        ("Raw name", lf.source_name or "—"),
        ("Query coordinates", coords),
        ("Reference coordinates", ref_coords),
        ("Length", f"{len(lf.sequence):,} nt" if lf.sequence else "—"),
        ("Coverage · identity", f"{_format_fraction_percent(lf.coverage)} · {_format_percent(lf.identity)}"),
        ("Boundary check", _boundary_check(lf) or "—"),
        ("Rescue action", _rescue_action(lf) or "—"),
        ("Bit score", f"{lf.score:.1f}" if lf.score is not None else "—"),
    ]
    head = (
        "<div class='vl-detail-head'>"
        f"<span class='vl-detail-title'>{html.escape(query_id)} · {html.escape(gene)}</span>"
        f"{_status_badge(lf.status)}"
        f"<span class='vl-chip'>{html.escape(lf.method or 'unknown')}</span>"
        + ("<span class='vl-chip is-primary'>approved for FASTA</span>" if approved else "")
        + "</div>"
    )
    explain_key = {
        "invalid_boundaries": "invalid_boundary_help",
        NOT_IN_SEQUENCE: "not_in_sequence_help",
    }.get(lf.status)
    explain = f"<div class='vl-explain'>{html.escape(_t(explain_key))}</div>" if explain_key else ""
    sequence = _sequence_html(lf.sequence) if lf.sequence else ""
    with _card("feature_detail"):
        st.html(head + _kv_html(items) + explain)
        _render_annotation_check(query_id, lf, gene)
        if sequence:
            st.html(sequence)


def _span_length(feature: LiftedFeature) -> str:
    length = _feature_length(feature)
    return f"{length:,}" if length is not None else "—"


def _set_choice(query_id: str, name: str, row: Optional[LiftedFeature]) -> None:
    """Use `row` for this gene from now on; None goes back to the run's own row."""
    choices = dict(st.session_state.get("annotation_choices") or {})
    if row is None:
        choices.pop(_choice_key(query_id, name), None)
    else:
        choices[_choice_key(query_id, name)] = row
    st.session_state.annotation_choices = choices
    st.session_state.annotation_choice_version = st.session_state.get("annotation_choice_version", 0) + 1


def _run_row(query_id: str, name: str) -> Optional[LiftedFeature]:
    """The pipeline's own row for this gene, before any choice."""
    for record_id, features in st.session_state.all_results or []:
        if record_id == query_id:
            return next((f for f in features if f.name == name and f.ref_start is not None), None)
    return None


def _manual_lift(query_id: str) -> List[LiftedFeature]:
    """tblastn over the whole record, as the pipeline would lift it (cached)."""
    lifts = st.session_state.manual_lifts
    if query_id not in lifts:
        record = next(r for r in st.session_state.query_records if r.id == query_id)
        lifts[query_id] = process_one_query_record(
            ref_record=st.session_state.ref_record,
            query_record=record,
            ref_cds=st.session_state.ref_features,
            ref_feature_type=st.session_state.ref_feature_type,
            min_coverage=st.session_state.min_coverage,
            min_identity=st.session_state.min_identity,
            evalue=st.session_state.evalue,
            rescue_window=st.session_state.rescue_window,
            quiet=True,
        )
    return lifts[query_id]


def _render_annotation_check(query_id: str, lf: LiftedFeature, gene: str) -> None:
    """Annotation vs tblastn for a gene taken from the record's annotation, with
    the switch between them."""
    annotated = lf.annotation if lf.annotation is not None else lf
    if annotated.method != "direct" or annotated.ref_start is None or lf.status == NOT_IN_SEQUENCE:
        return
    lines = []
    if annotated.annotation_check:
        lines.append(_t(
            "check_annotation_line",
            start=f"{annotated.query_start:,}",
            end=f"{annotated.query_end:,}",
            length=_span_length(annotated),
            ref_length=f"{annotated.ref_end - annotated.ref_start + 1:,}",
            coverage=_format_fraction_percent(annotated.coverage),
            identity=_format_percent(annotated.identity),
        ))
        if annotated.best_match:
            lines.append(_t("check_best_match", gene=annotated.best_match, name=gene))

    run_row = _run_row(query_id, lf.name)
    action: Optional[Tuple[str, Optional[LiftedFeature]]] = None  # (label, row to use)
    check_button = False
    if lf.annotation is not None:
        lines.append(_t("check_using_tblastn", start=f"{lf.query_start:,}", end=f"{lf.query_end:,}", length=_span_length(lf)))
        back = None if run_row is not None and run_row.annotation is None else lf.annotation
        action = (_t("use_annotation"), back)
    elif run_row is not None and run_row.annotation is not None:
        lines.append(_t(
            "check_using_annotation", gene=gene, start=f"{run_row.query_start:,}",
            end=f"{run_row.query_end:,}", length=_span_length(run_row), status=run_row.status,
        ))
        action = (_t("use_tblastn"), None)
    elif query_id in st.session_state.manual_lifts:
        alternative = next((f for f in _manual_lift(query_id) if f.name == lf.name), None)
        if alternative is None or alternative.status not in PASS_STATUSES or alternative.query_start is None:
            lines.append(_t("check_tblastn_none", gene=gene, status=alternative.status if alternative else "no_hit"))
        elif (alternative.query_start, alternative.query_end) == (lf.query_start, lf.query_end):
            lines.append(_t("check_tblastn_same", gene=gene, status=alternative.status))
        else:
            lines.append(_t(
                "check_using_annotation", gene=gene, start=f"{alternative.query_start:,}",
                end=f"{alternative.query_end:,}", length=_span_length(alternative), status=alternative.status,
            ))
            action = (_t("use_tblastn"), dataclasses.replace(
                alternative,
                source_name=lf.source_name,
                annotation_check=lf.annotation_check,
                best_match=lf.best_match,
                annotation=lf,
            ))
    else:
        check_button = True

    verdict = _check_cell(lf)
    st.html(
        "<div class='vl-explain'>"
        f"<b>{html.escape(_t('check_section'))}</b>"
        + (f" · {html.escape(verdict)}" if verdict else "")
        + "".join(f"<br>{html.escape(line)}" for line in lines)
        + "</div>"
    )
    if action:
        label, row = action
        st.button(
            label, key=f"check_choice_{query_id}_{lf.name}", icon=":material/swap_horiz:",
            on_click=_set_choice, args=(query_id, lf.name, row),
        )
    elif check_button and st.button(
        _t("check_with_tblastn"), key=f"check_tblastn_{query_id}_{lf.name}",
        icon=":material/manage_search:", help=_t("check_with_tblastn_help"),
    ):
        with st.spinner(_t("checking_tblastn", record=query_id)):
            _manual_lift(query_id)
        st.rerun()


def _filter_signature(*parts: object) -> str:
    return hashlib.md5(repr(parts).encode("utf-8")).hexdigest()[:10]


def _render_features_view(rows: List[FeatureRow]) -> None:
    group_counts = {"in_sequence": 0, "review": 0, "passed": 0, "other": 0, "absent": 0, "all": len(rows)}
    for _, lf, _ in rows:
        group = _status_group(lf.status)
        group_counts[group] += 1
        if group != "absent":
            group_counts["in_sequence"] += 1
    group_labels = {
        "in_sequence": _t("filter_in_sequence"),
        "review": _t("filter_review"),
        "passed": _t("filter_passed"),
        "other": _t("filter_other"),
        "absent": _t("filter_absent"),
        "all": _t("filter_all"),
    }
    # With partial records most rows are "not in sequence", so the table opens
    # on the genes that are actually there.
    first = "in_sequence" if group_counts["absent"] else "all"
    show_options = [first] + [
        group for group in ("review", "passed", "other", "absent") if group_counts[group]
    ] + (["all"] if first != "all" else [])
    method_labels = {
        "any": _t("filter_any_method"),
        "direct": _t("method_direct"),
        "tblastn": _t("method_tblastn"),
    }

    selected_row: Optional[FeatureRow] = None
    with _card("features"):
        # The title shows the live row count, so it is filled in after the filters run.
        with st.container(horizontal=True, horizontal_alignment="distribute", vertical_alignment="center"):
            title_slot = st.empty()
            _render_table_help(FEATURE_COLUMN_HELP, key="features_table_help")

        with st.container(horizontal=True, vertical_alignment="center", gap="small"):
            show = st.segmented_control(
                _t("filter_show"),
                show_options,
                format_func=lambda group: f"{group_labels[group]} · {group_counts[group]:,}",
                default=first,
                required=True,
                key="results_show",
                label_visibility="collapsed",
            )
            method = st.segmented_control(
                _t("filter_method"),
                list(method_labels),
                format_func=method_labels.get,
                default="any",
                required=True,
                key="results_method",
                label_visibility="collapsed",
            )
            genes = st.multiselect(
                _t("filter_genes"),
                sorted({gene for _, _, gene in rows}),
                placeholder=_t("all_genes"),
                key="results_genes",
                label_visibility="collapsed",
                width=240,
            )
            search = st.text_input(
                _t("search_feature"),
                placeholder=_t("search_feature"),
                icon=":material/search:",
                key="results_search",
                label_visibility="collapsed",
            ).strip().lower()

        visible = [
            (query_id, lf, gene)
            for query_id, lf, gene in rows
            if (
                show == "all"
                or _status_group(lf.status) == show
                or (show == "in_sequence" and _status_group(lf.status) != "absent")
            )
            and (method == "any" or lf.method == method)
            and (not genes or gene in genes)
            and (not search or search in query_id.lower() or search in gene.lower())
        ]
        with title_slot:
            _render_section_title(
                _t("feature_table"),
                _t("feature_table_caption", shown=f"{len(visible):,}", total=f"{len(rows):,}"),
            )
        if not visible:
            st.info(_t("no_rows"))
            return

        # The hint sits above the table so the table's hover toolbar has room
        # and does not cover the search box.
        st.caption(_t("select_hint"))
        # A new key per filter combination resets the selection when the visible
        # rows change, so a stale row index never points at a different feature.
        event = st.dataframe(
            _feature_frame(visible),
            column_config=FEATURE_COLUMNS,
            hide_index=True,
            height=_table_height(len(visible)),
            on_select="rerun",
            selection_mode="single-row",
            key=f"results_features_{_filter_signature(show, method, tuple(genes), search, st.session_state.get('annotation_choice_version', 0))}",
        )
        selected = _selected_dataframe_rows(event)
        if selected and selected[0] < len(visible):
            selected_row = visible[selected[0]]

    if selected_row:
        _render_feature_detail(*selected_row)


def _render_records_view(
    all_results: List[Tuple[str, List[LiftedFeature]]],
    rows: List[FeatureRow],
    error_map: Dict[str, str],
) -> None:
    lengths = {record.id: len(record.seq) for record in st.session_state.query_records or []}
    overview = []
    for query_id, features in all_results:
        total = len(features)
        in_sequence = sum(1 for f in features if f.status != NOT_IN_SEQUENCE)
        passed = sum(1 for f in features if f.status in GOOD_STATUSES)
        health = _record_health(query_id, features, error_map)
        overview.append({
            "health_key": health,
            "Record": query_id,
            "Health": [health],
            "Length": lengths.get(query_id),
            "Features": total,
            "In sequence": in_sequence,
            "Pass rate": passed / in_sequence * 100 if in_sequence else 0.0,
            "Needs review": sum(1 for f in features if f.status in REVIEW_STATUSES),
            "Method": METHOD_TAG_LABELS[_method_tag(features)],
            "Error": error_map.get(query_id, ""),
        })

    present = [h for h in RECORD_HEALTH_LABELS if any(row["health_key"] == h for row in overview)]
    record_id: Optional[str] = None
    with _card("records"):
        with st.container(horizontal=True, horizontal_alignment="distribute", vertical_alignment="center"):
            title_slot = st.empty()
            _render_table_help(RECORD_COLUMN_HELP, key="records_table_help", status_legend=False)

        with st.container(horizontal=True, vertical_alignment="center", gap="small"):
            health = st.segmented_control(
                _t("health_filter"),
                ["all"] + present,
                format_func=lambda h: _t("filter_all") if h == "all" else RECORD_HEALTH_LABELS[h],
                default="all",
                required=True,
                key="results_record_health",
                label_visibility="collapsed",
            )
            search = st.text_input(
                _t("search_record"),
                placeholder=_t("search_record"),
                icon=":material/search:",
                key="results_record_search",
                label_visibility="collapsed",
            ).strip().lower()

        visible = [
            row for row in overview
            if (health == "all" or row["health_key"] == health)
            and (not search or search in row["Record"].lower())
        ]
        with title_slot:
            _render_section_title(
                _t("record_table"),
                _t("record_table_caption", shown=f"{len(visible):,}", total=f"{len(overview):,}"),
            )
        if not visible:
            st.info(_t("no_rows"))
            return

        st.caption(_t("select_record_hint"))
        event = st.dataframe(
            pd.DataFrame(visible, columns=["health_key", *RECORD_COLUMNS]).drop(columns=["health_key"]),
            column_config=RECORD_COLUMNS,
            hide_index=True,
            height=_table_height(len(visible), cap=420),
            on_select="rerun",
            selection_mode="single-row",
            key=f"results_records_{_filter_signature(health, search)}",
        )
        selected = _selected_dataframe_rows(event)
        if selected and selected[0] < len(visible):
            record_id = visible[selected[0]]["Record"]

    if record_id is None:
        return
    record_rows = [row for row in rows if row[0] == record_id]
    with _card("record_detail"):
        _render_section_title(record_id, f"{len(record_rows)} feature(s)")
        if record_id in error_map:
            st.error(error_map[record_id])
        elif not record_rows:
            st.warning(_t("no_features"))
        else:
            st.dataframe(
                _feature_frame(record_rows).drop(columns=["Record"]),
                column_config=FEATURE_COLUMNS,
                hide_index=True,
                height=_table_height(len(record_rows), cap=420),
            )


def _render_approval_editor(rows: List[FeatureRow]) -> None:
    review_candidates = [
        (query_id, lf, gene)
        for query_id, lf, gene in rows
        if lf.status in MANUALLY_APPROVABLE_STATUSES and lf.sequence
    ]
    if not review_candidates:
        return

    approved_keys = _approved_export_keys()
    candidate_keys = [_export_key(query_id, lf, gene) for query_id, lf, gene in review_candidates]
    with st.expander(
        f"{_t('manual_approve_features')} ({len(review_candidates)})",
        expanded=bool(approved_keys),
    ):
        st.caption(_t("manual_approve_help"))
        base = _feature_frame(review_candidates).drop(columns=["Method", "Raw name"])
        base.insert(0, "Approve", [key in approved_keys for key in candidate_keys])
        edited = st.data_editor(
            base,
            column_config={
                **FEATURE_COLUMNS,
                "Approve": st.column_config.CheckboxColumn(_t("approve_column"), width="small"),
            },
            disabled=[column for column in base.columns if column != "Approve"],
            hide_index=True,
            height=_table_height(len(base), cap=380),
            key="fasta_approval_editor",
        )
        updated = (approved_keys - set(candidate_keys)) | {
            key for key, flag in zip(candidate_keys, edited["Approve"]) if flag
        }
        if updated != approved_keys:
            _save_approved_export_keys(updated)

        with st.container(horizontal=True, horizontal_alignment="distribute", vertical_alignment="center"):
            st.caption(_t("approved_export_count", count=len(updated)))
            st.button(
                _t("clear_approvals"),
                key="clear_fasta_approvals",
                disabled=not updated,
                on_click=_clear_approvals,
            )


def _record_metadata(query_id: str) -> Dict[str, str]:
    """Source metadata of a query record, cached for the run."""
    cache = st.session_state.setdefault("record_metadata", {})
    if query_id not in cache:
        record = next((r for r in st.session_state.query_records or [] if r.id == query_id), None)
        cache[query_id] = record_metadata(record) if record is not None else {"accession": query_id}
    return cache[query_id]


def _fasta_header(settings: Dict, query_id: str, lf: LiftedFeature, gene: str) -> str:
    return build_header(
        settings["fields"], settings["separator"], settings["missing"], _record_metadata(query_id), gene, lf,
    )


def _apply_name_preset(name: str) -> None:
    preset = PRESETS[name]
    st.session_state.fasta_name_fields = list(preset["fields"])
    st.session_state.fasta_name_separator = preset["separator"]
    st.session_state.fasta_name_missing = preset["missing"]
    _save_name_settings()


def _current_name_settings() -> Dict:
    return {
        "fields": list(st.session_state.get("fasta_name_fields") or []),
        "separator": st.session_state.get("fasta_name_separator"),
        "missing": st.session_state.get("fasta_name_missing"),
    }


def _save_name_settings() -> None:
    """Remember the naming for the next run and the next session."""
    try:
        save_settings(_current_name_settings())
    except OSError:
        pass  # a read-only config folder only loses the convenience


def _render_fasta_name_controls() -> Dict:
    """The sequence-name picker; returns the settings to build headers with."""
    if "fasta_name_fields" not in st.session_state:
        saved = load_settings()
        st.session_state.fasta_name_fields = saved["fields"]
        st.session_state.fasta_name_separator = saved["separator"]
        st.session_state.fasta_name_missing = saved["missing"]

    with st.container(horizontal=True, horizontal_alignment="distribute", vertical_alignment="center"):
        st.markdown(f"**{_t('fasta_names')}**")
        with st.container(horizontal=True, gap="small", width="content"):
            st.button(_t("fasta_names_default"), key="fasta_preset_default", type="tertiary",
                      on_click=_apply_name_preset, args=("default",))
            st.button(_t("fasta_names_isolate_host"), key="fasta_preset_isolate_host", type="tertiary",
                      on_click=_apply_name_preset, args=("accession_isolate_host",))
    col_fields, col_sep, col_missing = st.columns([4, 1, 1])
    col_fields.multiselect(
        _t("fasta_name_fields"), list(FIELDS), format_func=FIELDS.get, key="fasta_name_fields",
        help=_t("fasta_name_fields_help"), on_change=_save_name_settings,
    )
    col_sep.segmented_control(
        _t("fasta_name_separator"), list(SEPARATORS), required=True, key="fasta_name_separator",
        on_change=_save_name_settings,
    )
    col_missing.segmented_control(
        _t("fasta_name_missing"), list(MISSING), required=True, key="fasta_name_missing",
        help=_t("fasta_name_missing_help"), on_change=_save_name_settings,
    )
    settings = _current_name_settings()
    if not settings["fields"]:
        settings["fields"] = ["accession"]
    return settings


def _render_export_view(
    rows: List[FeatureRow],
    df: pd.DataFrame,
    ref_name_map: Optional[Dict[str, str]],
) -> None:
    with _card("tsv"):
        _render_section_title(_t("tsv"), _t("download_table"))
        tsv_canonical = df.drop(columns=["sequence"]).to_csv(sep="\t", index=False)
        df_raw = df.copy()
        has_source = df_raw["source_name"].notna() & (df_raw["source_name"] != "")
        df_raw.loc[has_source, "name"] = df_raw.loc[has_source, "source_name"]
        tsv_raw = df_raw.drop(columns=["sequence"]).to_csv(sep="\t", index=False)
        with st.container(horizontal=True):
            st.download_button(
                _t("download_display"),
                data=tsv_canonical,
                file_name="viralift_canonical.tsv",
                mime="text/tab-separated-values",
                icon=":material/download:",
                on_click="ignore",
            )
            st.download_button(
                _t("download_raw"),
                data=tsv_raw,
                file_name="viralift_raw.tsv",
                mime="text/tab-separated-values",
                icon=":material/download:",
                on_click="ignore",
            )

    with _card("fasta"):
        _render_section_title(_t("fasta"), _t("fasta_intro"))

        # gene list: display names respect the use_ref_names toggle
        ref_gene_names = sorted({
            (ref_name_map.get(f.get("name"), f.get("name")) if ref_name_map else f.get("name"))
            for f in st.session_state.ref_features
            if f.get("name")
        })

        col_select, col_format = st.columns([3, 2])
        selected_genes = col_select.multiselect(
            _t("genes_to_extract"),
            options=ref_gene_names,
            default=ref_gene_names,
        )
        fasta_mode = col_format.segmented_control(
            _t("output_format"),
            [_t("one_fasta"), _t("all_fasta")],
            default=_t("one_fasta"),
            required=True,
            key="fasta_mode",
        )

        name_settings = _render_fasta_name_controls()

        st.markdown(f"**{_t('quality_filter')}**")
        qf_col1, qf_col2, qf_col3, qf_col4 = st.columns(4, vertical_alignment="center")
        min_cov_export = qf_col1.slider(_t("min_coverage"), 0.0, 1.0, 0.5, 0.05)
        min_id_export  = qf_col2.slider(_t("min_identity"),  0.0, 100.0, 0.0, 5.0)
        include_rescued = qf_col3.checkbox(_t("include_rescued"), value=True)
        include_extrapolated = qf_col4.checkbox(_t("include_extrapolated"), value=True)

        accepted_statuses = {"ok", "direct"}
        if include_rescued:
            accepted_statuses.add("ok_rescued")
        if include_extrapolated:
            accepted_statuses.add("ok_extrapolated")

        _render_approval_editor(rows)
        approved_review_keys = _approved_export_keys()

        def _passes_fasta_filters(query_id: str, feature: LiftedFeature, gene: str) -> bool:
            if gene not in selected_genes or not feature.sequence:
                return False
            if _export_key(query_id, feature, gene) in approved_review_keys:
                return True
            if feature.status not in accepted_statuses:
                return False
            if feature.coverage is not None and feature.coverage < min_cov_export:
                return False
            if feature.identity is not None and feature.identity < min_id_export:
                return False
            return True

        candidates = [(query_id, lf, gene) for query_id, lf, gene in rows if _passes_fasta_filters(query_id, lf, gene)]
        candidate_count = len(candidates)
        if candidates:
            # Preview the first file as it will be downloaded.
            if fasta_mode == _t("all_fasta"):
                file_name = "all_genes.fasta"
                first_file = [row for gene in selected_genes for row in candidates if row[2] == gene]
                if "gene" not in name_settings["fields"] and len(selected_genes) > 1:
                    st.caption(_t("fasta_names_add_gene"))
            else:
                first_gene = next(gene for gene in selected_genes if any(row[2] == gene for row in candidates))
                file_name = f"{first_gene}.fasta"
                first_file = [row for row in candidates if row[2] == first_gene]
            headers = make_unique([_fasta_header(name_settings, *row) for row in first_file], name_settings["separator"])
            st.caption(_t("fasta_name_preview", file=file_name))
            st.code("\n".join(f">{header}" for header in headers[:3]), language=None)

        with st.container(horizontal=True, horizontal_alignment="distribute", vertical_alignment="center"):
            st.caption(_t("candidate_count", count=candidate_count))
            generate = st.button(
                _t("generate_fasta"),
                icon=":material/genetics:",
                type="primary",
                disabled=not candidate_count,
            )

        if generate:
            # gene -> [(header, sequence)], keyed by display name
            gene_entries: Dict[str, List[Tuple[str, str]]] = {g: [] for g in selected_genes}
            skipped = 0

            for query_id, lf, gene in rows:
                if gene not in gene_entries:
                    continue
                if not _passes_fasta_filters(query_id, lf, gene):
                    skipped += 1
                    continue
                gene_entries[gene].append((_fasta_header(name_settings, query_id, lf, gene), lf.sequence))

            # Names must be unique within each downloaded file.
            separator = name_settings["separator"]
            renamed = 0
            if fasta_mode == _t("all_fasta"):
                entries = [entry for gene in selected_genes for entry in gene_entries[gene]]
                headers = make_unique([header for header, _ in entries], separator)
                renamed += sum(1 for (header, _), new in zip(entries, headers) if header != new)
                gene_seqs = {"all": [f">{h}\n{seq}" for h, (_, seq) in zip(headers, entries)]}
            else:
                gene_seqs = {}
                for gene in selected_genes:
                    headers = make_unique([header for header, _ in gene_entries[gene]], separator)
                    renamed += sum(1 for (header, _), new in zip(gene_entries[gene], headers) if header != new)
                    gene_seqs[gene] = [f">{h}\n{seq}" for h, (_, seq) in zip(headers, gene_entries[gene])]

            if fasta_mode == _t("all_fasta"):
                all_seqs = "\n".join(gene_seqs["all"])
                st.download_button(
                    _t("download_all_fasta"),
                    data=all_seqs,
                    file_name="all_genes.fasta",
                    mime="text/plain",
                    icon=":material/download:",
                    type="primary",
                    on_click="ignore",
                )
            else:
                # one download button per gene
                empty_genes = [gene for gene in selected_genes if not gene_seqs[gene]]
                with st.container(horizontal=True):
                    for gene in selected_genes:
                        seqs = gene_seqs[gene]
                        if not seqs:
                            continue
                        st.download_button(
                            _t("gene_download", gene=gene, count=len(seqs)),
                            data="\n".join(seqs),
                            file_name=f"{gene}.fasta",
                            mime="text/plain",
                            icon=":material/download:",
                            key=f"dl_{gene}",
                            on_click="ignore",
                        )
                for gene in empty_genes:
                    st.warning(_t("no_sequences", gene=gene))

            if skipped:
                st.caption(_t("skipped", count=skipped))
            if renamed:
                st.caption(_t("fasta_names_renamed", count=renamed))


def _render_check_banner(rows: List[FeatureRow]) -> None:
    checked = [lf for _, lf, _ in rows if lf.annotation_check]
    if not checked:
        return
    counts = Counter(lf.annotation_check for lf in checked)
    issues = "".join(
        f" · {_t('annotation_check_issue', count=f'{counts[v]:,}', label=_t(f'check_{v}').lower())}"
        for v in ("partial", "fragment", "low_identity", "overlong") if counts[v]
    )
    replaced = sum(1 for lf in checked if lf.annotation is not None)
    _render_callout(
        _t(
            "annotation_check_banner",
            confirmed=f"{counts['confirmed']:,}",
            checked=f"{len(checked):,}",
            issues=html.escape(issues),
            replaced=_t("annotation_check_replaced", count=f"{replaced:,}") if replaced else "",
        ),
        tone="info",
    )


def stage_results():
    all_results, display_results = _run_views(st.session_state.all_results)
    summary     = summarize_counts(display_results)
    run_errors  = st.session_state.run_errors or []
    error_map   = _error_by_record(run_errors)

    # build ref name map if user wants ref names as output
    # {canonical_key: ref_raw_name}  e.g. {"Lpro": "Lab", "3Cpro": "3C", ...}
    ref_name_map: Optional[Dict[str, str]] = (
        _canonical_to_ref_map(st.session_state.ref_features)
        if st.session_state.use_ref_names else None
    )

    # Exports use the engine's statuses; the views use the display ones.
    df = _results_to_df(all_results, ref_name_map)
    rows: List[FeatureRow] = [
        (query_id, lf, ref_name_map.get(lf.name, lf.name) if ref_name_map else lf.name)
        for query_id, features in display_results
        for lf in features
    ]

    # ── header ───────────────────────────────────────────────────
    _render_page_intro(
        _t("run_review"),
        _t("results_title"),
        _t("results_body"),
        guide=_open_guide,
    )

    run_facts = [st.session_state.ref_record.id]
    if st.session_state.alias_config_path:
        run_facts.append(Path(st.session_state.alias_config_path).name)
    if st.session_state.use_ref_names:
        run_facts.append(_t("ref_names_caption"))
    with st.container(horizontal=True, horizontal_alignment="distribute", vertical_alignment="center"):
        st.caption(" · ".join(run_facts))
        st.button(_t("new_run"), icon=":material/restart_alt:", key="results_new_run", on_click=_reset)

    # ── run health ────────────────────────────────────────────────
    total_records = len(all_results)
    failed_records = len(run_errors)
    absent_features = summary.pop(NOT_IN_SEQUENCE, 0)
    in_sequence_features = len(rows) - absent_features
    partial_records = sum(
        1 for _, features in display_results if any(f.status == NOT_IN_SEQUENCE for f in features)
    )
    passing_features = sum(1 for _, lf, _ in rows if lf.status in GOOD_STATUSES)
    review_features = sum(1 for _, lf, _ in rows if lf.status in REVIEW_STATUSES)
    pass_rate = (passing_features / in_sequence_features * 100) if in_sequence_features else 0.0
    method_counts: Dict[str, int] = {}
    for _, lf, _ in rows:
        if lf.status != NOT_IN_SEQUENCE:
            method_counts[lf.method or "unknown"] = method_counts.get(lf.method or "unknown", 0) + 1

    _render_stats([
        {
            "label": _t("records_processed"),
            "value": f"{total_records - failed_records:,}",
            "note": _t("failed_delta", count=failed_records) if failed_records else _t("all_processed"),
            "tone": "danger" if failed_records else "plain",
        },
        {
            "label": _t("features_found"),
            "value": f"{in_sequence_features:,}",
            "note": (
                _t("not_in_sequence_note", count=f"{absent_features:,}") if absent_features
                else " · ".join(f"{method} {count:,}" for method, count in sorted(method_counts.items()))
            ),
        },
        {
            "label": _t("pass_rate"),
            "value": f"{pass_rate:.1f}%",
            "note": _t("passed_count", count=f"{passing_features:,}"),
            "tone": "primary",
        },
        {
            "label": _t("needs_review"),
            "value": f"{review_features:,}",
            "note": _t("review_note") if review_features else _t("nothing_to_review"),
            "tone": "warn" if review_features else "ok",
        },
    ])
    _render_status_bar(summary)
    _render_check_banner(rows)
    if partial_records:
        _render_callout(
            _t(
                "partial_records_banner",
                partial=f"{partial_records:,}",
                total=f"{total_records:,}",
                absent=f"{absent_features:,}",
            ),
            tone="info",
        )

    if run_errors:
        st.error(_t("processing_error", count=failed_records))
        with st.expander(_t("processing_errors"), expanded=True):
            st.dataframe(pd.DataFrame(run_errors), width="stretch", hide_index=True)

    # Stateful tabs: only the open tab's content runs.
    features_tab, records_tab, export_tab = st.tabs(
        [_t("view_features"), _t("view_records"), _t("view_export")],
        key="results_view",
        on_change="rerun",
    )
    if records_tab.open:
        with records_tab:
            _render_records_view(display_results, rows, error_map)
    elif export_tab.open:
        with export_tab:
            _render_export_view(rows, df, ref_name_map)
    else:
        with features_tab:
            _render_features_view(rows)
