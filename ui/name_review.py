# Logic behind the Review names step, kept free of Streamlit so it can be tested.
#
# Rows: one per exact set of qualifier names. ("P1", "capsid protein") and
# ("capsid protein", "P1") are one decision; ("capsid protein", "VP0") is another
# even though it shares a name (see services._scan_unknown_names).
#
# Position evidence: the reference genes are lifted onto a few records that carry
# a row's names (tblastn, as in the pipeline) and the annotated span is compared
# with them. Coordinates say which gene a name refers to far more reliably than
# the wording: "structural protein 1A" sits exactly on VP4, while a 2,208 bp
# "capsid protein" spans VP4..VP1 and is the P1 precursor, not VP1.
#
# Session lookup: the engine applies decisions by name, so mapping a shared name
# for one row would also rename every other feature carrying it. The plan keeps
# only the names that leave every other feature's outcome unchanged and reports
# the rows it could not express that way.
from collections import Counter
from typing import Callable, Dict, FrozenSet, Iterable, List, Optional, Sequence, Set, Tuple
from Bio.SeqRecord import SeqRecord
from app.src.alias.alias_bootstrap import compute_iou
from app.src.alias.alias_classifier import _is_generic_name
from app.src.alias.gene_alias import apply_alias_to_feature, normalize_text
from app.src.features.annotation_strategy import select_feature_type
from app.src.io.genbank_parser import _LOOKUP_QUALIFIER_KEYS
from app.src.lifting.base import LiftedFeature


MATCH_IOU = 0.90          # same bar as coordinate-supported bootstrap suggestions
CONTAINED_FRACTION = 0.80  # a gene counts as covered once this share of it is inside the span
SAMPLE_RECORDS = 3         # records lifted per row
EXCLUDED = "__excluded__"  # outcome of a feature whose names are all excluded

NameSet = FrozenSet[str]


# ── names ────────────────────────────────────────────────────────────────

def feature_name_values(qualifiers: Dict[str, List[str]]) -> List[str]:
    """Qualifier values that can name a feature, in lookup priority order."""
    values: List[str] = []
    for field in _LOOKUP_QUALIFIER_KEYS:
        value = (qualifiers.get(field) or [None])[0]
        if value and value not in values:
            values.append(value)
    return values


def name_set(values: Iterable[str]) -> NameSet:
    return frozenset(normalize_text(value) for value in values)


def _parts(value: str) -> Set[str]:
    """Normalized forms a lookup key can match: the whole value or a ';' part."""
    parts = {normalize_text(value)}
    parts.update(normalize_text(part) for part in value.split(";") if part.strip())
    return parts


# ── position evidence ────────────────────────────────────────────────────

def _overlap(start: int, end: int, other_start: int, other_end: int) -> int:
    return max(0, min(end, other_end) - max(start, other_start) + 1)


def classify_span(start: int, end: int, lifted: Sequence[LiftedFeature]) -> Dict:
    """Where an annotated span sits relative to the reference genes lifted onto
    the same record: match (one gene), spans (several), inside (part of one),
    overlaps (partly one) or none."""
    located = [lf for lf in lifted if lf.query_start is not None and lf.query_end is not None]
    if not located:
        return {"verdict": "none"}
    best_iou, best = max(
        ((compute_iou(start, end, lf.query_start, lf.query_end), lf) for lf in located),
        key=lambda pair: pair[0],
    )
    if best_iou >= MATCH_IOU:
        return {"verdict": "match", "gene": best.name, "iou": round(best_iou, 2)}

    covered = [
        lf for lf in located
        if _overlap(start, end, lf.query_start, lf.query_end)
        >= CONTAINED_FRACTION * (lf.query_end - lf.query_start + 1)
    ]
    if len(covered) >= 2:
        covered.sort(key=lambda lf: lf.ref_start if lf.ref_start is not None else 0)
        return {"verdict": "spans", "genes": [lf.name for lf in covered]}

    span_length = end - start + 1
    for lf in located:
        if _overlap(start, end, lf.query_start, lf.query_end) >= CONTAINED_FRACTION * span_length:
            return {"verdict": "inside", "gene": lf.name}
    if best_iou > 0:
        return {"verdict": "overlaps", "gene": best.name, "iou": round(best_iou, 2)}
    return {"verdict": "none"}


def _signature(verdict: Dict) -> Tuple:
    return verdict["verdict"], verdict.get("gene"), tuple(verdict.get("genes", ()))


def summarize_position(verdicts: Sequence[Dict]) -> Dict:
    """One verdict for a row: decisive only when every checked record agrees."""
    if not verdicts:
        return {"verdict": "unplaced", "checked": 0}
    counts = Counter(_signature(v) for v in verdicts)
    top, agree = counts.most_common(1)[0]
    if agree < len(verdicts):
        return {"verdict": "mixed", "checked": len(verdicts), "agree": agree}
    agreeing = [v for v in verdicts if _signature(v) == top]
    summary = {**agreeing[0], "checked": len(verdicts), "agree": agree}
    if "iou" in summary:
        summary["iou"] = min(v["iou"] for v in agreeing)
    return summary


def locate_names(
    record: SeqRecord,
    names: NameSet,
    alias_lookup: Dict[str, str],
    excluded_names: Set[str],
) -> List[Tuple[str, int, int]]:
    """(feature_type, start, end) of the features in `record` that carry exactly
    these non-excluded names, on the feature level the pipeline would use."""
    feature_type = select_feature_type(record, alias_lookup)
    spans = []
    for feature in record.features:
        if feature.type != feature_type:
            continue
        kept = [v for v in feature_name_values(feature.qualifiers) if normalize_text(v) not in excluded_names]
        if kept and name_set(kept) == names:
            spans.append((feature.type, int(feature.location.start) + 1, int(feature.location.end)))
    return spans


def position_evidence(
    rows: Dict[str, Dict],
    records: Dict[str, SeqRecord],
    alias_lookup: Dict[str, str],
    excluded_names: Set[str],
    lift: Callable[[SeqRecord], List[LiftedFeature]],
    progress: Optional[Callable[[int, int, str], None]] = None,
) -> Dict[str, Dict]:
    """Position verdict per row, lifting each sampled record once."""
    placements: Dict[str, List[Tuple[str, str, int, int]]] = {}
    for key, info in rows.items():
        names = name_set(info.get("candidates", []))
        found = []
        for record_id in info.get("records", [])[:SAMPLE_RECORDS]:
            record = records.get(record_id)
            if record is None:
                continue
            spans = locate_names(record, names, alias_lookup, excluded_names)
            if spans:
                feature_type, start, end = spans[0]
                found.append((record_id, feature_type, start, end))
        placements[key] = found

    to_lift = list(dict.fromkeys(record_id for found in placements.values() for record_id, *_ in found))
    lifted: Dict[str, List[LiftedFeature]] = {}
    for index, record_id in enumerate(to_lift):
        if progress:
            progress(index, len(to_lift), record_id)
        lifted[record_id] = lift(records[record_id])
    if progress:
        progress(len(to_lift), len(to_lift), "")

    evidence = {}
    for key, found in placements.items():
        verdicts = []
        for record_id, feature_type, start, end in found:
            verdict = classify_span(start, end, lifted[record_id])
            verdicts.append({
                **verdict,
                "record": record_id,
                "feature_type": feature_type,
                "start": start,
                "end": end,
                "record_length": len(records[record_id].seq),
            })
        evidence[key] = summarize_position(verdicts)
    return evidence


def llm_position_context(evidence: Dict) -> Dict:
    """The row's position evidence in the fields the LLM payload understands."""
    if not evidence or evidence.get("verdict") in (None, "unplaced"):
        return {}
    verdict = evidence["verdict"]
    context = {
        "coordinate_verdict": verdict,
        "records_checked": evidence.get("checked"),
        "records_agreeing": evidence.get("agree"),
        "feature_type": evidence.get("feature_type"),
        "start": evidence.get("start"),
        "end": evidence.get("end"),
        "genome_length": evidence.get("record_length"),
    }
    if verdict == "match":
        context.update(ref_slot_by_position=evidence["gene"], coordinate_iou=evidence.get("iou"))
    elif verdict == "spans":
        context["spans_reference_genes"] = evidence.get("genes")
    elif verdict == "inside":
        context["is_subfeature_of"] = evidence["gene"]
    elif verdict == "overlaps":
        context.update(overlaps_reference_gene=evidence["gene"], coordinate_iou=evidence.get("iou"))
    return {key: value for key, value in context.items() if value is not None}


# ── applying decisions ───────────────────────────────────────────────────

def name_patterns(
    records: Iterable[SeqRecord],
    alias_lookup: Dict[str, str],
    excluded_names: Set[str],
) -> List[Dict]:
    """Every distinct qualifier pattern on the feature level the pipeline uses,
    with its non-excluded name set and how many features carry it."""
    counts: Counter = Counter()
    for record in records:
        feature_type = select_feature_type(record, alias_lookup)
        if feature_type is None:
            continue
        for feature in record.features:
            if feature.type != feature_type:
                continue
            fields = tuple(
                (field, feature.qualifiers[field][0])
                for field in _LOOKUP_QUALIFIER_KEYS
                if feature.qualifiers.get(field) and feature.qualifiers[field][0]
            )
            if fields:
                counts[fields] += 1
    patterns = []
    for fields, count in counts.items():
        values = list(dict.fromkeys(value for _, value in fields))
        kept = [v for v in values if normalize_text(v) not in excluded_names]
        patterns.append({
            "feature": {**dict(fields), "name": values[0]},
            "values": values,
            "names": name_set(kept) if kept else frozenset(),
            "count": count,
        })
    return patterns


def _outcome(feature: Dict, lookup: Dict[str, str]) -> str:
    resolved = apply_alias_to_feature(feature, lookup)
    if resolved["name_source"] in ("alias", "alias_conflict_resolved"):
        return resolved["name"]
    if resolved["name_source"] == "excluded":
        return EXCLUDED
    return ""


def _effective(base: Dict[str, str], mappings: Dict[str, str]) -> Dict[str, str]:
    effective = dict(base)
    effective.update({normalize_text(name): canonical for name, canonical in mappings.items()})
    return effective


def plan_session_lookup(
    rows: Dict[str, Dict],
    decisions: Dict[str, Optional[str]],
    patterns: Sequence[Dict],
    base_lookup: Dict[str, str],
) -> Tuple[Dict[str, str], List[str]]:
    """Name mappings that give every row its decided outcome without changing any
    other feature, plus the decided rows that cannot be expressed that way.

    A row decided "keep raw" (None) must stay raw; features outside the reviewed
    rows must keep the outcome the alias config already gives them.
    """
    row_by_names = {name_set(info["candidates"]): key for key, info in rows.items()}
    intended = []
    for pattern in patterns:
        key = row_by_names.get(pattern["names"])
        want = (decisions.get(key) or "") if key in decisions else _outcome(pattern["feature"], base_lookup)
        intended.append((pattern, key, want, set().union(*(_parts(v) for v in pattern["values"]))))

    mappings = {
        candidate: canonical
        for key, canonical in decisions.items()
        if canonical and key in rows
        for candidate in rows[key]["candidates"]
    }
    while True:
        effective = _effective(base_lookup, mappings)
        wrong: Set[str] = set()
        for pattern, _, want, parts in intended:
            if _outcome(pattern["feature"], effective) == want:
                continue
            wrong.update(
                name for name, canonical in mappings.items()
                if canonical != want and normalize_text(name) in parts
            )
        if not wrong:
            break
        for name in wrong:
            del mappings[name]

    effective = _effective(base_lookup, mappings)
    blocked = sorted({
        key for pattern, key, want, _ in intended
        if key in decisions and decisions[key] and _outcome(pattern["feature"], effective) != want
    })
    return mappings, blocked


def names_shared_elsewhere(
    rows: Dict[str, Dict],
    decisions: Dict[str, Optional[str]],
    patterns: Sequence[Dict],
    base_lookup: Dict[str, str],
) -> Dict[str, Set[str]]:
    """For each row, the names that also appear on features meant to end up as
    something else. Saving such a name as an alias would rename those features
    in every later run, so it is never pre-selected for saving."""
    row_by_names = {name_set(info["candidates"]): key for key, info in rows.items()}
    outcomes_by_part: Dict[str, Set[str]] = {}
    for pattern in patterns:
        key = row_by_names.get(pattern["names"])
        want = (decisions.get(key) or "") if key in decisions else _outcome(pattern["feature"], base_lookup)
        for value in pattern["values"]:
            for part in _parts(value):
                outcomes_by_part.setdefault(part, set()).add(want)
    shared = {}
    for key, info in rows.items():
        mine = decisions.get(key) or ""
        shared[key] = {
            candidate for candidate in info["candidates"]
            if outcomes_by_part.get(normalize_text(candidate), {mine}) - {mine}
        }
    return shared


def is_specific_name(value: str) -> bool:
    """Clean and specific enough to become a reusable alias."""
    text = str(value or "").strip()
    return bool(text) and ";" not in text and not _is_generic_name(text)
