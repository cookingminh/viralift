# Lift the reference genes an annotated record does not name.
#
# An annotated record takes the direct path: its own CDS / mat_peptide
# coordinates are kept and only the names are normalised. A reference gene the
# annotation does not name is then absent from the output, even when the
# sequence contains it. A complete FMDV genome annotated only as "P1/P2/P3
# precursor" loses all twelve peptides, and short peptides such as 2A and 3B
# are often left unannotated.
#
# With PipelineConfig.lift_missing those genes are lifted with tblastn. The
# record is lifted once against the whole reference, exactly as an unannotated
# record would be (so neighbour-based gap filling still works), and only the
# missing genes' rows are kept; the annotated rows are never changed. The
# annotated genes place the record on the reference, so when every missing
# gene lies outside a partial record nothing is searched.
from typing import Callable, Dict, List, Sequence, Tuple

from app.src.lifting.base import LiftedFeature, PASS_STATUSES
from app.src.lifting.gene_presence import missing_genes_outside_record


def missing_reference_indexes(
    direct_features: Sequence[LiftedFeature],
    ref_features: Sequence[Dict],
) -> List[int]:
    """Indexes of the reference features that no direct row resolved to.

    A gene the annotation check flagged (or replaced) is still present: it has
    a row, just not a clean one.
    """
    found = {f.name for f in direct_features if f.status == "ok" or f.annotation_check}
    return [i for i, ref in enumerate(ref_features) if ref["name"] not in found]


def _unsearched_row(ref: Dict) -> LiftedFeature:
    """A reference gene that was not searched for: the annotation does not name
    it and the annotated genes place it outside the record."""
    return LiftedFeature(
        name=ref["name"],
        source_name=None,
        ref_start=ref["start"],
        ref_end=ref["end"],
        strand=ref.get("strand", "+"),
        query_start=None,
        query_end=None,
        sequence=None,
        coverage=0.0,
        status="no_hit",
        method="direct",
    )


def add_missing_genes(
    direct_features: List[LiftedFeature],
    ref_features: Sequence[Dict],
    record_length: int,
    lift_record: Callable[[], List[LiftedFeature]],
) -> Tuple[List[LiftedFeature], bool]:
    """The direct rows followed by one row per reference gene they lack.

    `lift_record()` lifts every reference feature onto the record and returns
    one row per reference feature, in reference order. It is called at most
    once, and only when a missing gene may lie inside the record.

    Returns the rows and whether tblastn ran.
    """
    missing = missing_reference_indexes(direct_features, ref_features)
    if not missing:
        return direct_features, False

    placeholders = [_unsearched_row(ref_features[i]) for i in missing]
    # Only clean rows place the record: a flagged annotation's coordinates are
    # exactly what is in doubt.
    anchors = [f for f in direct_features if f.status in PASS_STATUSES and f.ref_start is not None]
    ref_strands = {ref["name"]: ref.get("strand", "+") for ref in ref_features}
    outside = set(missing_genes_outside_record(anchors + placeholders, record_length, ref_strands))
    if all(len(anchors) + n in outside for n in range(len(missing))):
        return direct_features + placeholders, False

    lifted = lift_record()
    return direct_features + [lifted[i] for i in missing], True
