"""Review names logic (ui/name_review.py, services._scan_unknown_names).

Worked examples use FMDV: the reference genes lifted onto a 2,208 bp P1-region
record sit at VP4 1-255, VP2 256-909, VP3 910-1569 and VP1 1570-2208, and the
annotations are real NCBI ones (AF292107.1 "structural protein 1A".."1D",
PX621376.1 "capsid protein"/"P1", KM111570.1 "capsid protein"/"VP0").
"""
from Bio.Seq import Seq
from Bio.SeqFeature import FeatureLocation, SeqFeature
from Bio.SeqRecord import SeqRecord

from app.src.alias.gene_alias import normalize_text
from app.src.lifting.base import LiftedFeature
from ui.name_review import (
    classify_span,
    is_specific_name,
    llm_position_context,
    name_patterns,
    name_set,
    names_shared_elsewhere,
    plan_session_lookup,
    position_evidence,
    summarize_position,
)
from ui.services import _scan_unknown_names

LIFTED_P1 = {"VP4": (1, 255), "VP2": (256, 909), "VP3": (910, 1569), "VP1": (1570, 2208)}
REF_START = {"VP4": 1787, "VP2": 2042, "VP3": 2696, "VP1": 3356}


def _lifted(spans=LIFTED_P1):
    return [
        LiftedFeature(
            name=name, source_name=None, ref_start=REF_START[name], ref_end=REF_START[name] + end - start,
            strand="+", query_start=start, query_end=end, sequence=None, coverage=1.0,
            status="ok", method="tblastn",
        )
        for name, (start, end) in spans.items()
    ]


def _record(record_id, *features, length=2208):
    record = SeqRecord(Seq("A" * length), id=record_id)
    for start, end, qualifiers in features:
        record.features.append(SeqFeature(
            FeatureLocation(start - 1, end, strand=1), type="CDS",
            qualifiers={key: [value] for key, value in qualifiers.items()},
        ))
    return record


LOOKUP = {normalize_text(name): name for name in ("VP4", "VP2", "VP3", "VP1", "1A")}


# ── rows ──────────────────────────────────────────────────────────────────

def test_rows_are_one_per_exact_name_set():
    records = [
        _record("PX569380.1", (1, 2208, {"product": "P1", "note": "capsid protein"})),
        _record("PX621376.1", (1, 2208, {"product": "capsid protein", "note": "P1"})),
        _record("KM111570.1", (1, 861, {"product": "capsid protein", "note": "polyprotein; VP0 region"})),
        _record("MN000001.1", (1, 639, {"product": "capsid protein"})),
    ]
    rows = _scan_unknown_names(records, {}, excluded_names=set())

    # Same names in either order: one row. A shared name alone does not merge rows.
    assert rows["P1"]["records"] == ["PX569380.1", "PX621376.1"]
    assert rows["capsid protein"]["candidates"] == ["capsid protein", "polyprotein; VP0 region"]
    assert rows["capsid protein (2)"]["records"] == ["MN000001.1"]
    assert len(rows) == 3


# ── position verdicts ─────────────────────────────────────────────────────

def test_span_on_one_gene_is_a_match():
    assert classify_span(1, 255, _lifted()) == {"verdict": "match", "gene": "VP4", "iou": 1.0}


def test_span_over_several_genes_is_never_one_gene():
    # PX621376.1 "capsid protein" covers 1-2208: the P1 precursor, not VP1.
    assert classify_span(1, 2208, _lifted()) == {"verdict": "spans", "genes": ["VP4", "VP2", "VP3", "VP1"]}
    # KM111570.1 "VP0" at 1-861 covers VP4 and 606 of VP2's 654 bp.
    assert classify_span(1, 861, _lifted()) == {"verdict": "spans", "genes": ["VP4", "VP2"]}


def test_sub_part_partial_overlap_and_nothing():
    assert classify_span(300, 600, _lifted()) == {"verdict": "inside", "gene": "VP2"}
    # 1500-1700: 131 bp of VP1 and 70 bp of VP3, best IoU 131/709.
    assert classify_span(1500, 1700, _lifted()) == {"verdict": "overlaps", "gene": "VP1", "iou": 0.18}
    assert classify_span(1, 255, []) == {"verdict": "none"}


def test_a_row_is_decided_only_when_every_record_agrees():
    match = {"verdict": "match", "gene": "VP4", "iou": 0.99, "record": "A", "start": 1, "end": 255}
    summary = summarize_position([match, {**match, "record": "B", "iou": 0.97}])
    assert (summary["verdict"], summary["gene"], summary["agree"], summary["iou"]) == ("match", "VP4", 2, 0.97)
    mixed = summarize_position([match, {"verdict": "spans", "genes": ["VP4", "VP2"]}])
    assert (mixed["verdict"], mixed["checked"], mixed["agree"]) == ("mixed", 2, 1)
    assert summarize_position([])["verdict"] == "unplaced"


def test_position_evidence_lifts_each_record_once():
    record = _record(
        "AF292107.1",
        (1, 255, {"product": "structural protein 1A"}),
        (256, 909, {"product": "structural protein 1B"}),
    )
    rows = _scan_unknown_names([record], {}, excluded_names=set())
    lifted_records = []

    def lift(rec):
        lifted_records.append(rec.id)
        return _lifted()

    evidence = position_evidence(rows, {record.id: record}, {}, set(), lift)
    assert lifted_records == ["AF292107.1"]
    assert evidence["structural protein 1A"]["gene"] == "VP4"
    assert evidence["structural protein 1B"]["gene"] == "VP2"
    context = llm_position_context(evidence["structural protein 1A"])
    assert context["coordinate_verdict"] == "match"
    assert context["ref_slot_by_position"] == "VP4"
    assert (context["start"], context["end"]) == (1, 255)
    spans = llm_position_context({"verdict": "spans", "genes": ["VP4", "VP2"], "checked": 1, "agree": 1,
                                  "start": 1, "end": 861, "record_length": 861})
    assert spans["spans_reference_genes"] == ["VP4", "VP2"] and "ref_slot_by_position" not in spans


# ── applying decisions ────────────────────────────────────────────────────

def _fmdv_review():
    records = [
        _record("A", (1, 639, {"product": "capsid protein", "note": "VP1"})),   # already VP1
        _record("B", (1, 2208, {"product": "capsid protein", "note": "P1"})),   # P1 precursor
        _record("C", (1, 861, {"product": "capsid protein", "note": "VP0"})),
        _record("D", (1, 639, {"product": "capsid protein"})),
        _record("E", (1, 255, {"product": "structural protein 1A"})),
    ]
    rows = _scan_unknown_names(records, LOOKUP, excluded_names=set())
    patterns = name_patterns(records, LOOKUP, set())
    return records, rows, patterns


def test_decisions_apply_only_to_their_own_name_set():
    _, rows, patterns = _fmdv_review()
    decisions = {
        "capsid protein": None,                      # B: P1 precursor, keep raw
        "capsid protein · VP0": "VP0",               # C
        "capsid protein (2)": "VP1",                 # D: wants VP1 by its only name
        "structural protein 1A": "VP4",              # E
    }
    assert set(decisions) == set(rows)
    mappings, blocked = plan_session_lookup(rows, decisions, patterns, LOOKUP)

    # Mapping "capsid protein" -> VP1 would turn B's P1 precursor into VP1, so it
    # is withheld; D can only be named through that shared word and is reported.
    assert "capsid protein" not in mappings
    assert mappings == {"VP0": "VP0", "structural protein 1A": "VP4"}
    assert blocked == ["capsid protein (2)"]


def test_shared_names_are_flagged_for_saving():
    _, rows, patterns = _fmdv_review()
    decisions = {"capsid protein": None, "capsid protein · VP0": "VP0",
                 "capsid protein (2)": "VP1", "structural protein 1A": "VP4"}
    shared = names_shared_elsewhere(rows, decisions, patterns, LOOKUP)
    assert shared["capsid protein · VP0"] == {"capsid protein"}
    assert shared["structural protein 1A"] == set()


def test_specific_names():
    assert is_specific_name("structural protein 1A")
    assert not is_specific_name("structural protein")
    assert not is_specific_name("polyprotein")
    assert not is_specific_name("ORF6; M")
    assert name_set(["P1", "capsid protein"]) == name_set(["capsid protein", "P1"])

