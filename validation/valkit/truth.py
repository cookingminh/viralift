"""
Truth construction: which features of a query record count as ground truth, and the R ∩ truth restriction (METHODOLOGY.md §1-2).

Functions here were moved verbatim from validation/_shared/validation_utils.py
(validation branch @ b9f5894). Any change to a scoring rule must come with a
test in validation/tests/ and a note in validation/METHODOLOGY.md.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Sequence, Tuple

import pandas as pd
from Bio.SeqRecord import SeqRecord

from app.src.alias.gene_alias import apply_alias_to_features
from app.src.io.genbank_parser import parse_cds_features, parse_mat_peptides


def filter_subfeatures(features: Sequence[Dict], max_ratio: float = 0.8) -> Tuple[List[Dict], List[Dict]]:
    main, subs = [], []
    for i, feature in enumerate(features):
        feature_len = feature["end"] - feature["start"] + 1
        is_subfeature = any(
            j != i
            and feature["start"] >= parent["start"]
            and feature["end"] <= parent["end"]
            and feature_len < max_ratio * (parent["end"] - parent["start"] + 1)
            for j, parent in enumerate(features)
        )
        (subs if is_subfeature else main).append(feature)
    return main, subs


def parse_features_for_type(record: SeqRecord, feature_type: Optional[str]) -> List[Dict]:
    if feature_type == "mat_peptide":
        return parse_mat_peptides(record)
    if feature_type == "CDS":
        return parse_cds_features(record)
    return []


def parse_truth_features(
    record: SeqRecord,
    alias_lookup: Dict[str, str],
    feature_type: Optional[str],
    filter_nested: bool = True,
    target_names: Optional[Sequence[str]] = None,
    keep_extra_names: Optional[Sequence[str]] = None,
) -> Tuple[List[Dict], List[Dict]]:
    features = parse_features_for_type(record, feature_type)
    if alias_lookup and features:
        features = apply_alias_to_features(features, alias_lookup)
    if target_names is not None:
        allowed = set(target_names)
        if keep_extra_names:
            allowed.update(keep_extra_names)
        kept = [feature for feature in features if feature.get("name") in allowed]
        dropped = [feature for feature in features if feature.get("name") not in allowed]
        return kept, dropped
    if not filter_nested:
        return features, []
    return filter_subfeatures(features)


def truth_target_names(ref_features: Sequence[Dict], virus_label: Optional[str] = None) -> Tuple[List[str], List[str]]:
    # Truth targets = the gene names the reference actually carries (set R).
    # Accuracy denominator is R ∩ query-truth: a gene is only evaluable on a
    # record whose truth contains it. Granularity/merge cases (e.g. a query
    # ORF1ab where the ref has ORF1a/ORF1b) fall outside R and are reported
    # separately by the failure-attribution notebook via a generic overlap
    # rule — no virus- or gene-name is hard-coded here.
    target_names = sorted({feature["name"] for feature in ref_features if feature.get("name")})
    return target_names, []


def should_use_target_truth_filter(feature_type: Optional[str], virus_label: Optional[str] = None) -> bool:
    # Apply the ref-gene truth filter for coding-sequence evaluation, generically
    # for every virus (virus_label kept only for signature compatibility).
    return feature_type == "CDS"


def parse_validation_truth_features(
    record: SeqRecord,
    alias_lookup: Dict[str, str],
    feature_type: Optional[str],
    ref_features: Sequence[Dict],
    virus_label: Optional[str] = None,
) -> Tuple[List[Dict], List[Dict]]:
    if should_use_target_truth_filter(feature_type, virus_label):
        targets, extras = truth_target_names(ref_features, virus_label)
        return parse_truth_features(
            record,
            alias_lookup,
            feature_type,
            filter_nested=False,
            target_names=targets,
            keep_extra_names=extras,
        )
    return parse_truth_features(record, alias_lookup, feature_type)


def dedupe_truth_by_name(truth_features: Sequence[Dict]) -> List[Dict]:
    """Collapse truth features that share a name, keeping the longest.

    `compare_predictions_to_truth` already resolves truth by name this way (see its
    `truth_by_name` loop): at most ONE truth feature per name can ever be matched. A
    truth-anchored harness that counts every raw truth feature therefore inflates its own
    denominator whenever a record annotates the same gene twice -- the duplicate is an
    automatic miss for every tool, by construction rather than by performance.

    Real case: PRRSV `AF331831.1` labels BOTH ORF1a and ORF1b "RNA polymerase", so ORF1b
    appears twice in truth after alias resolution. Counting it twice made the comparison
    denominator 797 where the accuracy harness (which counts (record, gene) presence via
    `build_truth_presence`) counts 796.

    Use this in truth-anchored harnesses that build their denominator from the truth list, so
    the denominator matches what the comparator can actually match.
    """
    best: Dict[str, Dict] = {}
    for feature in truth_features:
        existing = best.get(feature["name"])
        if existing is None or (feature["end"] - feature["start"]) > (existing["end"] - existing["start"]):
            best[feature["name"]] = feature
    return [feature for feature in truth_features if best.get(feature["name"]) is feature]


def ref_codon_checkable_genes(bundle: Dict) -> set:
    """Reference genes whose OWN CDS is codon-clean (valid start + stop + frame).

    Only these genes are held to the codon check when scoring predictions. Reference
    features that are partial / frameshift / overlapping (e.g. PRRSV ORF1b, annotated
    `<7687..12072`, which has no independent ATG start) fail this and are therefore
    exempt — an "invalid codon" on such a gene reflects its biology, not a tool error.
    Empty set for non-CDS reference feature types (mat_peptide), where codon validity
    does not apply. Fully data-driven from the reference; no gene name is hard-coded.
    """
    if bundle.get("feature_type") != "CDS":
        return set()
    from Bio.Seq import Seq
    from app.src.lifting.validator import validate_cds_boundaries
    seq = str(bundle["record"].seq)
    genes = set()
    for f in bundle["features"]:
        s, e, strand, name = f.get("start"), f.get("end"), f.get("strand"), f.get("name")
        if s is None or e is None or not name:
            continue
        sub = seq[s - 1:e]
        if strand in ("-", -1):
            sub = str(Seq(sub).reverse_complement())
        if validate_cds_boundaries(sub).get("valid"):
            genes.add(name)
    return genes


# --------------------------------------------------------------------------- #
# Truth-based per-gene accuracy (ported from the archived accuracy notebooks). #
# Denominator = records where the reference gene is present in the query truth #
# (R ∩ query-truth), aligned by ref_name. Catches "no prediction at all" cases #
# and surfaces name-gap predictions separately. Fully generic (no gene names). #
# --------------------------------------------------------------------------- #


def build_truth_presence(bundle: Dict, query_records: Sequence[SeqRecord],
                         virus_label: Optional[str] = None) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Return (ref_model, truth_presence).

    ref_model: one row per reference gene with ref_start/ref_end/ref_len.
    truth_presence: one row per (record, ref-gene) with has_truth_gene flag.
    """
    ref_features = bundle["features"]
    ref_model = pd.DataFrame(ref_features).copy()
    ref_model["ref_len"] = ref_model["end"] - ref_model["start"] + 1
    ref_model = (
        ref_model.rename(columns={"name": "ref_name", "start": "ref_start", "end": "ref_end"})
        [["ref_name", "ref_start", "ref_end", "ref_len", "strand"]]
        .sort_values(["ref_start", "ref_end"])
        .reset_index(drop=True)
    )
    ref_gene_names = ref_model["ref_name"].dropna().astype(str).tolist()
    rows = []
    for record in query_records:
        truth_features, _ = parse_validation_truth_features(
            record, bundle["alias_lookup"], bundle["feature_type"], ref_features, virus_label,
        )
        truth_names = {f["name"] for f in truth_features}
        for gene in ref_gene_names:
            rows.append({"record_id": record.id, "gene": gene, "has_truth_gene": gene in truth_names})
    return ref_model, pd.DataFrame(rows)
