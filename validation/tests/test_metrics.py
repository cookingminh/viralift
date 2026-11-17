"""
Scoring rules of METHODOLOGY.md, pinned. BLAST-free.

Coordinates are 1-based inclusive throughout.
"""
import pandas as pd
import pytest

from validation.valkit.metrics import classify_prediction, compare_predictions_to_truth, iou
from validation.valkit.report import summarize_overall, summarize_per_gene
from validation.valkit.truth import dedupe_truth_by_name, filter_subfeatures, parse_truth_features


def pred(name, start, end, **kw):
    row = {"record_id": "r1", "method": "tblastn", "ref_name": name, "pred_name": name,
           "pred_start": start, "pred_end": end, "status": "ok_rescued",
           "has_start_codon": True, "has_stop_codon": True, "in_frame": True, "coverage": 1.0}
    row.update(kw)
    return row


def truth(name, start, end):
    return {"name": name, "start": start, "end": end, "strand": "+"}


# ------------------------------------------------------------------------ IoU

def test_iou_is_inclusive_and_symmetric():
    assert iou(1, 100, 1, 100) == 1.0
    assert iou(1, 100, 51, 150) == pytest.approx(50 / 150)
    assert iou(1, 100, 101, 200) == 0.0
    assert iou(1, 10, 10, 20) == pytest.approx(1 / 20)        # one shared base
    assert iou(None, 10, 1, 10) == 0.0


# --------------------------------------------------------- coordinate-correct

def test_exact_match_is_correct_even_if_codon_check_fails():
    df = compare_predictions_to_truth([pred("G", 1, 300, has_stop_codon=False)], [truth("G", 1, 300)])
    assert bool(df.loc[0, "exact_match"]) and bool(df.loc[0, "coord_correct"])
    assert df.loc[0, "failure_mode"] == "Correct"


def test_iou_rule_long_gene():
    # 3000-nt gene, boundaries off by 30 nt each side: IoU = 2940/3060 = 0.96 -> coord_only
    df = compare_predictions_to_truth([pred("G", 31, 3000)], [truth("G", 1, 3030)])
    assert df.loc[0, "iou"] == pytest.approx(2970 / 3030, abs=1e-4)
    assert bool(df.loc[0, "coord_correct"]) and not bool(df.loc[0, "exact_match"])
    assert df.loc[0, "failure_mode"] == "Boundary offset"


def test_bp_tolerance_rescues_short_feature_where_iou_fails():
    # 54-nt peptide, both boundaries 6 nt off: IoU = 42/66 = 0.64 but within +-6 bp -> correct
    df = compare_predictions_to_truth([pred("2A", 7, 60)], [truth("2A", 1, 54)])
    assert df.loc[0, "iou"] < 0.90
    assert bool(df.loc[0, "within_bp_tolerance"]) and bool(df.loc[0, "coord_correct"])
    # 7 nt off on one side is outside the tolerance -> failed
    df = compare_predictions_to_truth([pred("2A", 8, 60)], [truth("2A", 1, 54)])
    assert not bool(df.loc[0, "coord_correct"]) and df.loc[0, "failure_mode"] == "Wrong coords"


def test_codon_check_applies_only_to_codon_required_genes():
    rows = [pred("ORF5", 10, 609, has_stop_codon=False), pred("ORF1b", 10, 609, has_start_codon=False)]
    tr = [truth("ORF5", 1, 603), truth("ORF1b", 1, 603)]          # IoU 0.98 for both
    df = compare_predictions_to_truth(rows, tr, codon_required_names={"ORF5"})
    by = df.set_index("pred_name")
    assert not bool(by.loc["ORF5", "coord_correct"]) and by.loc["ORF5", "failure_mode"] == "Invalid codon"
    assert bool(by.loc["ORF1b", "coord_correct"]) and by.loc["ORF1b", "failure_mode"] == "Boundary offset"


def test_codon_required_none_means_every_gene_is_checked():
    df = compare_predictions_to_truth([pred("G", 10, 609, in_frame=False)], [truth("G", 1, 603)])
    assert not bool(df.loc[0, "coord_correct"])


def test_mat_peptide_rows_have_no_codon_flags_and_pass_on_iou():
    df = compare_predictions_to_truth(
        [pred("VP1", 10, 609, has_start_codon=None, has_stop_codon=None, in_frame=None)], [truth("VP1", 1, 603)])
    assert bool(df.loc[0, "codon_valid"]) and bool(df.loc[0, "coord_correct"])


def test_no_hit_and_name_gap_modes():
    rows = [pred("ORF7", None, None, status="no_hit"), pred("ORF1a", 1, 7000)]
    tr = [truth("ORF7", 1, 372), truth("ORF1ab", 1, 12000)]
    df = compare_predictions_to_truth(rows, tr).set_index("pred_name")
    assert df.loc["ORF7", "failure_mode"] == "Not lifted"
    assert df.loc["ORF1a", "failure_mode"] in ("Possible overlap", "Alias/name gap")
    assert not bool(df.loc["ORF1a", "name_match"])            # excluded from the denominator


def test_truth_with_duplicate_names_keeps_the_longest():
    tr = [truth("ORF1b", 7000, 12000), truth("ORF1b", 11000, 12000)]
    assert dedupe_truth_by_name(tr) == [truth("ORF1b", 7000, 12000)]
    df = compare_predictions_to_truth([pred("ORF1b", 7000, 12000)], tr)
    assert bool(df.loc[0, "exact_match"])


def test_filter_subfeatures_drops_nested_shorter_features():
    feats = [truth("poly", 1, 1000), truth("sub", 100, 200), truth("other", 1001, 1500)]
    main, subs = filter_subfeatures(feats)
    assert [f["name"] for f in main] == ["poly", "other"] and [f["name"] for f in subs] == ["sub"]


# ---------------------------------------------------------------- roll-ups

def test_per_gene_buckets_are_exclusive_and_truth_anchored():
    ref_model = pd.DataFrame([{"ref_name": "A", "ref_start": 1, "ref_end": 300, "ref_len": 300, "strand": "+"},
                              {"ref_name": "B", "ref_start": 400, "ref_end": 700, "ref_len": 300, "strand": "+"}])
    presence = pd.DataFrame([
        {"record_id": "r1", "gene": "A", "has_truth_gene": True}, {"record_id": "r1", "gene": "B", "has_truth_gene": True},
        {"record_id": "r2", "gene": "A", "has_truth_gene": True}, {"record_id": "r2", "gene": "B", "has_truth_gene": False},
    ])
    per_pred = pd.DataFrame([
        {"record_id": "r1", "ref_name": "A", "exact_match": True, "coord_correct": True, "status": "ok"},
        {"record_id": "r1", "ref_name": "B", "exact_match": False, "coord_correct": True, "status": "ok_rescued"},
        {"record_id": "r2", "ref_name": "A", "exact_match": False, "coord_correct": False, "status": "no_hit"},
        {"record_id": "r2", "ref_name": "B", "exact_match": False, "coord_correct": False, "status": "ok"},  # no truth -> extra
    ])
    per_gene = summarize_per_gene(per_pred, presence, ref_model, "v").set_index("gene")
    assert per_gene.loc["A", ["total", "exact", "coord_only", "failed", "no_hit"]].tolist() == [2, 1, 0, 1, 1]
    assert per_gene.loc["B", ["total", "exact", "coord_only", "failed"]].tolist() == [1, 0, 1, 0]
    assert per_gene.loc["B", "extra_predictions_without_truth"] == 1
    assert per_gene.loc["A", "accuracy_pct"] == 50.0 and per_gene.loc["B", "accuracy_pct"] == 100.0
    overall = summarize_overall(per_gene.reset_index())
    all_row = overall[overall["virus"] == "ALL"].iloc[0]
    assert (all_row["total"], all_row["exact"], all_row["coord_only"], all_row["failed"]) == (3, 1, 1, 1)
    assert all_row["accuracy_pct"] == pytest.approx(66.67)
