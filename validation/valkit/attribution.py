"""
Evidence-based attribution of every non-exact prediction.

`adjudicate_failures` (report.py) decides from length deltas alone, which labels a
truth feature with IoU 0.001 as a "boundary convention". This module looks at the
things that can actually be checked and prints them next to the verdict:

    - the record's OTHER predictions (label swap, granularity): sequence-derived,
      independent of how the annotator named things;
    - the sequence itself: N runs in the part of the truth the lift did not cover,
      and whether the truth span and the prediction span are valid CDS;
    - the whole dataset: the same (gene, delta_start, delta_end) recurring in many
      records is a convention, a one-off is not.

Sides are deliberately not just "tool" vs "truth":

    tool         the lift is wrong and the sequence shows it
    annotation   the record's own annotation contradicts sequence-level evidence
    data         the sequence cannot support a correct lift (N run)
    convention   both sides are internally consistent and the offset recurs
    undecided    sequence evidence does not settle it; listed for a human

Every row keeps the numeric evidence, so a reader can disagree with the verdict.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Sequence, Tuple

import pandas as pd
from Bio.Seq import Seq
from Bio.SeqRecord import SeqRecord

from app.src.lifting.validator import validate_cds_boundaries
from validation.valkit.metrics import iou

SIDES = ("tool", "annotation", "data", "convention", "undecided")
MIN_N_RUN = 10            # N bases in the uncovered truth region to call a sequencing gap
MIN_RECURRENCE = 3        # records sharing the same (gene, delta_start, delta_end) to call a convention
GRANULARITY_FACTOR = 1.3  # truth longer than this x ref_len AND covering another gene's prediction


def _span_seq(record: SeqRecord, start, end, strand) -> Optional[str]:
    if start is None or end is None or pd.isna(start) or pd.isna(end):
        return None
    seq = record.seq[int(start) - 1:int(end)]
    if strand in ("-", -1):
        seq = seq.reverse_complement()
    return str(seq).upper()


def _cds_valid(record: SeqRecord, start, end, strand) -> Optional[bool]:
    seq = _span_seq(record, start, end, strand)
    return None if seq is None else bool(validate_cds_boundaries(seq)["valid"])


def _frame_ok(record: SeqRecord, start, end, strand) -> Optional[bool]:
    """
    Structural check that does not depend on the start codon: in frame, ends on a
    stop, no internal stop. A span can fail this only by being wrong; a span that
    passes it but lacks ATG may be a frameshift product or an alternative start,
    which is a convention question, not an error.
    """
    seq = _span_seq(record, start, end, strand)
    if seq is None:
        return None
    v = validate_cds_boundaries(seq)
    return bool(v["in_frame"] and v["has_stop_codon"] and not v["has_internal_stop"])


def _n_in_uncovered_truth(record: SeqRecord, ps, pe, ts, te) -> int:
    """N bases inside the truth span that the prediction does not cover."""
    if ts is None or te is None or pd.isna(ts) or pd.isna(te):
        return 0
    ts, te = int(ts), int(te)
    seq = str(record.seq).upper()
    if ps is None or pe is None or pd.isna(ps) or pd.isna(pe):
        return seq[ts - 1:te].count("N")
    ps, pe = int(ps), int(pe)
    n = 0
    if ts < ps:
        n += seq[ts - 1:min(ps - 1, te)].count("N")
    if te > pe:
        n += seq[max(pe, ts - 1):te].count("N")
    return n


def _inside_fraction(inner_start, inner_end, outer_start, outer_end) -> float:
    if None in (inner_start, inner_end, outer_start, outer_end):
        return 0.0
    overlap = max(0, min(inner_end, outer_end) - max(inner_start, outer_start) + 1)
    return overlap / (inner_end - inner_start + 1)


def attribute_cases(
    per_pred: pd.DataFrame,
    records: Dict[str, SeqRecord],
    feature_level: str,
    codon_required: Sequence[str],
) -> pd.DataFrame:
    """
    Attribute every scored, non-exact prediction (failed and coord-only).

    per_pred: the per_prediction table of one dataset (compare_predictions_to_truth
    output + ref_len columns + has_truth_gene). records: record_id -> SeqRecord.
    Returns the selected rows with evidence columns and a verdict (side, category,
    evidence) per row.
    """
    df = per_pred.copy()
    if "has_truth_gene" in df.columns:
        scored = df[df["has_truth_gene"].fillna(False)]
    else:
        scored = df[df["name_match"].fillna(False)]
    cases = scored[~scored["exact_match"].fillna(False).astype(bool)].copy()
    if cases.empty:
        return cases

    codon_required = set(codon_required or [])
    # offset recurrence across the dataset (distinct records per gene+offset)
    rec = (
        scored.dropna(subset=["delta_start", "delta_end"])
        .groupby(["ref_name", "delta_start", "delta_end"])["record_id"].nunique()
    )
    preds_by_record = {rid: g for rid, g in df.groupby("record_id")}

    out_rows = []
    for row in cases.itertuples(index=False):
        r = row._asdict()
        record = records.get(r["record_id"])
        ps, pe = r.get("pred_start"), r.get("pred_end")
        ts, te = r.get("truth_start"), r.get("truth_end")
        strand = r.get("strand") or "+"
        gene = r["ref_name"]
        lifted = not (ps is None or pd.isna(ps))
        bucket = "failed" if not bool(r.get("coord_correct")) else "coord_only"

        # --- evidence --------------------------------------------------------
        ev = {
            "bucket": bucket,
            "max_abs_offset": (max(abs(r["delta_start"]), abs(r["delta_end"]))
                               if lifted and not pd.isna(r.get("delta_start")) else None),
            "offset_recurrence": int(rec.get((gene, r["delta_start"], r["delta_end"]), 0))
                                 if lifted and not pd.isna(r.get("delta_start")) else 0,
            "pred_len_eq_ref": bool(lifted and r.get("pred_minus_ref_len") == 0),
            "truth_len_eq_ref": bool(r.get("truth_minus_ref_len") == 0),
            "n_in_uncovered_truth": _n_in_uncovered_truth(record, ps, pe, ts, te) if record is not None else None,
            "truth_cds_valid": None, "pred_cds_valid": None,
            "truth_frame_ok": None, "pred_frame_ok": None,
            "truth_matches_other_pred": None, "truth_matches_other_iou": None,
            "truth_covers_other_preds": None,
        }
        if feature_level == "CDS" and record is not None and gene in codon_required:
            ev["truth_cds_valid"] = _cds_valid(record, ts, te, strand)
            ev["pred_cds_valid"] = _cds_valid(record, ps, pe, strand) if lifted else None
            ev["truth_frame_ok"] = _frame_ok(record, ts, te, strand)
            ev["pred_frame_ok"] = _frame_ok(record, ps, pe, strand) if lifted else None

        others = preds_by_record.get(r["record_id"])
        if others is not None and ts is not None and not pd.isna(ts):
            best_name, best_iou, covered = None, 0.0, []
            for o in others.itertuples(index=False):
                if o.ref_name == gene or o.pred_start is None or pd.isna(o.pred_start):
                    continue
                score = iou(int(ts), int(te), int(o.pred_start), int(o.pred_end))
                if score > best_iou:
                    best_name, best_iou = o.ref_name, score
                if _inside_fraction(int(o.pred_start), int(o.pred_end), int(ts), int(te)) >= 0.9:
                    covered.append(o.ref_name)
            ev["truth_matches_other_pred"] = best_name
            ev["truth_matches_other_iou"] = round(best_iou, 3)
            ev["truth_covers_other_preds"] = ",".join(covered) if covered else None

        # --- verdict (first rule that fires) ----------------------------------
        own_iou = float(r.get("iou") or 0.0)
        other_iou = ev["truth_matches_other_iou"] or 0.0
        ref_len = r.get("ref_len") or 0
        if not lifted:
            side, cat, why = "tool", "no_hit", "no usable tblastn hit; truth feature exists"
        elif own_iou < 0.5 and other_iou >= 0.9:
            side, cat = "annotation", "label_swap"
            why = (f"truth span coincides with this record's {ev['truth_matches_other_pred']} prediction "
                   f"(IoU {other_iou}) and not with {gene} (IoU {own_iou:.3f}): the gene is mislabelled")
        elif ev["truth_covers_other_preds"] and (r.get("truth_len") or 0) > GRANULARITY_FACTOR * ref_len:
            side, cat = "annotation", "granularity"
            why = (f"truth span ({int(ts)}-{int(te)}, {int(r['truth_len'])} nt vs reference {int(ref_len)} nt) also covers "
                   f"this record's prediction(s) for {ev['truth_covers_other_preds']}: a merged feature labelled {gene}")
        elif ev["truth_frame_ok"] is False and ev["pred_frame_ok"]:
            side, cat = "annotation", "truth_not_valid_cds"
            why = (f"the annotated span {int(ts)}-{int(te)} is out of frame, lacks a stop or has an internal stop on "
                   f"this sequence; the prediction is a clean reading frame")
        elif (ev["n_in_uncovered_truth"] or 0) >= MIN_N_RUN:
            side, cat = "data", "sequencing_gap"
            why = f"{ev['n_in_uncovered_truth']} N bases in the part of the truth the lift did not cover"
        elif ev["pred_cds_valid"] is False:
            side, cat = "tool", "pred_not_valid_cds"
            why = (f"prediction {int(ps)}-{int(pe)} is not a valid CDS "
                   f"(frame/stop ok: {ev['pred_frame_ok']}; annotated span valid: {ev['truth_cds_valid']})")
        elif ev["pred_len_eq_ref"] and ev["offset_recurrence"] >= MIN_RECURRENCE:
            side, cat = "convention", "convention_offset"
            why = (f"lift reproduces the reference boundary exactly; the same offset "
                   f"(start {r['delta_start']:+.0f}, end {r['delta_end']:+.0f}) recurs in {ev['offset_recurrence']} records")
        elif ev["offset_recurrence"] >= MIN_RECURRENCE:
            side, cat = "undecided", "recurring_offset"
            why = (f"the same offset (start {r['delta_start']:+.0f}, end {r['delta_end']:+.0f}) recurs in "
                   f"{ev['offset_recurrence']} records but the prediction is not reference-length "
                   f"(pred-ref {r['pred_minus_ref_len']:+.0f} nt): convention likely, not proven")
        elif ev["truth_frame_ok"] and ev["truth_cds_valid"] is False and r["delta_end"] == 0:
            side, cat = "undecided", "start_convention"
            why = (f"annotation starts {-r['delta_start']:+.0f} nt from the lift on a non-ATG codon "
                   f"(frameshift product or alternative start); frame and stop agree; sequence cannot decide")
        elif ev["truth_cds_valid"] and ev["pred_cds_valid"] and r["delta_end"] == 0 and r["delta_start"] != 0:
            side, cat = "undecided", "alternative_start"
            why = (f"both spans are valid CDS sharing the stop; the lift starts {r['delta_start']:+.0f} nt from the "
                   f"annotation; sequence alone cannot say which start is used")
        elif ev["pred_len_eq_ref"]:
            side, cat = "undecided", "reference_vs_record_boundary"
            why = (f"lift reproduces the reference boundary exactly; this record's annotation differs "
                   f"(start {r['delta_start']:+.0f}, end {r['delta_end']:+.0f}) and the offset does not recur")
        elif (r.get("coverage") or 1.0) < 0.9:
            side, cat = "tool", "truncated_divergent"
            why = f"HSP coverage {r['coverage']:.2f} with no N run: the alignment ended early on divergent sequence"
        else:
            side, cat, why = "undecided", "review", "no rule fired; inspect the evidence columns"

        out_rows.append({**r, **ev, "side": side, "category": cat, "evidence": why})

    out = pd.DataFrame(out_rows)
    return out


def offset_tiers(per_pred: pd.DataFrame) -> Dict[str, int]:
    """How far the scored predictions sit from the annotation, by tier (the strict view)."""
    scored = per_pred[per_pred["has_truth_gene"].fillna(False)] if "has_truth_gene" in per_pred else per_pred
    tiers = {"exact": 0, "1-3_bp": 0, "4-6_bp": 0, "7-30_bp": 0, "over_30_bp": 0, "not_lifted": 0}
    for row in scored.itertuples(index=False):
        if row.pred_start is None or pd.isna(row.pred_start):
            tiers["not_lifted"] += 1
            continue
        d = max(abs(row.delta_start), abs(row.delta_end)) if not pd.isna(row.delta_start) else None
        if d is None:
            tiers["not_lifted"] += 1
        elif d == 0:
            tiers["exact"] += 1
        elif d <= 3:
            tiers["1-3_bp"] += 1
        elif d <= 6:
            tiers["4-6_bp"] += 1
        elif d <= 30:
            tiers["7-30_bp"] += 1
        else:
            tiers["over_30_bp"] += 1
    return tiers


def accuracy_by_identity(per_pred: pd.DataFrame) -> List[Dict]:
    """Accuracy of scored predictions binned by the record's mean protein identity to the reference."""
    scored = per_pred[per_pred["has_truth_gene"].fillna(False)].copy() if "has_truth_gene" in per_pred else per_pred.copy()
    if scored.empty:
        return []
    rec_identity = per_pred.groupby("record_id")["identity"].mean()
    scored["record_identity"] = scored["record_id"].map(rec_identity)
    bins = [(0, 85, "<85"), (85, 95, "85-95"), (95, 101, ">=95")]
    out = []
    for lo, hi, label in bins:
        part = scored[(scored["record_identity"] >= lo) & (scored["record_identity"] < hi)]
        if part.empty:
            continue
        out.append({
            "identity_bin": label,
            "records": int(part["record_id"].nunique()),
            "pairs": int(len(part)),
            "exact": int(part["exact_match"].fillna(False).sum()),
            "coord_correct": int(part["coord_correct"].fillna(False).sum()),
            "accuracy_pct": round(part["coord_correct"].fillna(False).mean() * 100, 2),
        })
    return out


def check_unscored_predictions(per_pred: pd.DataFrame, all_truth_by_record: Dict[str, List[Dict]]) -> pd.DataFrame:
    """
    Predictions without a same-name truth are outside the denominator. Check them
    against the record's full annotation (every name, every feature of the level):

        consistent_with_merged   a truth feature of another name contains the prediction and
                                 shares its start or its end (e.g. ORF1a inside an ORF1ab)
        matches_other_name       IoU >= 0.9 with a truth feature of another name (the
                                 record names this gene differently)
        nested_in_annotated      the prediction lies inside an annotated gene of another name
                                 (an overlapping ORF the record does not annotate separately)
        partial_overlap          some overlap, nothing conclusive
        no_overlap               nothing annotated there
    """
    if "has_truth_gene" not in per_pred.columns:
        return pd.DataFrame()
    unscored = per_pred[~per_pred["has_truth_gene"].fillna(False)].copy()
    rows = []
    for r in unscored.itertuples(index=False):
        truths = all_truth_by_record.get(r.record_id, [])
        verdict, partner, score = "no_overlap", None, 0.0
        if r.pred_start is not None and not pd.isna(r.pred_start):
            ps, pe = int(r.pred_start), int(r.pred_end)
            nested = None
            for t in truths:
                s = iou(ps, pe, t["start"], t["end"])
                if s > score:
                    partner, score = t["name"], s
                if t["start"] <= ps and t["end"] >= pe and (t["start"] == ps or t["end"] == pe):
                    verdict, partner, score = "consistent_with_merged", t["name"], s
                    break
                if t["start"] <= ps and t["end"] >= pe:
                    nested = t["name"]
            else:
                if score >= 0.9:
                    verdict = "matches_other_name"
                elif nested:
                    # e.g. ORF2b lying inside an annotated ORF2a in a record that does not annotate ORF2b
                    verdict, partner = "nested_in_annotated", nested
                elif score > 0:
                    verdict = "partial_overlap"
        else:
            verdict = "not_lifted"
        rows.append({"record_id": r.record_id, "ref_name": r.ref_name, "pred_start": r.pred_start,
                     "pred_end": r.pred_end, "status": r.status, "check": verdict,
                     "annotated_as": partner, "iou_with_annotated": round(score, 3)})
    return pd.DataFrame(rows)
