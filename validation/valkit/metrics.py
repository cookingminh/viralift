"""
Per-prediction scoring: IoU, coordinate-correct rule, failure mode (METHODOLOGY.md §3-4).

Functions here were moved verbatim from validation/_shared/validation_utils.py
(validation branch @ b9f5894). Any change to a scoring rule must come with a
test in validation/tests/ and a note in validation/METHODOLOGY.md.
"""
from __future__ import annotations

from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import pandas as pd


def iou(a_start: Optional[int], a_end: Optional[int], b_start: Optional[int], b_end: Optional[int]) -> float:
    if None in (a_start, a_end, b_start, b_end):
        return 0.0
    left = max(int(a_start), int(b_start))
    right = min(int(a_end), int(b_end))
    inter = max(0, right - left + 1)
    union = max(int(a_end), int(b_end)) - min(int(a_start), int(b_start)) + 1
    return inter / union if union else 0.0


def lifted_to_rows(record_id: str, lifted: Iterable, method: str) -> List[Dict]:
    rows = []
    for item in lifted:
        if hasattr(item, "to_dict"):
            data = item.to_dict()
        else:
            data = dict(item)
        rows.append({
            "record_id": record_id,
            "method": method,
            "ref_name": data.get("ref_name") or data.get("name"),
            "pred_name": data.get("name"),
            "source_name": data.get("source_name"),
            "pred_start": data.get("start") or data.get("query_start"),
            "pred_end": data.get("end") or data.get("query_end"),
            "strand": data.get("strand"),
            "status": data.get("status"),
            "coverage": data.get("coverage"),
            "identity": data.get("identity"),
            "score": data.get("score"),
            # biological validity the tool already computed — carried through so the
            # coord-correct metric can require a valid CDS, not just a good IoU.
            "has_start_codon": data.get("has_start_codon"),
            "has_stop_codon": data.get("has_stop_codon"),
            "in_frame": data.get("in_frame"),
            # diagnostics: where the raw HSP landed vs the final coords, and rescue actions
            "raw_start": data.get("raw_start"),
            "raw_end": data.get("raw_end"),
            "n_term_missing_aa": data.get("n_term_missing_aa"),
            "rescue_target": data.get("rescue_target"),
            "rescue_offset": data.get("rescue_offset"),
            "rescue_action": data.get("rescue_action"),
        })
    return rows


def best_overlap(pred_row: Dict, truth_features: Sequence[Dict]) -> Tuple[Optional[Dict], float]:
    best_feature, best_iou = None, 0.0
    for truth in truth_features:
        score = iou(pred_row.get("pred_start"), pred_row.get("pred_end"), truth["start"], truth["end"])
        if score > best_iou:
            best_feature, best_iou = truth, score
    return best_feature, best_iou


def compare_predictions_to_truth(
    predictions: Sequence[Dict],
    truth_features: Sequence[Dict],
    iou_threshold: float = 0.90,
    codon_required_names: Optional[set] = None,
    bp_tolerance: int = 6,
) -> pd.DataFrame:
    # codon_required_names: genes whose REFERENCE feature is itself a clean CDS
    # (valid start/stop/frame). Only these are held to the codon check. Genes whose
    # reference is partial / frameshift / overlapping (e.g. PRRSV ORF1b, which has no
    # independent ATG start) are exempt -- an "invalid codon" there is biology, not a
    # tool error. None => hold every codon-computable prediction to the check.
    truth_by_name: Dict[str, Dict] = {}
    for truth in truth_features:
        existing = truth_by_name.get(truth["name"])
        if existing is None or (truth["end"] - truth["start"]) > (existing["end"] - existing["start"]):
            truth_by_name[truth["name"]] = truth

    rows = []
    for pred in predictions:
        same_name_truth = truth_by_name.get(pred.get("pred_name"))
        overlap_truth, best_iou = best_overlap(pred, truth_features)
        truth = same_name_truth
        match_iou = (
            iou(pred.get("pred_start"), pred.get("pred_end"), truth["start"], truth["end"])
            if truth else 0.0
        )
        # Codon/frame validity: the lifter reports has_start_codon / has_stop_codon /
        # in_frame (None for non-CDS such as mat_peptide, where it does not apply).
        # A prediction is codon-valid unless one of these is explicitly False.
        codon_valid = not (
            pred.get("has_start_codon") is False
            or pred.get("has_stop_codon") is False
            or pred.get("in_frame") is False
        )
        # Only hold this gene to the codon check if its reference is a clean CDS.
        codon_required = codon_required_names is None or pred.get("pred_name") in codon_required_names
        codon_ok = codon_valid or not codon_required
        exact = (
            truth is not None
            and pred.get("pred_start") == truth["start"]
            and pred.get("pred_end") == truth["end"]
        )
        # Length / boundary diagnostics (for coord-only & failure inspection).
        ps, pe = pred.get("pred_start"), pred.get("pred_end")
        ts, te = (truth["start"], truth["end"]) if truth else (None, None)
        pred_len = (pe - ps + 1) if ps is not None and pe is not None else None
        truth_len = (te - ts + 1) if truth else None
        d_start = (ps - ts) if (truth and ps is not None) else None
        d_end = (pe - te) if (truth and pe is not None) else None

        # Absolute boundary tolerance. IoU is scale-dependent: the SAME few-bp
        # annotation-convention difference leaves a long feature at IoU~0.99 (coord-only)
        # but pushes a very short one below the cutoff (failed) -- e.g. a 2-codon
        # cleavage-boundary convention on an 18 aa peptide. A prediction whose BOTH
        # boundaries sit within `bp_tolerance` of truth is coordinate-correct regardless
        # of feature length. Generic: no gene or virus name, no truth used beyond the
        # comparison itself.
        within_bp_tol = (
            d_start is not None and d_end is not None
            and abs(d_start) <= bp_tolerance and abs(d_end) <= bp_tolerance
        )
        # Coordinate-correct = right region (IoU >= threshold OR within bp tolerance)
        # AND a valid CDS (start + stop + frame) WHERE the reference gene warrants it.
        coord_correct = truth is not None and (
            exact or ((match_iou >= iou_threshold or within_bp_tol) and codon_ok)
        )
        rows.append({
            **pred,
            "truth_name": truth["name"] if truth else None,
            "truth_start": truth["start"] if truth else None,
            "truth_end": truth["end"] if truth else None,
            "best_overlap_name": overlap_truth["name"] if overlap_truth else None,
            "best_iou": round(best_iou, 4),
            "iou": round(match_iou, 4),
            "name_match": truth is not None,
            "codon_valid": codon_valid,
            "codon_required": codon_required,
            "within_bp_tolerance": within_bp_tol,
            "coord_correct": coord_correct,
            "exact_match": exact,
            "pred_len": pred_len,
            "truth_len": truth_len,
            "pred_minus_truth_len": (pred_len - truth_len) if pred_len is not None and truth_len is not None else None,
            "delta_start": d_start,
            "delta_end": d_end,
            "failure_mode": classify_prediction(
                pred, truth, match_iou, overlap_truth, best_iou, iou_threshold, codon_ok, within_bp_tol
            ),
        })
    return pd.DataFrame(rows)


def classify_prediction(
    pred: Dict,
    truth: Optional[Dict],
    match_iou: float,
    overlap_truth: Optional[Dict],
    best_iou: float,
    iou_threshold: float,
    codon_ok: bool = True,
    within_bp_tol: bool = False,
) -> str:
    if pred.get("pred_start") is None or pred.get("pred_end") is None:
        return "Not lifted"
    # within_bp_tol: both boundaries within the absolute bp tolerance -> treated as the
    # right region even when IoU is low (short features, where IoU is over-sensitive).
    if truth and (match_iou >= iou_threshold or within_bp_tol):
        if pred.get("pred_start") == truth["start"] and pred.get("pred_end") == truth["end"]:
            return "Correct"
        # codon_ok already folds in the reference-driven exemption: it is False only when
        # this gene is codon-required AND the lifted CDS has a bad start/stop/frame. A
        # frameshift gene (e.g. ORF1b, exempt) is codon_ok=True -> "Boundary offset", not
        # "Invalid codon", even though it has no ATG start.
        if not codon_ok:
            # right region but broken CDS on a codon-required gene — not coord-correct
            return "Invalid codon"
        return "Boundary offset"
    if truth:
        return "Wrong coords"
    if overlap_truth and best_iou >= iou_threshold:
        return "Alias/name gap"
    if overlap_truth and best_iou > 0:
        return "Possible overlap"
    return "Not in truth"
