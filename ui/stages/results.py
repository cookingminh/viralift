# Step 3 · Results — run health, a filterable feature table with a detail panel,
# a per-record view, and TSV / FASTA export.
#
# Partial query records (e.g. VP1-only sequences) are common in NCBI downloads.
# Genes that fall outside such a record are shown as "Not in sequence"
# (app/src/lifting/gene_presence.py) and kept out of the pass rate and review counts; the
# engine's own statuses, used by every export, are left untouched.
import dataclasses
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
    _kv_html,
    _render_callout,
    _render_page_intro,
    _render_section_title,
    _render_stats,
    _render_status_bar,
    _sequence_html,
    _status_badge,
    _status_cell,
    _status_column,
    _status_label,
    _status_tone,
)
from app.src.lifting.gene_presence import NOT_IN_SEQUENCE, missing_genes_outside_record, nothing_located
from ui import genome_map
from ui.fasta_names import FIELDS, MISSING, PRESETS, SEPARATORS, build_header, load_settings, make_unique, record_metadata, save_settings
from ui.guide import FEATURE_COLUMN_HELP, _open_guide
from ui.i18n import _t
from ui.services import _canonical_to_ref_map, _results_to_df
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
    # Bars make a weak gene stand out while scanning; the columns still sort numerically.
    "Of reference": st.column_config.ProgressColumn(
        "Of reference", format="%.0f%%", min_value=0, max_value=100, help=FEATURE_COLUMN_HELP["Of reference"],
    ),
    "Coverage": st.column_config.ProgressColumn(
        "Coverage", format="%.0f%%", min_value=0, max_value=100, help=FEATURE_COLUMN_HELP["Coverage"],
    ),
    "Identity": st.column_config.ProgressColumn(
        "Identity", format="%.1f%%", min_value=0, max_value=100, help=FEATURE_COLUMN_HELP["Identity"],
    ),
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


def _rescue_action(feature: LiftedFeature) -> str:
    if feature.rescue_action:
        return feature.rescue_action
    if feature.rescue_target and feature.rescue_offset is not None:
        return f"{feature.rescue_target} {feature.rescue_offset:+d} bp"
    if feature.rescue_offset is not None:
        return f"start {feature.rescue_offset:+d} bp"
    return ""


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


def _per_run(name: str, build, *extra):
    """build() once per run, annotation choice and `extra`, kept in session state.

    A click on the map reruns the whole page; with thousands of records the
    stats, record health and export tables would otherwise be rebuilt every
    time, which made each click feel slow. The run's results are compared by
    identity, so a new run never reuses another run's values."""
    results = st.session_state.all_results
    key = (st.session_state.get("annotation_choice_version", 0), extra)
    cached = st.session_state.get(name)
    if cached is not None and cached[0] is results and cached[1] == key:
        return cached[2]
    value = build()
    st.session_state[name] = (results, key, value)
    return value


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


def _as_percent(fraction: Optional[float]) -> Optional[float]:
    return None if fraction is None else fraction * 100


def _reference_share(feature: LiftedFeature) -> Optional[float]:
    """Placed length as a share of the reference gene's length (1.0 = same length)."""
    length = _feature_length(feature)
    if length is None or feature.ref_start is None or feature.ref_end is None:
        return None
    return length / (feature.ref_end - feature.ref_start + 1)


# Positions that can be missing are shown as text: st.dataframe prints a null
# integer as a literal "None", and unplaced genes have no coordinates. Text
# columns sort with localeCompare, where space-padding to a fixed width keeps
# numeric order and "" sorts first. The bar columns are floats, where a
# missing value is NaN and shows as an empty cell.
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
                "Of reference": _as_percent(_reference_share(lf)),
                # An unplaced gene has no alignment on this record.
                "Coverage": _as_percent(lf.coverage) if lf.query_start is not None else None,
                "Identity": lf.identity,
                "Raw name": lf.source_name or "",
            }
            for query_id, lf, gene in rows
        ],
        columns=list(FEATURE_COLUMNS),
    )
    for column in ("Of reference", "Coverage", "Identity"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
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


# ── gene detail ───────────────────────────────────────────────────────────
# The panel for the gene clicked on the Genome map, under the record map: where
# it sits on the record and on the reference (with a bar of its length against
# the reference gene), coverage and identity as bars against the run's cut-offs,
# the boundary checks, the annotation check with its tblastn switch, and the
# sequence. Fields that do not apply to the gene are left out, not shown as "—".

def _record_length(query_id: str) -> int:
    return next((len(r.seq) for r in st.session_state.query_records or [] if r.id == query_id), 0)


def _placement_html(lf: LiftedFeature) -> str:
    def row(label: str, coords: str, length: str) -> str:
        return (
            "<div class='vl-place-row'>"
            f"<span class='vl-place-label'>{html.escape(label)}</span>"
            f"<span class='vl-place-coords'>{coords}</span>"
            f"<span class='vl-place-len'>{html.escape(length)}</span></div>"
        )

    rows = []
    if lf.query_start is not None and lf.query_end is not None:
        strand = "−" if lf.strand == "-" else "+"
        rows.append(row(_t("detail_record"), f"{lf.query_start:,}–{lf.query_end:,} <span class='vl-faint'>({strand})</span>", f"{_feature_length(lf):,} nt"))
    else:
        rows.append(row(_t("detail_record"), html.escape(_t("detail_not_placed")), ""))
    if lf.ref_start is not None and lf.ref_end is not None:
        rows.append(row(_t("detail_reference"), f"{lf.ref_start:,}–{lf.ref_end:,}", f"{lf.ref_end - lf.ref_start + 1:,} nt"))
    else:
        rows.append(row(_t("detail_reference"), html.escape(_t("detail_no_reference")), ""))
    share = _reference_share(lf)
    bar = ""
    if share is not None:
        tone = "warn" if genome_map.is_much_shorter(lf) or share > 1.1 else "ok"
        bar = (
            f"<div class='vl-lenbar tone-{tone}'><span style='width:{min(share, 1) * 100:.1f}%'></span></div>"
            f"<div class='vl-lenbar-note'>{html.escape(_t('detail_share', share=f'{share:.0%}'))}</div>"
        )
    return "<div class='vl-place'>" + "".join(rows) + bar + "</div>"


def _meters_html(lf: LiftedFeature) -> str:
    """Coverage and identity as bars, with the run's cut-off marked on each."""
    if lf.query_start is None or lf.ref_start is None:
        return ""  # nothing placed, or no reference protein to align to
    if lf.method == "direct" and lf.annotation_check is None:
        text = _t("detail_not_aligned")
        if not st.session_state.get("check_annotations"):
            text += " " + _t("detail_turn_on_check")
        return f"<div class='vl-explain'>{html.escape(text)}</div>"

    def meter(label: str, value: float, cutoff: float) -> str:
        tone = "ok" if value >= cutoff else "warn"
        return (
            f"<div class='vl-meter tone-{tone}'>"
            f"<div class='vl-meter-head'><span>{html.escape(label)}</span><b>{value:.1f}%</b></div>"
            f"<div class='vl-meter-bar'><span style='width:{min(value, 100):.1f}%'></span>"
            f"<i style='left:{cutoff:.1f}%' title='{html.escape(_t('detail_cutoff', value=f'{cutoff:.0f}%'))}'></i></div></div>"
        )

    meters = [meter(_t("detail_coverage"), (lf.coverage or 0) * 100, st.session_state.min_coverage * 100)]
    if lf.identity is not None:
        meters.append(meter(_t("detail_identity"), lf.identity, st.session_state.min_identity * 100))
    return "<div class='vl-meters'>" + "".join(meters) + "</div>"


def _checks_html(lf: LiftedFeature) -> str:
    pills = [
        f"<span class='vl-badge tone-{'ok' if value else 'danger'}'>{label} {'✓' if value else '✗'}</span>"
        for label, value in (("start", lf.has_start_codon), ("stop", lf.has_stop_codon), ("frame", lf.in_frame))
        if value is not None
    ]
    facts = []
    if _rescue_action(lf):
        facts.append((_t("detail_rescue"), _rescue_action(lf)))
    if (
        lf.raw_start is not None and lf.raw_end is not None and lf.query_start is not None
        and max(abs(lf.raw_start - lf.query_start), abs(lf.raw_end - lf.query_end)) > genome_map.RAW_HIT_MIN_SHIFT
    ):
        facts.append((_t("detail_raw_hit"), f"{lf.raw_start:,}–{lf.raw_end:,}"))
    if lf.score is not None:
        facts.append((_t("detail_bit_score"), f"{lf.score:.1f}"))
    if not pills and not facts:
        return ""
    return (
        "<div class='vl-checks'>" + "".join(pills)
        + "".join(f"<span class='vl-fact-inline'>{html.escape(k)} <b>{html.escape(v)}</b></span>" for k, v in facts)
        + "</div>"
    )


def _short_note(lf: LiftedFeature, length: int) -> Optional[str]:
    """Why a passing gene is far shorter than its reference gene, when it is."""
    if not genome_map.is_much_shorter(lf):
        return None
    share = _format_fraction_percent(_reference_share(lf))
    if lf.query_start == 1 or lf.query_end == length:
        return _t("map_short_edge", share=share)
    text = _t("map_short", share=share)
    if lf.raw_end is not None and lf.raw_end - lf.query_end > genome_map.RAW_HIT_MIN_SHIFT:
        text += " " + _t("map_short_raw", raw_start=f"{lf.raw_start:,}", raw_end=f"{lf.raw_end:,}", end=f"{lf.query_end:,}")
    return text


def _render_feature_detail(query_id: str, lf: LiftedFeature, gene: str) -> None:
    approved = _export_key(query_id, lf, gene) in _approved_export_keys()
    head = (
        "<div class='vl-detail-head'>"
        f"<span class='vl-detail-title'>{html.escape(query_id)} · {html.escape(gene)}</span>"
        f"{_status_badge(lf.status)}"
        f"<span class='vl-chip'>{html.escape(_method_label(lf.method) or 'unknown')}</span>"
        + ("<span class='vl-chip is-primary'>approved for FASTA</span>" if approved else "")
        + "</div>"
    )
    if lf.source_name and lf.source_name != gene:
        head += f"<div class='vl-meta vl-detail-sub'>{html.escape(_t('detail_annotated_as', name=lf.source_name))}</div>"
    explain_key = {
        "invalid_boundaries": "invalid_boundary_help",
        NOT_IN_SEQUENCE: "not_in_sequence_help",
    }.get(lf.status)
    explain = f"<div class='vl-explain'>{html.escape(_t(explain_key))}</div>" if explain_key else ""
    with _card("feature_detail"):
        # Full width under the map: the facts on the left, the sequence beside
        # them (Streamlit stacks the two columns on a narrow screen).
        facts, sequence = st.columns([1, 1.15], gap="large") if lf.sequence else (st.container(), None)
        with facts:
            st.html(head + _placement_html(lf) + _meters_html(lf) + _checks_html(lf) + explain)
            note = _short_note(lf, _record_length(query_id))
            if note:
                _render_callout(html.escape(note), tone="warn", icon="!")
            _render_annotation_check(query_id, lf, gene)
        if sequence is not None:
            with sequence:
                st.html(_sequence_html(lf.sequence))


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


def _record_placement_of(query_id: str) -> Tuple[int, bool, int]:
    """(offset, flipped, length) lining this record up with the reference (genome_map.record_placement)."""
    features = next((fs for rid, fs in st.session_state.all_results or [] if rid == query_id), [])
    strands = {f["name"]: f.get("strand") or "+" for f in st.session_state.ref_features or []}
    length = _record_length(query_id)
    offset, flipped = genome_map.record_placement(features, strands, length)
    return offset, flipped, length


def _reference_on_record(lf: LiftedFeature, query_id: str) -> Optional[Tuple[int, int]]:
    """Where the reference gene falls on this record, by the record's offset to the reference."""
    if lf.ref_start is None or lf.ref_end is None:
        return None
    offset, flipped, length = _record_placement_of(query_id)
    start, end = lf.ref_start - offset, lf.ref_end - offset
    return (length - end + 1, length - start + 1) if flipped else (start, end)


def _compare_html(
    query_id: str, gene: str, annotated: LiftedFeature, tblastn: Optional[LiftedFeature], in_use: str,
) -> str:
    """The reference gene, the record's annotation and tblastn's placement as
    bars on one axis of the record, with the reference's ends marked on each."""
    reference = _reference_on_record(annotated, query_id)
    rows: List[Tuple[str, str, Tuple[int, int], str, bool]] = []  # label, kind, span, facts, in use
    ref_length = annotated.ref_end - annotated.ref_start + 1

    def facts(row: LiftedFeature) -> str:
        length = _feature_length(row)
        parts = [f"{row.query_start:,}–{row.query_end:,}", f"{length:,} nt", _t("check_share", share=f"{length / ref_length:.0%}")]
        if row.identity is not None:
            parts.append(_t("check_identity", identity=f"{row.identity:.1f}%"))
        return " · ".join(parts)

    if reference:
        ref_facts = f"{annotated.ref_start:,}–{annotated.ref_end:,} · {ref_length:,} nt"
        if reference != (annotated.ref_start, annotated.ref_end):
            ref_facts += " · " + _t("check_projected", start=f"{reference[0]:,}", end=f"{reference[1]:,}")
        rows.append((_t("check_row_reference"), "ref", reference, ref_facts, False))
    rows.append((_t("check_row_annotation"), "anno", (annotated.query_start, annotated.query_end), facts(annotated), in_use == "annotation"))
    if tblastn is not None:
        rows.append((_t("check_row_tblastn"), "blast", (tblastn.query_start, tblastn.query_end), facts(tblastn), in_use == "tblastn"))

    lo = min(span[0] for _, _, span, _, _ in rows)
    hi = max(span[1] for _, _, span, _, _ in rows)
    pad = max(15, (hi - lo) * 0.06)
    lo, hi = lo - pad, hi + pad

    def pos(value: float) -> float:
        return (value - lo) / (hi - lo) * 100

    guides = "".join(
        f"<i class='vl-cmp-guide' style='left:{pos(edge):.2f}%'></i>"
        for edge in ((reference[0], reference[1] + 1) if reference else ())
    )
    body = "".join(
        "<div class='vl-cmp-row'>"
        f"<span class='vl-cmp-label'>{html.escape(label)}"
        + (f"<span class='vl-cmp-use'>{html.escape(_t('check_in_use'))}</span>" if used else "")
        + "</span>"
        f"<div class='vl-cmp-track'>{guides}<span class='vl-cmp-bar is-{kind}' "
        f"style='left:{pos(span[0]):.2f}%;width:{max(0.8, pos(span[1] + 1) - pos(span[0])):.2f}%'></span></div>"
        f"<span class='vl-cmp-facts'>{html.escape(text)}</span></div>"
        for label, kind, span, text, used in rows
    )
    axis = (
        "<div class='vl-cmp-row'><span></span><div class='vl-cmp-axis'>"
        f"<span>{max(1, round(lo)):,}</span><span>{round(hi):,}</span></div></div>"
    )
    note = ""
    if tblastn is not None:
        starts = annotated.query_start - tblastn.query_start
        ends = annotated.query_end - tblastn.query_end
        parts = [
            _t(key, n=f"{abs(delta):,}", direction=_t("check_later" if delta > 0 else "check_earlier"))
            for key, delta in (("check_delta_start", starts), ("check_delta_end", ends)) if delta
        ]
        note = _t("check_delta", parts=_t("check_and").join(parts)) if parts else _t("check_delta_same", gene=gene)
        note = f"<div class='vl-cmp-note'>{html.escape(note)}</div>"
    return (
        "<div class='vl-cmp'>"
        f"<div class='vl-cmp-title'>{html.escape(_t('check_compare_title', gene=gene))}</div>"
        f"{body}{axis}{note}</div>"
    )


def _render_annotation_check(query_id: str, lf: LiftedFeature, gene: str) -> None:
    """Annotation vs tblastn for a gene taken from the record's annotation: the
    two placements drawn against the reference gene, and the switch between them."""
    annotated = lf.annotation if lf.annotation is not None else lf
    if annotated.method != "direct" or annotated.ref_start is None or lf.status == NOT_IN_SEQUENCE:
        return
    lines = []
    if annotated.annotation_check and annotated.best_match:
        lines.append(_t("check_best_match", gene=annotated.best_match, name=gene))

    run_row = _run_row(query_id, lf.name)
    action: Optional[Tuple[str, Optional[LiftedFeature]]] = None  # (label, row to use)
    check_button = False
    tblastn_row: Optional[LiftedFeature] = None
    in_use = "annotation"
    if lf.annotation is not None:
        tblastn_row, in_use = lf, "tblastn"
        back = None if run_row is not None and run_row.annotation is None else lf.annotation
        action = (_t("use_annotation"), back)
    elif run_row is not None and run_row.annotation is not None:
        tblastn_row = run_row
        action = (_t("use_tblastn"), None)
    elif query_id in st.session_state.manual_lifts:
        alternative = next((f for f in _manual_lift(query_id) if f.name == lf.name), None)
        if alternative is None or alternative.status not in PASS_STATUSES or alternative.query_start is None:
            lines.append(_t("check_tblastn_none", gene=gene, status=alternative.status if alternative else "no_hit"))
        else:
            tblastn_row = alternative
            if (alternative.query_start, alternative.query_end) == (lf.query_start, lf.query_end):
                lines.append(_t("check_tblastn_same", gene=gene, status=alternative.status))
            else:
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
        + _compare_html(query_id, gene, annotated, tblastn_row, in_use)
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


# ── genome map ────────────────────────────────────────────────────────────
# A record x gene matrix under the reference bar, then the selected record drawn
# under the reference with ribbons from each reference gene to where it landed
# (ui/genome_map.py). Clicks come back as component events; the handlers only
# set map_record / map_gene / map_focus, so every panel reads one state.

MAP_MATRIX_KEY = "vl_map_matrix"
MAP_TRACKS_KEY = "vl_map_tracks"
MAP_PICKER_KEY = "vl_map_picker"
MAP_ATTENTION_LIMIT = 8
MAP_CHECK_LIMIT = 8
HEALTH_META = {key: (label, RECORD_HEALTH_TONE[key]) for key, label in RECORD_HEALTH_LABELS.items()}
MAP_SORTS = ("order", "review", "identity", "coverage", "length")
# "Needs review first" puts the records to act on at the top.
HEALTH_ORDER = ("failed", "needs_review", "no_genes", "partial", "passed", "empty")


def _sorted_records(
    record_ids: List[str], sort: str, gene: Optional[str], features_of: Dict[str, List[LiftedFeature]], health: Dict[str, str],
) -> List[str]:
    """Matrix rows in the chosen order. Metric sorts put the lowest value first
    (that gene's when a gene column is open, else each record's lowest) and
    records without a value last; ties keep the run order."""
    if sort == "review":
        rank = {key: index for index, key in enumerate(HEALTH_ORDER)}
        return sorted(record_ids, key=lambda q: rank.get(health[q], len(rank)))
    if sort in genome_map.SORT_METRICS:
        values = {q: genome_map.record_metric(features_of[q], sort, gene) for q in record_ids}
        return sorted(record_ids, key=lambda q: (values[q] is None, values[q] or 0.0))
    return list(record_ids)


def _gene_labeler(ref_name_map: Optional[Dict[str, str]]):
    return (lambda name: ref_name_map.get(name, name)) if ref_name_map else None


def _map_reference(ref_name_map: Optional[Dict[str, str]]) -> Dict:
    ref = st.session_state.ref_record
    return genome_map.reference_payload(
        ref.id, len(ref.seq), st.session_state.ref_features, st.session_state.ref_feature_type,
        _gene_labeler(ref_name_map),
    )


def _map_feature(features: List[LiftedFeature], gene: Optional[str]) -> Optional[LiftedFeature]:
    """The row a gene name refers to on one record: its reference gene first."""
    if not gene:
        return None
    named = [f for f in features if f.name == gene]
    return next((f for f in named if f.ref_start is not None), named[0] if named else None)


def _on_matrix_select() -> None:
    value = genome_map.event_value(MAP_MATRIX_KEY, "select") or {}
    if value.get("record"):
        st.session_state.map_record = value["record"]
        if value.get("gene"):
            st.session_state.map_gene = value["gene"]


def _on_matrix_focus() -> None:
    gene = genome_map.event_value(MAP_MATRIX_KEY, "focus")
    st.session_state.map_focus = None if not gene or gene == st.session_state.get("map_focus") else gene


def _on_tracks_select() -> None:
    gene = genome_map.event_value(MAP_TRACKS_KEY, "select")
    st.session_state.map_gene = None if not gene or gene == st.session_state.get("map_gene") else gene


def _export_gene_names() -> List[str]:
    ref_name_map = _canonical_to_ref_map(st.session_state.ref_features) if st.session_state.use_ref_names else None
    return sorted({
        (ref_name_map.get(f.get("name"), f.get("name")) if ref_name_map else f.get("name"))
        for f in st.session_state.ref_features
        if f.get("name")
    })


def _on_pick() -> None:
    name = genome_map.event_value(MAP_PICKER_KEY, "pick")
    if not name:
        return
    if st.session_state.use_ref_names:
        name = _canonical_to_ref_map(st.session_state.ref_features).get(name, name)
    chosen = set(st.session_state.get("fasta_genes") or [])
    chosen ^= {name}
    st.session_state.fasta_genes = [gene for gene in _export_gene_names() if gene in chosen]


def _pick_all_genes() -> None:
    st.session_state.fasta_genes = _export_gene_names()


def _pick_no_genes() -> None:
    st.session_state.fasta_genes = []


def _open_on_map(record_id: str, gene: Optional[str] = None) -> None:
    st.session_state.map_record = record_id
    if gene:
        st.session_state.map_gene = gene


def _close_focus() -> None:
    st.session_state.map_focus = None


def _export_one_gene(label: str) -> None:
    st.session_state.fasta_genes = [label]
    st.session_state.results_view = _t("view_export")


def _step_record(record_ids: List[str], step: int) -> None:
    current = st.session_state.get("map_record")
    index = record_ids.index(current) if current in record_ids else -1
    st.session_state.map_record = record_ids[(index + step) % len(record_ids)]


def _jump_to_record() -> None:
    record_id = st.session_state.get("map_jump")
    if record_id:
        st.session_state.map_record = record_id
    st.session_state.map_jump = None


def _render_gene_focus(gene: str, display_results: Results, ref: Dict, label_of) -> None:
    label = label_of(gene) if label_of else gene
    ref_gene = next((g for g in ref["genes"] if g[0] == gene), None)
    placed = [(qid, f) for qid, features in display_results for f in [_map_feature(features, gene)] if f]
    tones = Counter("absent" if f.status == NOT_IN_SEQUENCE else _status_tone(f.status) for _, f in placed)
    lengths = sorted(
        f.query_end - f.query_start + 1 for _, f in placed
        if f.query_start is not None and f.query_end is not None and f.status in GOOD_STATUSES
    )
    exportable = sum(1 for _, f in placed if f.sequence and f.status in GOOD_STATUSES)
    to_check = [(qid, f) for qid, f in placed if f.status in REVIEW_STATUSES or genome_map.is_much_shorter(f)]

    facts = []
    if ref_gene:
        facts.append(_t("map_focus_ref", start=f"{ref_gene[1]:,}", end=f"{ref_gene[2]:,}", length=f"{ref_gene[2] - ref_gene[1] + 1:,}"))
    if lengths:
        facts.append(_t("map_focus_median", length=f"{lengths[len(lengths) // 2]:,}"))
    chips = "".join(
        f"<span class='vl-badge tone-{'neutral' if tone == 'absent' else tone}'>{html.escape(_t(f'map_tone_{tone}'))} · {tones[tone]:,}</span> "
        for tone in ("ok", "info", "warn", "danger", "neutral", "absent") if tones[tone]
    )
    st.html(
        "<div class='vl-detail-head'>"
        f"<span class='vl-detail-title'>{html.escape(label)}</span>"
        f"<span class='vl-meta'>{html.escape(' · '.join(facts))}</span></div>"
        f"<div>{chips}</div>"
    )
    with st.container(horizontal=True, gap="small"):
        st.button(
            _t("map_export_gene", gene=label, count=exportable), key="map_export_gene",
            icon=":material/download:", on_click=_export_one_gene, args=(label,), disabled=not exportable,
        )
        st.button(_t("map_close_focus"), key="map_close_focus", type="tertiary", on_click=_close_focus)
    if to_check:
        st.caption(_t("map_focus_check", count=len(to_check)))
        with st.container(horizontal=True, gap="small"):
            for qid, f in to_check[:MAP_CHECK_LIMIT]:
                reason = (
                    _t("map_share_of_ref", share=_format_fraction_percent(
                        (f.query_end - f.query_start + 1) / (f.ref_end - f.ref_start + 1)))
                    if f.status not in REVIEW_STATUSES else _status_label(f.status)
                )
                st.button(
                    f"{qid} · {reason}", key=f"map_check_{qid}", type="secondary",
                    on_click=_open_on_map, args=(qid, gene),
                )


def _render_record_summary(record_id: str, features: List[LiftedFeature], length: int, health: str, ref: Dict, error: Optional[str]) -> None:
    offset, flipped = genome_map.record_placement(features, genome_map.reference_strands(ref), length)
    statuses = Counter(f.status for f in features)
    with _card("map_summary"):
        st.html(
            "<div class='vl-detail-head'>"
            f"<span class='vl-detail-title'>{html.escape(record_id)}</span>"
            f"<span class='vl-badge tone-{RECORD_HEALTH_TONE[health]}'>{html.escape(RECORD_HEALTH_LABELS[health])}</span>"
            "</div>"
            + _kv_html([
                (_t("map_length"), f"{length:,} bp · reference {ref['length']:,} bp"),
                (_t("map_shift"), (f"{offset:+,} bp" if any(f.query_start is not None for f in features) else "—")
                    + (" · " + _t("map_reverse") if flipped else "")),
                (_t("map_method"), METHOD_TAG_LABELS[_method_tag(features)]),
            ])
            + "<div class='vl-chips'>" + "".join(
                f"<span class='vl-badge tone-{_status_tone(status)}'>{html.escape(_status_label(status))} · {count}</span>"
                for status, count in statuses.most_common()
            ) + "</div>"
        )
        if error:
            st.error(error)
        st.caption(_t("map_pick_gene"))


def _map_context(display_results: Results, error_map: Dict[str, str]) -> Dict:
    """What the map reads about every record, the same until the run or a choice changes."""
    health = {query_id: _record_health(query_id, features, error_map) for query_id, features in display_results}
    return {
        "records": {record.id: record for record in st.session_state.query_records or []},
        "features_of": dict(display_results),
        "record_ids": [query_id for query_id, _ in display_results],
        "health": health,
        "counts": Counter(health.values()),
        # Worth a look: records to review, or with a passing gene far shorter than its reference gene.
        "attention": [
            query_id for query_id, features in display_results
            if health[query_id] == "needs_review" or any(genome_map.is_much_shorter(f) for f in features)
        ],
    }


def _render_map_view(display_results: Results, error_map: Dict[str, str], ref_name_map: Optional[Dict[str, str]]) -> None:
    label_of = _gene_labeler(ref_name_map)
    ref = _map_reference(ref_name_map)
    context = _per_run("map_context", lambda: _map_context(display_results, error_map))
    records, features_of, record_ids = context["records"], context["features_of"], context["record_ids"]
    health, counts = context["health"], context["counts"]

    with _card("map_overview"):
        with st.container(horizontal=True, horizontal_alignment="distribute", vertical_alignment="center"):
            title_slot = st.empty()
        present = [h for h in RECORD_HEALTH_LABELS if counts[h]]
        with st.container(horizontal=True, vertical_alignment="center", gap="small"):
            show = st.segmented_control(
                _t("health_filter"),
                ["all"] + present,
                format_func=lambda h: (
                    f"{_t('filter_all')} · {len(record_ids):,}" if h == "all" else f"{RECORD_HEALTH_LABELS[h]} · {counts[h]:,}"
                ),
                default="all",
                required=True,
                key="map_health",
                label_visibility="collapsed",
            )
            sort = st.selectbox(
                _t("map_sort"),
                list(MAP_SORTS),
                format_func=lambda key: _t(f"map_sort_{key}"),
                key="map_sort",
                label_visibility="collapsed",
                width=250,
            )
            search = st.text_input(
                _t("search_record"),
                placeholder=_t("search_record"),
                icon=":material/search:",
                key="map_search",
                label_visibility="collapsed",
            ).strip().lower()
        focus = st.session_state.get("map_focus")
        if focus and not any(g[0] == focus for g in ref["genes"]):
            focus = None
        sort_gene = focus if sort in genome_map.SORT_METRICS else None
        # Building ~100k cells takes a moment, so the rows are kept until the run,
        # a choice, the filter, the search or the sort changes; a click only
        # changes the selection, which is added on top.
        def matrix():
            ordered = _sorted_records(
                [
                    query_id for query_id in record_ids
                    if (show == "all" or health[query_id] == show) and (not search or search in query_id.lower())
                ],
                sort, sort_gene, features_of, health,
            )
            return ordered, genome_map.matrix_payload(
                ref, [(query_id, features_of[query_id], health[query_id]) for query_id in ordered], HEALTH_META,
            )

        # Building ~100k cells takes a moment, so the rows are kept until the run,
        # a choice, the filter, the search or the sort changes; a click only
        # changes the selection, which is added on top.
        visible, payload = _per_run(
            "map_matrix_cache", matrix, show, search, sort, sort_gene, st.session_state.use_ref_names,
        )
        with title_slot:
            _render_section_title(
                _t("map_matrix_title"),
                _t("map_matrix_caption", shown=f"{len(visible):,}", total=f"{len(record_ids):,}"),
            )
        if st.session_state.get("map_record") not in features_of:
            st.session_state.map_record = (visible or record_ids or [None])[0]
        record_id = st.session_state.map_record
        if sort in genome_map.SORT_METRICS:
            metric = _t(f"map_metric_{sort}")
            st.caption(
                _t("map_sorted_gene", gene=label_of(sort_gene) if label_of else sort_gene, metric=metric)
                if sort_gene else _t("map_sorted_lowest", metric=metric)
            )
        genome_map.render(
            {**payload, "selected": record_id, "focus": focus},
            MAP_MATRIX_KEY,
            on_select_change=_on_matrix_select,
            on_focus_change=_on_matrix_focus,
        )
        st.caption(_t("map_matrix_legend"))
        if focus:
            _render_gene_focus(focus, display_results, ref, label_of)

    if record_id is None:
        return
    features = features_of[record_id]
    record = records.get(record_id)
    length = len(record.seq) if record is not None else 0
    lf = _map_feature(features, st.session_state.get("map_gene"))
    with _card("map_record"):
        with st.container(horizontal=True, horizontal_alignment="distribute", vertical_alignment="top"):
            st.html(
                f"<div class='vl-section-title vl-mono'>{html.escape(record_id)}</div>"
                f"<div class='vl-section-caption'>{html.escape(record.description if record is not None else '')}"
                f" · {length:,} bp · {html.escape(METHOD_TAG_LABELS[_method_tag(features)])} "
                f"<span class='vl-badge tone-{RECORD_HEALTH_TONE[health[record_id]]}'>"
                f"{html.escape(RECORD_HEALTH_LABELS[health[record_id]])}</span></div>"
            )
            steps = visible if record_id in visible else record_ids
            with st.container(horizontal=True, width="content", gap="small"):
                st.button(_t("map_prev"), icon=":material/chevron_left:", key="map_prev",
                          on_click=_step_record, args=(steps, -1), disabled=len(steps) < 2)
                st.button(_t("map_next"), icon=":material/chevron_right:", key="map_next",
                          on_click=_step_record, args=(steps, 1), disabled=len(steps) < 2)
        attention = [query_id for query_id in context["attention"] if query_id != record_id]
        if attention:
            st.pills(
                _t("map_attention", count=len(attention)),
                attention[:MAP_ATTENTION_LIMIT],
                key="map_jump",
                on_change=_jump_to_record,
            )
        # The detail opens under the map, so say how to get there.
        if lf is None:
            _render_callout(html.escape(_t("map_select_tip")), tone="info", icon="i")
        else:
            st.caption(f":material/arrow_downward: {_t('map_showing_gene', gene=label_of(lf.name) if label_of else lf.name)}")
        genome_map.render(
            genome_map.tracks_payload(
                ref, record_id, length, features, selected=st.session_state.get("map_gene"), label_of=label_of,
            ),
            MAP_TRACKS_KEY,
            on_select_change=_on_tracks_select,
        )
        st.caption(_t("map_tracks_legend"))

    if lf is None:
        _render_record_summary(record_id, features, length, health[record_id], ref, error_map.get(record_id))
    else:
        _render_feature_detail(record_id, lf, label_of(lf.name) if label_of else lf.name)


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
    all_results: Results,
    ref_name_map: Optional[Dict[str, str]],
) -> None:
    with _card("tsv"):
        _render_section_title(_t("tsv"), _t("download_table"))
        # Exports use the engine's statuses; the views use the display ones.
        tsv_canonical, tsv_raw = _per_run(
            "results_tsv", lambda: _tsv_tables(all_results, ref_name_map), st.session_state.use_ref_names,
        )
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

        # Genes are picked on the reference bar or its chips only. The choice is
        # plain session state (no widget owns it), so it survives switching tabs.
        current = st.session_state.get("fasta_genes")
        st.session_state.fasta_genes = (
            list(ref_gene_names) if current is None else [g for g in current if g in ref_gene_names]
        )
        selected_genes = list(st.session_state.fasta_genes)
        label_of = _gene_labeler(ref_name_map)
        ref = _map_reference(ref_name_map)
        chosen = set(selected_genes)
        exportable = Counter(lf.name for _, lf, _ in rows if lf.sequence and lf.status in GOOD_STATUSES)

        with st.container(horizontal=True, horizontal_alignment="distribute", vertical_alignment="center"):
            st.markdown(
                f"**{_t('genes_to_extract')}** · "
                + _t("genes_picked", count=len(selected_genes), total=len(ref_gene_names))
            )
            with st.container(horizontal=True, width="content", gap="small"):
                st.button(
                    _t("pick_all"), key="fasta_pick_all", icon=":material/select_all:",
                    on_click=_pick_all_genes, disabled=len(selected_genes) == len(ref_gene_names),
                )
                st.button(
                    _t("pick_none"), key="fasta_pick_none", icon=":material/deselect:",
                    on_click=_pick_no_genes, disabled=not selected_genes,
                )
        genome_map.render(
            genome_map.picker_payload(
                ref,
                [gene[0] for gene in ref["genes"] if (label_of(gene[0]) if label_of else gene[0]) in chosen],
                dict(exportable),
            ),
            MAP_PICKER_KEY,
            on_pick_change=_on_pick,
        )
        st.caption(_t("pick_hint") if selected_genes else _t("pick_hint_empty"))

        fasta_mode = st.segmented_control(
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


def _run_numbers(display_results: Results, ref_name_map: Optional[Dict[str, str]]) -> Dict:
    """The page header's numbers and the gene rows, the same until the run or a choice changes."""
    rows: List[FeatureRow] = [
        (query_id, lf, ref_name_map.get(lf.name, lf.name) if ref_name_map else lf.name)
        for query_id, features in display_results
        for lf in features
    ]
    summary = summarize_counts(display_results)
    absent = summary.pop(NOT_IN_SEQUENCE, 0)
    method_counts: Dict[str, int] = {}
    for _, lf, _ in rows:
        if lf.status != NOT_IN_SEQUENCE:
            method_counts[lf.method or "unknown"] = method_counts.get(lf.method or "unknown", 0) + 1
    checked = [lf for _, lf, _ in rows if lf.annotation_check]
    return {
        "rows": rows,
        "summary": summary,
        "absent": absent,
        "in_sequence": len(rows) - absent,
        "partial_records": sum(
            1 for _, features in display_results if any(f.status == NOT_IN_SEQUENCE for f in features)
        ),
        "passing": sum(1 for _, lf, _ in rows if lf.status in GOOD_STATUSES),
        "review": sum(1 for _, lf, _ in rows if lf.status in REVIEW_STATUSES),
        "method_counts": method_counts,
        "check_counts": Counter(lf.annotation_check for lf in checked),
        "checked": len(checked),
        "replaced": sum(1 for lf in checked if lf.annotation is not None),
    }


def _tsv_tables(all_results: Results, ref_name_map: Optional[Dict[str, str]]) -> Tuple[str, str]:
    """The two TSV downloads (display names, raw source names)."""
    df = _results_to_df(all_results, ref_name_map)
    canonical = df.drop(columns=["sequence"]).to_csv(sep="\t", index=False)
    has_source = df["source_name"].notna() & (df["source_name"] != "")
    df.loc[has_source, "name"] = df.loc[has_source, "source_name"]
    return canonical, df.drop(columns=["sequence"]).to_csv(sep="\t", index=False)


def _render_check_banner(numbers: Dict) -> None:
    if not numbers["checked"]:
        return
    counts, replaced = numbers["check_counts"], numbers["replaced"]
    issues = "".join(
        f" · {_t('annotation_check_issue', count=f'{counts[v]:,}', label=_t(f'check_{v}').lower())}"
        for v in ("partial", "fragment", "low_identity", "overlong") if counts[v]
    )
    _render_callout(
        _t(
            "annotation_check_banner",
            confirmed=f"{counts['confirmed']:,}",
            checked=f"{numbers['checked']:,}",
            issues=html.escape(issues),
            replaced=_t("annotation_check_replaced", count=f"{replaced:,}") if replaced else "",
        ),
        tone="info",
    )


def stage_results():
    all_results, display_results = _run_views(st.session_state.all_results)
    run_errors  = st.session_state.run_errors or []
    error_map   = _error_by_record(run_errors)

    # build ref name map if user wants ref names as output
    # {canonical_key: ref_raw_name}  e.g. {"Lpro": "Lab", "3Cpro": "3C", ...}
    ref_name_map: Optional[Dict[str, str]] = (
        _canonical_to_ref_map(st.session_state.ref_features)
        if st.session_state.use_ref_names else None
    )

    numbers = _per_run("results_numbers", lambda: _run_numbers(display_results, ref_name_map), st.session_state.use_ref_names)
    rows: List[FeatureRow] = numbers["rows"]

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
    summary = numbers["summary"]
    absent_features = numbers["absent"]
    in_sequence_features = numbers["in_sequence"]
    partial_records = numbers["partial_records"]
    passing_features = numbers["passing"]
    review_features = numbers["review"]
    pass_rate = (passing_features / in_sequence_features * 100) if in_sequence_features else 0.0
    method_counts = numbers["method_counts"]

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
    _render_check_banner(numbers)
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

    # Stateful tabs: only the open tab's content runs. The genome map opens first.
    map_tab, export_tab = st.tabs(
        [_t("view_map"), _t("view_export")],
        key="results_view",
        on_change="rerun",
    )
    if export_tab.open:
        with export_tab:
            _render_export_view(rows, all_results, ref_name_map)
    else:
        with map_tab:
            _render_map_view(display_results, error_map, ref_name_map)
