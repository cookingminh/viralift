"""
Roll-ups: per-gene buckets on the truth-anchored denominator, overall table, failure adjudication, alias coverage (METHODOLOGY.md §5).

Functions here were moved verbatim from validation/_shared/validation_utils.py
(validation branch @ b9f5894). Any change to a scoring rule must come with a
test in validation/tests/ and a note in validation/METHODOLOGY.md.
"""
from __future__ import annotations

from typing import Dict, Sequence

import pandas as pd
from Bio.SeqRecord import SeqRecord

from app.src.alias.gene_alias import EXCLUSION_SENTINELS, lookup_field_value
from app.src.io.genbank_parser import _LOOKUP_QUALIFIER_KEYS

from validation.valkit.truth import parse_features_for_type


def summarize_comparison(df: pd.DataFrame, group_cols: Sequence[str]) -> pd.DataFrame:
    return (
        df.groupby(list(group_cols), dropna=False)
        .agg(
            total=("pred_name", "size"),
            exact=("exact_match", "sum"),
            coord_correct=("coord_correct", "sum"),
            mean_iou=("iou", "mean"),
        )
        .reset_index()
        .assign(
            exact_pct=lambda d: (d["exact"] / d["total"] * 100).round(2),
            coord_pct=lambda d: (d["coord_correct"] / d["total"] * 100).round(2),
            mean_iou=lambda d: d["mean_iou"].round(4),
        )
    )


def summarize_evaluable(df: pd.DataFrame, group_cols: Sequence[str]) -> pd.DataFrame:
    """Accuracy over the EVALUABLE set only (the paper denominator).

    Keeps predictions whose gene name is present in the query truth
    (``name_match == True``) — i.e. genes in R ∩ query-truth. Predictions with no
    same-name truth (granularity / name-gap, e.g. an ORF1a lifted onto a record
    whose truth only has the merged ORF1ab) are dropped from the denominator and
    analysed separately by the failure-attribution notebook, instead of being
    counted as errors. Generic: no virus or gene name is referenced.
    """
    evaluable = df[df["name_match"].fillna(False)] if "name_match" in df.columns else df
    return summarize_comparison(evaluable, group_cols)


def attach_ref_lengths(pred_df: pd.DataFrame, ref_model: pd.DataFrame) -> pd.DataFrame:
    """Add ref_len + pred/truth-vs-ref length deltas by joining on ref_name."""
    if pred_df.empty:
        return pred_df
    ref_len = ref_model.set_index("ref_name")["ref_len"]
    out = pred_df.copy()
    out["ref_len"] = out["ref_name"].map(ref_len)
    out["pred_minus_ref_len"] = out["pred_len"] - out["ref_len"]
    out["truth_minus_ref_len"] = out["truth_len"] - out["ref_len"]
    return out


def summarize_per_gene(pred_df: pd.DataFrame, truth_presence: pd.DataFrame,
                       ref_model: pd.DataFrame, virus_name: str) -> pd.DataFrame:
    """Per-gene buckets on the truth-available denominator.

    total = records where the gene is in truth AND a prediction exists;
    exact / coord_only / failed are mutually exclusive; no_hit and
    extra_predictions_without_truth (gene predicted where truth lacks it) tracked separately.
    """
    rows = []
    for gene in ref_model["ref_name"].tolist():
        truth_records = set(
            truth_presence[(truth_presence["gene"] == gene) & truth_presence["has_truth_gene"]]["record_id"]
        )
        gene_rows = pred_df[(pred_df["ref_name"] == gene) & pred_df["record_id"].isin(truth_records)]
        total = len(gene_rows)
        exact = int(gene_rows["exact_match"].fillna(False).sum()) if total else 0
        coord_correct = int(gene_rows["coord_correct"].fillna(False).sum()) if total else 0
        coord_only = coord_correct - exact
        failed = total - coord_correct
        no_hit = int(gene_rows["status"].fillna("").eq("no_hit").sum()) if total and "status" in gene_rows else 0
        extra = int(len(pred_df[(pred_df["ref_name"] == gene) & ~pred_df["record_id"].isin(truth_records)]))
        rows.append({
            "virus": virus_name, "gene": gene, "total": total,
            "exact": exact, "coord_only": coord_only, "coord_correct": coord_correct,
            "failed": failed, "no_hit": no_hit, "extra_predictions_without_truth": extra,
            "exact_pct": round(exact / total * 100, 2) if total else None,
            "coord_only_pct": round(coord_only / total * 100, 2) if total else None,
            "failed_pct": round(failed / total * 100, 2) if total else None,
            "accuracy_pct": round((exact + coord_only) / total * 100, 2) if total else None,
        })
    return pd.DataFrame(rows)


def summarize_overall(per_gene_df: pd.DataFrame, group_col: str = "virus") -> pd.DataFrame:
    """Roll per-gene buckets up to per-virus + an ALL row."""
    def agg(df, label):
        total = int(df["total"].sum()); exact = int(df["exact"].sum())
        coord_only = int(df["coord_only"].sum()); coord_correct = int(df["coord_correct"].sum())
        failed = int(df["failed"].sum())
        return {
            group_col: label, "total": total, "exact": exact, "coord_only": coord_only,
            "coord_correct": coord_correct, "failed": failed,
            "no_hit": int(df["no_hit"].sum()) if "no_hit" in df else 0,
            "exact_pct": round(exact / total * 100, 2) if total else None,
            "coord_only_pct": round(coord_only / total * 100, 2) if total else None,
            "failed_pct": round(failed / total * 100, 2) if total else None,
            "accuracy_pct": round((exact + coord_only) / total * 100, 2) if total else None,
        }
    rows = [agg(df, label) for label, df in per_gene_df.groupby(group_col, sort=False)]
    rows.append(agg(per_gene_df, "ALL"))
    return pd.DataFrame(rows)


def adjudicate_failures(df: pd.DataFrame, short_peptide_bp: int = 150) -> pd.DataFrame:
    """First-pass, GENERIC adjudication of non-coord-correct cases.

    Splits each failure into blame = ref_truth / tool / review using only ref/pred/truth
    length deltas (no virus- or gene-specific rule). Rules (ported from the archived
    breakdown notebooks, de-hardcoded):

      - no hit / not lifted                          -> tool  (no_hit)
      - truth feature absent                         -> ref_truth (truth_feature_absent)
      - pred length == ref, truth differs            -> ref_truth (ref_query_boundary_convention)
            · if the reference gene is short (<= short_peptide_bp) the same convention gap
              is flagged short_peptide_iou_artifact (a few-bp offset drops IoU below cutoff)
      - truth length == ref, prediction differs      -> tool  (prediction_boundary_error)
      - pred shorter than BOTH ref & truth, low cov  -> tool  (truncation)
      - differs from both, otherwise                 -> review

    Needs columns: pred_len, truth_len, ref_len, pred_minus_ref_len, truth_minus_ref_len,
    pred_minus_truth_len, coverage, status, failure_mode. Returns df + blame/cause/explanation.
    """
    def _one(row):
        status = str(row.get("status") or "")
        mode = row.get("failure_mode")
        pr, tr, pt = row.get("pred_minus_ref_len"), row.get("truth_minus_ref_len"), row.get("pred_minus_truth_len")
        ref_len, cov = row.get("ref_len"), row.get("coverage")
        if status == "no_hit" or mode == "Not lifted":
            return ("tool", "no_hit", "Feature in truth but tblastn produced no usable hit.")
        if pd.isna(row.get("truth_len")):
            return ("ref_truth", "truth_feature_absent", "Query truth lacks the same-name feature.")
        if pd.notna(pr) and pd.notna(tr):
            if pr == 0 and tr != 0:
                if pd.notna(ref_len) and ref_len <= short_peptide_bp:
                    return ("ref_truth", "short_peptide_iou_artifact",
                            "Prediction follows the reference; query truth differs by a few bp, but the gene "
                            "is short so IoU drops below the cutoff and it registers as failed.")
                return ("ref_truth", "ref_query_boundary_convention",
                        "Prediction length follows the reference; query truth uses a different boundary.")
            if tr == 0 and pr != 0:
                return ("tool", "prediction_boundary_error",
                        "Truth length follows the reference; the prediction boundary differs -> tool-side.")
            if pr != 0 and tr != 0:
                if pd.notna(pt) and pt < 0 and (cov if pd.notna(cov) else 1) < 0.9:
                    return ("tool", "truncation",
                            "Prediction shorter than BOTH ref and truth with low coverage -> tool truncation.")
                return ("review", "differs_from_ref_and_truth",
                        "Prediction differs from both ref and truth; manual review.")
        return ("review", "unclassified", "Not enough length evidence; manual review.")

    if df.empty:
        return df.assign(blame=[], cause=[], explanation=[])
    df = df.reset_index(drop=True)   # align index before concat, else NaN/duplicate rows
    adj = df.apply(lambda r: pd.Series(_one(r), index=["blame", "cause", "explanation"]), axis=1)
    return pd.concat([df, adj], axis=1)


def collect_alias_rows(records: Sequence[SeqRecord], feature_types: Sequence[str] = ("CDS", "mat_peptide")) -> pd.DataFrame:
    rows = []
    for record in records:
        for feature_type in feature_types:
            for feature in parse_features_for_type(record, feature_type):
                for field in _LOOKUP_QUALIFIER_KEYS:
                    value = feature.get(field)
                    if value:
                        rows.append({
                            "record_id": record.id,
                            "feature_type": feature_type,
                            "field": field,
                            "raw_value": value,
                        })
    return pd.DataFrame(rows)


def evaluate_alias_rows(rows: pd.DataFrame, alias_lookup: Dict[str, str], virus_label: str) -> pd.DataFrame:
    if rows.empty:
        return rows

    def resolve(value: str) -> str:
        hit = lookup_field_value(value, alias_lookup)
        if hit in EXCLUSION_SENTINELS:
            return "excluded"
        if hit is None:
            return "unresolved"
        return hit

    result = rows.copy()
    result.insert(0, "virus", virus_label)
    result["resolved_to"] = result["raw_value"].map(resolve)
    result["is_canonical"] = ~result["resolved_to"].isin(["excluded", "unresolved"])
    return result
