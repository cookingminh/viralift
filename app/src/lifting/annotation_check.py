# Check each annotated gene against the reference protein of the same name.
#
# The direct path trusts a record's own CDS / mat_peptide coordinates and only
# normalises the name, so a sloppy annotation passes as a clean gene: S72510.1
# names a 69 nt fragment "1D" (VP1, 633 nt), PV492667.1 calls 1,032 nt "VP1"
# (VP3's tail and 2A included), and AF331831.1's "envelope protein E" maps to
# PRRSV ORF2b although its sequence is ORF5.
#
# With PipelineConfig.check_annotations every annotated gene that resolves to
# a reference gene is translated and aligned (Smith-Waterman, BLOSUM62) to that
# reference protein. Its coverage and identity then mean what they mean for a
# lifted gene, and the same thresholds apply. A gene that fails is looked up
# with tblastn on the whole record; when tblastn places the gene cleanly, its
# row replaces the annotation and keeps the annotation alongside, so a reader
# can see both and switch back. Annotated coordinates are never edited.
from dataclasses import dataclass, replace
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from Bio import Align
from Bio.Align import substitution_matrices
from Bio.Seq import Seq

from app.src.lifting.base import LiftedFeature, PASS_STATUSES

_MATRIX = substitution_matrices.load("BLOSUM62")
_ALPHABET = set(_MATRIX.alphabet)
# BLAST's protein defaults; local, so a partial or over-long annotation aligns
# on the part that is really the gene.
_ALIGNER = Align.PairwiseAligner(
    mode="local", substitution_matrix=_MATRIX, open_gap_score=-11, extend_gap_score=-1,
)

# Fewer aligned residues than this and nothing can be said about the gene.
MIN_ALIGNED_AA = 10
# Over-long: the annotation is this much longer than the reference protein and
# leaves at least EXTRA_AA_FLOOR residues (or EXTRA_FRACTION of it) unaligned.
# Both are needed: a divergent strain's ends may not align without the
# annotation being any longer than the gene.
LONGER_FACTOR = 1.1
EXTRA_FRACTION = 0.1
EXTRA_AA_FLOOR = 10
# A different reference gene is named when it aligns this many times better.
BEST_MATCH_FACTOR = 2.0
# A partial annotation is worth a tblastn search only when the record has at
# least this many nucleotides on the side where the gene is incomplete.
ROOM_TO_EXTEND_NT = 9

VERDICTS = ("confirmed", "partial", "fragment", "low_identity", "overlong")


@dataclass(frozen=True)
class ProteinMatch:
    """Best local alignment of a translated annotation to a reference protein."""
    coverage: float          # share of the reference protein aligned, 0-1
    ref_from: int            # aligned reference residues [ref_from, ref_to)
    ref_to: int
    identity: float          # identical / aligned residue pairs, 0-1
    aligned_aa: int          # reference residues spanned by the alignment
    extra_aa: int            # translated residues outside the alignment
    query_aa: int            # length of the translation
    score: float
    protein: str             # the translation, in the frame that aligned best


def _translate(sequence: str, frame: int) -> str:
    codons = sequence[frame:]
    codons = codons[: len(codons) // 3 * 3]
    if not codons:
        return ""
    protein = str(Seq(codons).translate()).rstrip("*")
    return "".join(aa if aa in _ALPHABET else "X" for aa in protein)


def _align(protein: str, target: str) -> Optional[ProteinMatch]:
    if len(protein) < 3 or not target:
        return None
    alignment = _ALIGNER.align(target, protein)[0]
    (ref_from, ref_to), (query_from, query_to) = (
        (alignment.coordinates[0][0], alignment.coordinates[0][-1]),
        (alignment.coordinates[1][0], alignment.coordinates[1][-1]),
    )
    counts = alignment.counts()
    pairs = counts.identities + counts.mismatches
    return ProteinMatch(
        coverage=(ref_to - ref_from) / len(target),
        ref_from=int(ref_from),
        ref_to=int(ref_to),
        identity=counts.identities / pairs if pairs else 0.0,
        aligned_aa=int(ref_to - ref_from),
        extra_aa=int(len(protein) - (query_to - query_from)),
        query_aa=len(protein),
        score=float(alignment.score),
        protein=protein,
    )


def match_reference(sequence: str, target: str) -> Optional[ProteinMatch]:
    """Align the annotated nucleotide sequence to the reference protein.

    The annotation's own frame (0) is tried first; the other two only when it
    does not give a clean match, e.g. a partial CDS starting mid-codon.
    """
    best = _align(_translate(sequence, 0), target)
    if best and best.coverage >= 0.5 and best.identity >= 0.5:
        return best
    for frame in (1, 2):
        match = _align(_translate(sequence, frame), target)
        if match and (best is None or match.score > best.score):
            best = match
    return best


def classify(match: Optional[ProteinMatch], ref_aa: int, min_coverage: float, min_identity: float):
    """(verdict, status) for an annotation, with the lifted genes' thresholds."""
    if match is None or match.aligned_aa < MIN_ALIGNED_AA:
        return "fragment", "low_coverage"
    if match.query_aa > LONGER_FACTOR * ref_aa and match.extra_aa > max(EXTRA_AA_FLOOR, EXTRA_FRACTION * ref_aa):
        return "overlong", "overlong_annotation"
    low_coverage = match.coverage < min_coverage
    low_identity = match.identity < min_identity
    if low_coverage and low_identity:
        return "low_identity", "low_coverage_and_identity"
    if low_coverage:
        return "partial", "low_coverage"
    if low_identity:
        return "low_identity", "low_identity"
    return "confirmed", "ok"


def best_other_gene(protein: str, name: str, ref_proteins: Dict[str, str], own_score: float) -> Optional[str]:
    """A reference gene the annotated protein matches far better than its own."""
    scores = {
        other: _ALIGNER.score(target, protein)
        for other, target in ref_proteins.items()
        if other != name and target
    }
    if not scores:
        return None
    other, score = max(scores.items(), key=lambda item: item[1])
    return other if score >= BEST_MATCH_FACTOR * max(own_score, 1.0) else None


def check_feature(
    feature: LiftedFeature,
    ref_proteins: Dict[str, str],
    min_coverage: float,
    min_identity: float,
) -> Tuple[LiftedFeature, Optional[ProteinMatch]]:
    """The annotated row with coverage, identity and status from the protein
    check, and the alignment behind them."""
    target = ref_proteins.get(feature.name)
    if not target or not feature.sequence:
        return feature, None
    match = match_reference(feature.sequence, target)
    verdict, status = classify(match, len(target), min_coverage, min_identity)
    # A failing annotation may simply carry the wrong name (AF331831.1).
    best_match = None
    if verdict != "confirmed":
        protein = match.protein if match else _translate(feature.sequence, 0)
        if len(protein) >= MIN_ALIGNED_AA:
            best_match = best_other_gene(protein, feature.name, ref_proteins, match.score if match else 0.0)
    return replace(
        feature,
        status=status,
        coverage=round(match.coverage, 4) if match else 0.0,
        identity=round(match.identity * 100, 1) if match else None,
        annotation_check=verdict,
        best_match=best_match,
    ), match


def worth_searching(feature: LiftedFeature, match: Optional[ProteinMatch], ref_aa: int, record_length: int) -> bool:
    """Could tblastn find more than this failing annotation holds?

    A partial annotation whose missing part would lie beyond the record's ends
    (JQ041374.1: 249 bp, VP1's last 40 codons at 1-124) cannot be extended, so
    searching is wasted time. Anything else (over-long, low identity, no
    alignment at all) is always searched.
    """
    if feature.annotation_check not in ("partial", "fragment") or match is None:
        return True
    if feature.query_start is None or feature.query_end is None:
        return True
    before = feature.query_start - 1
    after = record_length - feature.query_end
    if feature.strand == "-":
        before, after = after, before
    missing_start = match.ref_from > 0
    missing_end = match.ref_to < ref_aa
    return (missing_start and before >= ROOM_TO_EXTEND_NT) or (missing_end and after >= ROOM_TO_EXTEND_NT)


def check_annotations(
    features: List[LiftedFeature],
    ref_features: Sequence[Dict],
    ref_proteins: Dict[str, str],
    lift_record: Callable[[], List[LiftedFeature]],
    min_coverage: float,
    min_identity: float,
    record_length: int,
) -> List[LiftedFeature]:
    """Check every annotated gene that resolved to a reference gene; replace a
    failing one with its tblastn row when that row passes and places the gene
    differently (the same span adds nothing: PV533621.1's ORF3 is truncated by
    a deletion, and tblastn's "OK" there would only hide it).

    `lift_record()` returns one row per reference feature, in reference order,
    and is called at most once per record, only when a failing gene is worth
    searching for.
    """
    index_of = {ref["name"]: i for i, ref in enumerate(ref_features)}
    checked: List[LiftedFeature] = []
    matches: Dict[int, Optional[ProteinMatch]] = {}
    for i, feature in enumerate(features):
        if feature.method == "direct" and feature.status == "ok" and feature.name in index_of:
            feature, matches[i] = check_feature(feature, ref_proteins, min_coverage, min_identity)
        checked.append(feature)
    failing = [
        i for i, f in enumerate(checked)
        if f.annotation_check and f.status not in PASS_STATUSES
        and worth_searching(f, matches.get(i), len(ref_proteins.get(f.name, "")), record_length)
    ]
    if not failing:
        return checked

    lifted = lift_record()
    for i in failing:
        annotated = checked[i]
        alternative = lifted[index_of[annotated.name]]
        same_span = (alternative.query_start, alternative.query_end) == (annotated.query_start, annotated.query_end)
        if alternative.status in PASS_STATUSES and alternative.query_start is not None and not same_span:
            checked[i] = replace(
                alternative,
                source_name=annotated.source_name,
                annotation_check=annotated.annotation_check,
                best_match=annotated.best_match,
                annotation=annotated,
            )
    return checked


def reference_proteins(ref_features: Sequence[Dict], translate: Callable[[Dict], Optional[str]]) -> Dict[str, str]:
    """Reference gene name -> protein, in the aligner's alphabet."""
    proteins = {}
    for feature in ref_features:
        protein = translate(feature)
        if protein:
            proteins[feature["name"]] = "".join(
                aa if aa in _ALPHABET else "X" for aa in str(protein).rstrip("*")
            )
    return proteins
