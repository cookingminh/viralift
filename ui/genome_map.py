# Genome map: the reference genes drawn as a bar, and each query record's genes
# placed against it. Used by Results (record x gene matrix, two-track record map,
# FASTA gene picker), Setup (reference preview) and Review names (where an
# unknown name sits on a record).
#
# This module shapes the data and mounts the component; the drawing lives in
# ui/genome_map.js and ui/genome_map.css, served inline through
# st.components.v2 (no build step, no extra dependency). Payloads are plain
# lists so a few hundred records stay small on the wire.
#
# Coordinates are 1-based inclusive, as everywhere else in ViraLift.
from pathlib import Path
from statistics import median
from typing import Callable, Dict, List, Optional, Sequence, Tuple

import streamlit as st

from app.src.lifting.base import PASS_STATUSES, LiftedFeature
from ui.components import _status_label, _status_tone


ASSET_DIR = Path(__file__).parent
COMPONENT_NAME = "viralift_genome_map"

# A passing gene shorter than this share of its reference gene is flagged on the
# map. Display only: statuses and exports are left as the engine set them.
SHORT_FRACTION = 0.8
# Matrix cells are sent as one character per gene: the index of the cell's
# status in the payload's status table, or "-" when the record has no row for
# that gene. The browser draws only the rows in view, so every record is sent.
CELL_CODES = "0123456789abcdefghijklmnopqrstuvwxyz"
NO_CELL = "-"
# What the matrix can be sorted by (results.py offers them).
SORT_METRICS = ("identity", "coverage", "length")
# A raw tblastn hit is drawn when rescue moved an end by more than this (bp).
RAW_HIT_MIN_SHIFT = 30

_assets: Dict[str, str] = {}

Labeler = Optional[Callable[[str], str]]


def _mount():
    """The component's mount command. Registering is cheap and an identical
    definition replaces itself silently, so it is registered on every use:
    that keeps it on the current runtime (each AppTest has its own)."""
    if not _assets:
        _assets["css"] = (ASSET_DIR / "genome_map.css").read_text(encoding="utf-8")
        _assets["js"] = (ASSET_DIR / "genome_map.js").read_text(encoding="utf-8")
    return st.components.v2.component(COMPONENT_NAME, css=_assets["css"], js=_assets["js"])


# ── shared pieces ────────────────────────────────────────────────────────

class StatusTable:
    """Statuses used in a payload, sent once as [key, label, tone] and referenced by index."""

    def __init__(self) -> None:
        self.rows: List[List[str]] = []
        self._index: Dict[str, int] = {}

    def __call__(self, status: str) -> int:
        if status not in self._index:
            self._index[status] = len(self.rows)
            self.rows.append([status, _status_label(status), _status_tone(status)])
        return self._index[status]


def _round(value: Optional[float], digits: int) -> Optional[float]:
    return None if value is None else round(float(value), digits)


def reference_genes(ref_features: Sequence[Dict], label_of: Labeler = None) -> List[List]:
    """[name, start, end, strand, label] per reference gene, in genome order."""
    genes = []
    for feature in sorted(ref_features, key=lambda f: (int(f["start"]), int(f["end"]))):
        name = str(feature.get("name") or feature.get("raw_name") or "?")
        genes.append([
            name,
            int(feature["start"]),
            int(feature["end"]),
            feature.get("strand") or "+",
            (label_of(name) if label_of else None) or name,
        ])
    return genes


def reference_payload(
    ref_id: str,
    ref_length: int,
    ref_features: Sequence[Dict],
    feature_type: Optional[str],
    label_of: Labeler = None,
) -> Dict:
    return {
        "id": ref_id,
        "length": int(ref_length),
        "ftype": feature_type or "CDS",
        "genes": reference_genes(ref_features, label_of),
    }


def _located(lf: LiftedFeature) -> bool:
    return lf.query_start is not None and lf.query_end is not None


def _on_reference(lf: LiftedFeature) -> bool:
    return lf.ref_start is not None and lf.ref_end is not None


def is_much_shorter(lf: LiftedFeature, fraction: float = SHORT_FRACTION) -> bool:
    """A passing gene placed on the record that is far shorter than its reference gene.

    Worked example: PRRSV LQ249403.1 ORF1a passes as ok_rescued at 3,159-6,965
    (3,807 nt) against a 7,512 nt reference gene, 51% of its length.
    """
    if not (_located(lf) and _on_reference(lf)) or lf.status not in PASS_STATUSES:
        return False
    query_length = lf.query_end - lf.query_start + 1
    ref_length = lf.ref_end - lf.ref_start + 1
    return query_length < fraction * ref_length


def record_placement(features: Sequence[LiftedFeature], ref_strands: Dict[str, str], length: int) -> Tuple[int, bool]:
    """(offset, flipped): how a record's coordinates line up with the reference.

    flipped: most of the located sequence lies on the opposite strand from its
    reference gene, so the record is the reverse complement of the reference
    and is drawn mirrored (display position = length - position + 1).
    offset: the median over passing genes of reference start - display start,
    so reference position = display position + offset for a collinear record.

    Worked example: a 1,000 bp record that is the reverse complement of the
    reference carries reference gene A (101-400, +) at 601-900 on the minus
    strand. Flipped, A starts at 1000 - 900 + 1 = 101 on display, so offset 0.
    """
    placed = [lf for lf in features if _located(lf) and _on_reference(lf) and lf.status in PASS_STATUSES]
    if not placed:
        return 0, False
    same = sum(lf.query_end - lf.query_start + 1 for lf in placed if lf.strand == ref_strands.get(lf.name, "+"))
    opposite = sum(lf.query_end - lf.query_start + 1 for lf in placed if lf.strand != ref_strands.get(lf.name, "+"))
    flipped = opposite > same
    starts = [(length - lf.query_end + 1) if flipped else lf.query_start for lf in placed]
    offset = median(lf.ref_start - start for lf, start in zip(placed, starts))
    return int(round(offset)), flipped


def reference_strands(ref: Dict) -> Dict[str, str]:
    """{gene name: strand} of a reference payload."""
    strands: Dict[str, str] = {}
    for name, _start, _end, strand, _label in ref["genes"]:
        strands.setdefault(name, strand)
    return strands


def _first_by_name(features: Sequence[LiftedFeature]) -> Dict[str, LiftedFeature]:
    """The row each reference gene is drawn from: the first with reference coordinates."""
    by_name: Dict[str, LiftedFeature] = {}
    for lf in features:
        if _on_reference(lf) and lf.name not in by_name:
            by_name[lf.name] = lf
    return by_name


# ── Results: record x gene matrix ────────────────────────────────────────

def matrix_rows(
    columns: Sequence[str],
    records: Sequence[Tuple[str, List[LiftedFeature], str]],
    statuses: "StatusTable",
    absent_status: str = "not_in_sequence",
) -> List[List]:
    """One compact row per (record_id, features, health key):
    [record id, health key, cell codes, extras, passed, in sequence, (short columns)].

    Cell codes hold one character per column (CELL_CODES index into the status
    table, NO_CELL when the record has no row for that gene). Extras are the
    record's genes without a reference counterpart, [name, status index]. The
    last item, only present when needed, lists the columns whose gene passed
    but is much shorter than the reference gene.
    """
    rows = []
    for record_id, features, health_key in records:
        by_name = _first_by_name(features)
        codes, short = [], []
        for index, name in enumerate(columns):
            lf = by_name.get(name)
            if lf is None:
                codes.append(NO_CELL)
                continue
            codes.append(CELL_CODES[statuses(lf.status)])
            if is_much_shorter(lf):
                short.append(index)
        extras = [[lf.name, statuses(lf.status)] for lf in features if not _on_reference(lf)]
        in_sequence = [lf for lf in by_name.values() if lf.status != absent_status]
        passed = sum(1 for lf in in_sequence if lf.status in PASS_STATUSES)
        row = [record_id, health_key, "".join(codes), extras, passed, len(in_sequence)]
        if short:
            row.append(short)
        rows.append(row)
    return rows


def matrix_payload(
    ref: Dict,
    records: Sequence[Tuple[str, List[LiftedFeature], str]],
    health: Dict[str, Tuple[str, str]],
    selected: Optional[str] = None,
    focus: Optional[str] = None,
    absent_status: str = "not_in_sequence",
) -> Dict:
    """Every record as one matrix row (see matrix_rows); the browser draws only
    the rows in view."""
    statuses = StatusTable()
    columns = list(dict.fromkeys(gene[0] for gene in ref["genes"]))
    rows = matrix_rows(columns, records, statuses, absent_status)
    return {
        "view": "matrix",
        "ref": ref,
        "columns": columns,
        "rows": rows,
        "statuses": statuses.rows,
        "health": {key: list(value) for key, value in health.items()},
        "selected": selected,
        "focus": focus,
        "absent": absent_status,
    }


def gene_metric(lf: LiftedFeature, metric: str) -> Optional[float]:
    """A placed gene's identity (%), coverage or length as a share of its
    reference gene; None when the gene is not placed or has no such value."""
    if not _located(lf):
        return None
    if metric == "identity":
        return lf.identity
    if metric == "coverage":
        return lf.coverage
    if metric == "length" and _on_reference(lf):
        return (lf.query_end - lf.query_start + 1) / (lf.ref_end - lf.ref_start + 1)
    return None


def record_metric(features: Sequence[LiftedFeature], metric: str, gene: Optional[str] = None) -> Optional[float]:
    """What a record sorts by: that gene's value when a gene is given, else the
    lowest value over the record's reference genes."""
    by_name = _first_by_name(features)
    picked = [by_name[gene]] if gene in by_name else ([] if gene else list(by_name.values()))
    values = [value for value in (gene_metric(lf, metric) for lf in picked) if value is not None]
    return min(values) if values else None


# ── Results: two-track record map ────────────────────────────────────────

def tracks_payload(
    ref: Dict,
    record_id: str,
    length: int,
    features: Sequence[LiftedFeature],
    selected: Optional[str] = None,
    align: str = "ref",
    label_of: Labeler = None,
) -> Dict:
    """The reference genes over one record's genes, joined by ribbons.

    Feature: [name, label, status index, method, ref start, ref end, query start,
    query end, strand, coverage, identity, raw start, raw end, rescue, much shorter].
    Raw start/end are kept only when rescue moved an end by more than
    RAW_HIT_MIN_SHIFT bp, so the map draws the tblastn hit beside the final CDS.
    """
    statuses = StatusTable()
    offset, flipped = record_placement(features, reference_strands(ref), length)
    rows = []
    for lf in features:
        raw_start = raw_end = None
        if (
            _located(lf) and lf.raw_start is not None and lf.raw_end is not None
            and max(abs(lf.raw_start - lf.query_start), abs(lf.raw_end - lf.query_end)) > RAW_HIT_MIN_SHIFT
        ):
            raw_start, raw_end = lf.raw_start, lf.raw_end
        rows.append([
            lf.name,
            (label_of(lf.name) if label_of else None) or lf.name,
            statuses(lf.status),
            lf.method,
            lf.ref_start,
            lf.ref_end,
            lf.query_start,
            lf.query_end,
            lf.strand or "+",
            _round(lf.coverage, 3) if _located(lf) else None,
            _round(lf.identity, 1),
            raw_start,
            raw_end,
            lf.rescue_action or None,
            1 if is_much_shorter(lf) else 0,
        ])
    return {
        "view": "tracks",
        "ref": ref,
        "record": {"id": record_id, "length": int(length), "offset": offset, "flipped": flipped, "features": rows},
        "statuses": statuses.rows,
        "selected": selected,
        "align": align,
    }


# ── Export: pick genes on the reference ──────────────────────────────────

def picker_payload(ref: Dict, selected: Sequence[str], counts: Dict[str, int]) -> Dict:
    return {"view": "picker", "ref": ref, "selected": list(selected), "counts": counts}


# ── Review names: where a name sits on a record ──────────────────────────

def evidence_payload(
    record_id: str,
    length: int,
    lifted: Sequence[LiftedFeature],
    start: int,
    end: int,
    label: str,
    highlight: Sequence[str] = (),
) -> Dict:
    """The reference genes as lifted onto one record, with the annotated span under them."""
    genes = [
        [lf.name, lf.query_start, lf.query_end, lf.strand or "+"]
        for lf in lifted if _located(lf)
    ]
    return {
        "view": "evidence",
        "record": {"id": record_id, "length": int(length)},
        "genes": genes,
        "span": [int(start), int(end), label],
        "highlight": list(highlight),
    }


# ── mounting ─────────────────────────────────────────────────────────────

def event_value(key: str, event: str):
    """The value an on_<event>_change callback was fired with."""
    value = st.session_state.get(key)
    return value.get(event) if isinstance(value, dict) else getattr(value, event, None)


def render(payload: Dict, key: str, **callbacks):
    """Mount the map; callbacks follow the component's on_<event>_change pattern
    (on_select_change, on_focus_change, on_pick_change)."""
    return _mount()(data=payload, key=key, **callbacks)
