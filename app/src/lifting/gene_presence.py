# Which `no_hit` genes simply lie outside a partial query record?
#
# The engine reports `no_hit` whenever tblastn finds nothing. That mixes two
# cases: the gene is outside the sequenced region (a VP1-only record has no 3D
# gene to find) and the gene should be there but was missed. Gene order is
# fixed within a virus species, so the genes that *were* located place every
# other gene on the record: if a missing gene's expected span falls outside
# the record it is "not in sequence"; if it falls inside, the miss is real.
#
# Used twice: the UI shows such genes as "Not in sequence" (a display status;
# the engine still reports `no_hit`), and the pipeline's lift-missing option
# (app/src/lifting/missing_genes.py) skips searching for them.
from typing import Callable, Dict, List, Optional, Sequence
from app.src.lifting.base import LiftedFeature, PASS_STATUSES


NOT_IN_SEQUENCE = "not_in_sequence"

# A miss stays a real `no_hit` once this share of its expected span is inside
# the record; below it the gene is treated as outside the sequenced region.
MIN_INSIDE_FRACTION = 0.2
# Located genes that disagree by more than this (bp) about where the record
# sits on the reference mean a rearranged or garbled record: keep `no_hit`.
MAX_ANCHOR_SPREAD = 300
# A located gene this close (bp) to a record end is treated as cut off there.
EDGE_TOLERANCE = 3


def _is_anchor(feature: LiftedFeature) -> bool:
    return (
        feature.status != "no_hit"
        and None not in (feature.query_start, feature.query_end, feature.ref_start, feature.ref_end)
    )


def _ref_to_query(anchor: LiftedFeature, record_length: int, ref_strand: str) -> Callable[[float], float]:
    """Linear reference -> query coordinate map implied by one located gene.

    Uses whichever edge of the gene the record does not cut off, so a gene
    truncated at a record end still places its neighbours correctly. A gene
    that failed a quality gate keeps the raw tblastn coordinates, which start
    `n_term_missing_aa` residues into the reference protein.
    """
    cut_at_start = anchor.query_start <= EDGE_TOLERANCE
    cut_at_end = anchor.query_end >= record_length - EDGE_TOLERANCE
    n_term_bp = 0 if anchor.status in PASS_STATUSES else 3 * (anchor.n_term_missing_aa or 0)

    if anchor.strand == ref_strand:
        # Same orientation as the reference: q = r + offset.
        if cut_at_start and not cut_at_end:
            offset = anchor.query_end - anchor.ref_end
        else:
            offset = anchor.query_start - (anchor.ref_start + n_term_bp)
        return lambda r: r + offset

    # Record runs opposite to the reference: q = c - r, ref start -> query end.
    if cut_at_end and not cut_at_start:
        c = anchor.query_start + anchor.ref_end
    else:
        c = anchor.query_end + anchor.ref_start + n_term_bp
    return lambda r: c - r


def _ref_distance(a: LiftedFeature, b: LiftedFeature) -> int:
    return max(0, max(a.ref_start, b.ref_start) - min(a.ref_end, b.ref_end))


def missing_genes_outside_record(
    features: Sequence[LiftedFeature],
    record_length: int,
    ref_strands: Optional[Dict[str, str]] = None,
) -> List[int]:
    """Indexes of `no_hit` features whose expected span lies outside the record.

    `ref_strands` maps a gene name to its strand on the reference (default "+");
    a located gene's own `strand` is its strand on the query.
    """
    ref_strands = ref_strands or {}
    anchors = [f for f in features if _is_anchor(f)]
    if not anchors or record_length <= 0:
        return []

    maps = {id(a): _ref_to_query(a, record_length, ref_strands.get(a.name, "+")) for a in anchors}
    # Annotated coordinates are sometimes sloppy (PV492667.1 annotates "VP1"
    # over 1,032 bp, VP3's tail and 2A included), while a lifted gene is placed
    # by aligning the reference protein. When the two disagree, the lifted
    # genes alone decide.
    groups = [anchors]
    lifted = [a for a in anchors if a.method == "tblastn"]
    if lifted and len(lifted) < len(anchors):
        groups.append(lifted)

    outside = []
    for index, feature in enumerate(features):
        if feature.status != "no_hit" or feature.ref_start is None or feature.ref_end is None:
            continue

        # Where every located gene says this one starts; they must roughly agree.
        for group in groups:
            predicted_starts = [maps[id(a)](feature.ref_start) for a in group]
            if max(predicted_starts) - min(predicted_starts) <= MAX_ANCHOR_SPREAD:
                break
        else:
            continue

        nearest = min(group, key=lambda a: (_ref_distance(a, feature), a.status not in PASS_STATUSES))
        to_query = maps[id(nearest)]
        lo, hi = sorted((to_query(feature.ref_start), to_query(feature.ref_end)))
        span = hi - lo + 1
        inside = max(0.0, min(hi, record_length) - max(lo, 1) + 1)
        if inside / span < MIN_INSIDE_FRACTION:
            outside.append(index)
    return outside


def nothing_located(features: Sequence[LiftedFeature]) -> bool:
    """True when a record has features but none of them was placed on it."""
    return bool(features) and all(f.query_start is None for f in features)
