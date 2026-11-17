"""
ViraLift engine adapter: the real tblastn lift (forced on every record) and the real shipped pipeline (routing included).

Functions here were moved verbatim from validation/_shared/validation_utils.py
(validation branch @ b9f5894). Any change to a scoring rule must come with a
test in validation/tests/ and a note in validation/METHODOLOGY.md.
"""
from __future__ import annotations

from pathlib import Path
from typing import Tuple

import pandas as pd

from app.src.features.annotation_strategy import get_strategy, select_feature_type
from app.src.io.genbank_parser import load_genbank_records
from app.src.lifting.tblastn_lifter import lift_all_tblastn
from app.src.pipeline import PipelineConfig, run_pipeline

from validation.valkit.datasets import load_reference_bundle
from validation.valkit.metrics import compare_predictions_to_truth, lifted_to_rows
from validation.valkit.paths import CONFIG
from validation.valkit.report import attach_ref_lengths, summarize_comparison, summarize_overall, summarize_per_gene
from validation.valkit.truth import build_truth_presence, parse_validation_truth_features, ref_codon_checkable_genes


def run_lifting_accuracy(virus_label: str, ref_path: Path, query_path: Path, output_dir: Path,
                         registry_path: Path = CONFIG / "virus_alias_registry.json",
                         progress: bool = True, reverse_complement: bool = False):
    """One-call lifting-accuracy: run tblastn, build truth presence, per-gene + overall buckets.

    Returns (per_pred, per_gene, overall, truth_presence, ref_model). per_pred carries the
    diagnostic columns (pred_len, delta_start/end, pred_minus_ref_len, ...) for inspection.

    reverse_complement=True lifts the reverse complement of every record and maps the
    coordinates back, so the truth is unchanged: a strand-handling check on real data.
    """
    per_pred, _ = run_tblastn_against_truth(virus_label, ref_path, query_path, output_dir,
                                            registry_path=registry_path, progress=progress,
                                            reverse_complement=reverse_complement)
    bundle = load_reference_bundle(ref_path, registry_path)
    records = load_genbank_records(query_path)
    ref_model, truth_presence = build_truth_presence(bundle, records, virus_label)
    per_pred = attach_ref_lengths(per_pred, ref_model)
    per_gene = summarize_per_gene(per_pred, truth_presence, ref_model, virus_label)
    overall = summarize_overall(per_gene)
    return per_pred, per_gene, overall, truth_presence, ref_model


def run_tblastn_against_truth(
    virus_label: str,
    ref_path: Path,
    query_path: Path,
    output_dir: Path,
    registry_path: Path = CONFIG / "virus_alias_registry.json",
    progress: bool = True,
    reverse_complement: bool = False,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    from tqdm.auto import tqdm
    from Bio.SeqRecord import SeqRecord

    bundle = load_reference_bundle(ref_path, registry_path)
    query_records = load_genbank_records(query_path)
    codon_required = ref_codon_checkable_genes(bundle)
    rows = []

    iterator = tqdm(
        query_records,
        desc=f"tblastn  {virus_label}",
        unit="rec",
        dynamic_ncols=True,
        leave=True,
    ) if progress else query_records

    for record in iterator:
        truth, _ = parse_validation_truth_features(
            record,
            bundle["alias_lookup"],
            bundle["feature_type"],
            bundle["features"],
            virus_label,
        )
        if not truth:
            continue
        if progress:
            iterator.set_postfix_str(record.id, refresh=True)
        # Force the tblastn engine on every record (this measures lifting quality,
        # not routing) but with the tool's default config, not incidental defaults.
        cfg = PipelineConfig()
        target = record
        if reverse_complement:
            target = SeqRecord(record.seq.reverse_complement(), id=record.id, name=record.name,
                               description=record.description)
        lifted = lift_all_tblastn(
            ref_features=bundle["features"],
            ref_record=bundle["record"],
            query_record=target,
            min_coverage=cfg.min_coverage,
            min_identity=cfg.min_identity,
            evalue=cfg.evalue,
            rescue_window=cfg.rescue_window,
            validate_codons=(bundle["feature_type"] == "CDS"),
        )
        if reverse_complement:
            # Map back onto the deposited orientation so the truth needs no change.
            length = len(record.seq)
            for lf in lifted:
                if lf.query_start is not None and lf.query_end is not None:
                    lf.query_start, lf.query_end = length - lf.query_end + 1, length - lf.query_start + 1
                    lf.strand = {"+": "-", "-": "+"}.get(lf.strand, lf.strand)
        preds = lifted_to_rows(record.id, lifted, "tblastn")
        compared = compare_predictions_to_truth(preds, truth, codon_required_names=codon_required)
        compared.insert(0, "virus", virus_label)
        rows.append(compared)

    result = pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()
    summary = summarize_comparison(result, ["virus", "method"]) if not result.empty else pd.DataFrame()
    output_dir.mkdir(parents=True, exist_ok=True)
    result.to_csv(output_dir / "tblastn_vs_truth.tsv", sep="\t", index=False)
    summary.to_csv(output_dir / "tblastn_summary.tsv", sep="\t", index=False)
    return result, summary


def run_production_pipeline_against_truth(
    virus_label: str,
    ref_path: Path,
    query_path: Path,
    output_dir: Path,
    registry_path: Path = CONFIG / "virus_alias_registry.json",
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    bundle = load_reference_bundle(ref_path, registry_path)
    query_records = load_genbank_records(query_path)

    # Run the EXACT shipping pipeline (same routing + same default config the CLI
    # and UI use) so validation measures what users actually run — no re-implemented
    # routing, no magic parameters. run_pipeline handles direct vs tblastn internally.
    run_result = run_pipeline(
        ref_record=bundle["record"],
        query_records=query_records,
        ref_features=bundle["features"],
        ref_feature_type=bundle["feature_type"],
        alias_lookup=bundle["alias_lookup"],
        config=PipelineConfig(),
    )
    lifted_by_record = dict(run_result.all_results)
    codon_required = ref_codon_checkable_genes(bundle)

    rows = []
    for record in query_records:
        truth_type = select_feature_type(record, bundle["alias_lookup"]) or bundle["feature_type"]
        truth, _ = parse_validation_truth_features(
            record,
            bundle["alias_lookup"],
            truth_type,
            bundle["features"],
            virus_label,
        )
        if not truth:
            continue
        # method label only — same deterministic call the pipeline made internally
        strategy, _ = get_strategy(record, bundle["alias_lookup"])
        lifted = lifted_by_record.get(record.id, [])
        preds = lifted_to_rows(record.id, lifted, strategy)
        compared = compare_predictions_to_truth(preds, truth, codon_required_names=codon_required)
        compared.insert(0, "virus", virus_label)
        rows.append(compared)
    result = pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()
    summary = summarize_comparison(result, ["virus", "method"]) if not result.empty else pd.DataFrame()
    output_dir.mkdir(parents=True, exist_ok=True)
    result.to_csv(output_dir / "e2e_per_prediction.tsv", sep="\t", index=False)
    summary.to_csv(output_dir / "e2e_summary.tsv", sep="\t", index=False)
    return result, summary
