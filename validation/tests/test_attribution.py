"""Each attribution rule, on a hand-built sequence. BLAST-free."""
import pandas as pd
import pytest
from Bio.Seq import Seq
from Bio.SeqRecord import SeqRecord

from validation.valkit.attribution import attribute_cases, check_unscored_predictions, offset_tiers

# Genome: flank(20) + A: ATG + 30 codons + TAA (96 nt, 21..116) + 10 nt + B: ATG + 20 codons + TAG (66 nt, 127..192) + flank
A = "ATG" + "GCTGAACTGAAAGGTCGTACCGTT" * 3 + "CCGCAGGACTCC" + "TAA"
B = "ATG" + "CCGCAGGACTCCGGTCGTACC" * 2 + "GCTGAACTGAAAGGT" + "TAG"
LA, LB = len(A), len(B)          # 90 and 63 nt
assert LA % 3 == 0 and LB % 3 == 0
GENOME = "CCGTCCGTCCGTCCGTCCGT" + A + "CCGTCCGTCC" + B + "CCGTCCGTCCGTCCGTCCGT"
A_START, A_END = 21, 21 + len(A) - 1
B_START, B_END = A_END + 11, A_END + 10 + len(B)
REC = {"r1": SeqRecord(Seq(GENOME), id="r1")}


def row(record, gene, ps, pe, ts, te, ref_len, **kw):
    pred_len = (pe - ps + 1) if ps else None
    truth_len = te - ts + 1
    base = {"record_id": record, "ref_name": gene, "pred_name": gene, "pred_start": ps, "pred_end": pe,
            "strand": "+", "status": "ok_rescued" if ps else "no_hit", "coverage": 1.0, "identity": 95.0,
            "truth_start": ts, "truth_end": te, "has_truth_gene": True, "name_match": True,
            "exact_match": bool(ps) and ps == ts and pe == te,
            "coord_correct": kw.pop("coord_correct", bool(ps) and ps == ts and pe == te),
            "iou": kw.pop("iou", 1.0 if (ps == ts and pe == te) else 0.0),
            "delta_start": (ps - ts) if ps else None, "delta_end": (pe - te) if pe else None,
            "pred_len": pred_len, "truth_len": truth_len, "ref_len": ref_len,
            "pred_minus_ref_len": (pred_len - ref_len) if pred_len else None,
            "truth_minus_ref_len": truth_len - ref_len}
    base.update(kw)
    return base


def attribute(rows, codon_required=("A", "B")):
    return attribute_cases(pd.DataFrame(rows), REC, "CDS", codon_required).set_index("ref_name")


def test_label_swap_when_truth_is_another_genes_span():
    # record labels A's region as B: B's "truth" == A's prediction
    out = attribute([row("r1", "A", A_START, A_END, A_START, A_END, LA),
                     row("r1", "B", B_START, B_END, A_START, A_END, LB, iou=0.0, coord_correct=False)])
    assert out.loc["B", "category"] == "label_swap" and out.loc["B", "side"] == "annotation"
    assert out.loc["B", "truth_matches_other_pred"] == "A"


def test_granularity_when_truth_covers_two_predictions():
    out = attribute([row("r1", "A", A_START, A_END, A_START, B_END, LA, iou=0.55, coord_correct=False),
                     row("r1", "B", B_START, B_END, B_START, B_END, LB)])
    assert out.loc["A", "category"] == "granularity"
    assert "B" in out.loc["A", "truth_covers_other_preds"]


def test_truth_not_valid_cds_is_blamed_on_the_annotation():
    # annotated span starts 3 nt early (not an ATG), the prediction is the real CDS
    out = attribute([row("r1", "A", A_START, A_END, A_START - 3, A_END, LA, iou=0.97, coord_correct=True)])
    assert out.loc["A", "category"] == "truth_not_valid_cds"
    assert bool(out.loc["A", "truth_cds_valid"]) is False and bool(out.loc["A", "pred_cds_valid"]) is True


def test_sequencing_gap_when_uncovered_truth_is_ns():
    genome = GENOME[:A_START + 59] + "N" * 20 + GENOME[A_START + 79:]
    rec = {"r1": SeqRecord(Seq(genome), id="r1")}
    df = pd.DataFrame([row("r1", "A", A_START, A_START + 56, A_START, A_END, LA, iou=0.57, coord_correct=False, coverage=0.6)])
    out = attribute_cases(df, rec, "CDS", ["A"]).set_index("ref_name")
    assert out.loc["A", "category"] == "sequencing_gap" and out.loc["A", "side"] == "data"
    assert out.loc["A", "n_in_uncovered_truth"] == 20


def test_prediction_with_internal_stop_is_a_tool_error():
    # prediction starts 12 nt upstream: ATG? no -> starts in flank, not a valid CDS; truth valid
    out = attribute([row("r1", "A", A_START - 12, A_END, A_START, A_END, LA, iou=0.89, coord_correct=False)])
    assert out.loc["A", "side"] == "tool" and out.loc["A", "category"] == "pred_not_valid_cds"


def test_recurring_offset_with_reference_length_is_a_convention():
    rows = [row(f"r{i}", "A", A_START, A_END, A_START - 3, A_END, LA, iou=0.97, coord_correct=True) for i in range(1, 5)]
    recs = {f"r{i}": REC["r1"] for i in range(1, 5)}
    out = attribute_cases(pd.DataFrame(rows), recs, "mat_peptide", []).set_index("record_id")
    assert set(out["category"]) == {"convention_offset"} and out["offset_recurrence"].min() == 4


def test_alternative_start_is_left_undecided():
    # an upstream in-frame ATG also gives a valid CDS: put ATG 9 nt before A
    genome = GENOME[:A_START - 10] + "ATGGCTGAA" + GENOME[A_START - 1:]
    rec = {"r1": SeqRecord(Seq(genome), id="r1")}
    df = pd.DataFrame([row("r1", "A", A_START - 9, A_END, A_START, A_END, LA, iou=0.92, coord_correct=True)])
    out = attribute_cases(df, rec, "CDS", ["A"]).set_index("ref_name")
    assert out.loc["A", "category"] == "alternative_start" and out.loc["A", "side"] == "undecided"


def test_no_hit_is_tool():
    out = attribute([row("r1", "A", None, None, A_START, A_END, LA, coord_correct=False)])
    assert out.loc["A", "category"] == "no_hit"


def test_exact_rows_are_not_attributed():
    out = attribute([row("r1", "A", A_START, A_END, A_START, A_END, LA)])
    assert out.empty


def test_offset_tiers_and_unscored_check():
    df = pd.DataFrame([
        row("r1", "A", A_START, A_END, A_START, A_END, LA),
        row("r1", "B", B_START + 2, B_END, B_START, B_END, LB, iou=0.97, coord_correct=True),
        row("r2", "A", None, None, A_START, A_END, LA, coord_correct=False),
    ])
    assert offset_tiers(df) == {"exact": 1, "1-3_bp": 1, "4-6_bp": 0, "7-30_bp": 0, "over_30_bp": 0, "not_lifted": 1}
    unscored = pd.DataFrame([dict(row("r3", "A", A_START, A_END, 0, 0, LA), has_truth_gene=False)])
    merged = {"r3": [{"name": "AB", "start": A_START, "end": B_END}]}
    chk = check_unscored_predictions(unscored, merged)
    assert chk.loc[0, "check"] == "consistent_with_merged" and chk.loc[0, "annotated_as"] == "AB"
