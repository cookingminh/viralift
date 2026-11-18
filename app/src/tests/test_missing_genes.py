"""Lifting the reference genes an annotated record does not name
(app/src/lifting/missing_genes.py, PipelineConfig.lift_missing).

Reference coordinates are FMDV FJ175661 (12 mat_peptides). The records mirror
real ones from an NCBI FMDV download: DQ478936.1 (complete genome annotated
only as L protease + p1/p2/p3), AJ294911.1 (VP1 only) and EU109774.1 (639 bp,
one "capsid protein" peptide the alias config does not know).
"""
import random
import shutil

import pytest
from Bio.Seq import Seq
from Bio.SeqFeature import FeatureLocation, SeqFeature
from Bio.SeqRecord import SeqRecord

from app.src.io.genbank_parser import parse_mat_peptides
from app.src.lifting.base import LiftedFeature
from app.src.lifting.missing_genes import add_missing_genes, missing_reference_indexes
from app.src.pipeline import PipelineConfig, run_pipeline

FMDV_REF = [
    {"name": name, "start": start, "end": end, "strand": "+"}
    for name, (start, end) in {
        "Lpro": (1184, 1786), "VP4": (1787, 2041), "VP2": (2042, 2695), "VP3": (2696, 3355),
        "VP1": (3356, 3988), "2A": (3989, 4042), "2B": (4043, 4504), "2C": (4505, 5458),
        "3A": (5459, 5917), "3B": (5918, 6130), "3Cpro": (6131, 6769), "3Dpol": (6770, 8179),
    }.items()
]
NAMES = [ref["name"] for ref in FMDV_REF]


def _direct(name, start, end, status="ok"):
    ref = next((r for r in FMDV_REF if r["name"] == name), None) if status == "ok" else None
    return LiftedFeature(
        name=name, source_name=None,
        ref_start=ref["start"] if ref else None, ref_end=ref["end"] if ref else None,
        strand="+", query_start=start, query_end=end, sequence="", coverage=1.0,
        status=status, method="direct",
    )


class FakeLift:
    """Stands in for a tblastn lift: one row per reference gene, in order."""

    def __init__(self):
        self.calls = 0
        self.rows = [
            LiftedFeature(
                name=ref["name"], source_name=None, ref_start=ref["start"], ref_end=ref["end"],
                strand="+", query_start=None, query_end=None, sequence=None, coverage=0.0,
                status="no_hit", method="tblastn",
            )
            for ref in FMDV_REF
        ]

    def __call__(self):
        self.calls += 1
        return self.rows


def test_fully_annotated_record_is_left_alone():
    direct = [_direct(name, 1, 3) for name in NAMES]
    lift = FakeLift()
    assert missing_reference_indexes(direct, FMDV_REF) == []
    assert add_missing_genes(direct, FMDV_REF, 8000, lift) == (direct, False)
    assert lift.calls == 0


def test_precursor_annotation_lifts_the_genes_it_hides():
    # DQ478936.1, 8,168 bp: L protease resolves to Lpro (1054-1656, so q = r - 130);
    # p1/p2/p3 are unresolved precursor names. Every other gene is expected inside
    # the record, so the record is lifted once and those genes' rows are added.
    direct = [
        _direct("Lpro", 1054, 1656),
        _direct("p1 protein", 1657, 3864, "unresolved_name"),
        _direct("p2 protein", 3865, 5328, "unresolved_name"),
        _direct("p3 protein", 5329, 8049, "unresolved_name"),
    ]
    lift = FakeLift()
    rows, lifted = add_missing_genes(direct, FMDV_REF, 8168, lift)

    assert lifted and lift.calls == 1
    assert rows[:4] == direct                       # annotated rows untouched, first
    assert rows[4:] == lift.rows[1:]                # VP4 .. 3Dpol, straight from the lift
    assert [r.name for r in rows[4:]] == NAMES[1:]


def test_genes_outside_a_partial_record_are_not_searched():
    # AJ294911.1, 639 bp: VP1 annotated at 1-633 (q = r - 3355). Every other gene
    # falls outside the record, so tblastn is not run; each still gets a row.
    direct = [_direct("VP1", 1, 633)]
    lift = FakeLift()
    rows, lifted = add_missing_genes(direct, FMDV_REF, 639, lift)

    assert not lifted and lift.calls == 0
    assert rows[0] is direct[0]
    assert [r.name for r in rows[1:]] == [n for n in NAMES if n != "VP1"]
    assert {(r.status, r.method, r.query_start) for r in rows[1:]} == {("no_hit", "direct", None)}
    assert (rows[1].ref_start, rows[1].ref_end) == (1184, 1786)


def test_record_with_no_resolved_gene_is_searched():
    # EU109774.1: the only peptide is an unknown "capsid protein", so nothing
    # places the record on the reference and every gene has to be searched.
    direct = [_direct("capsid protein", 76, 639, "unresolved_name")]
    lift = FakeLift()
    rows, lifted = add_missing_genes(direct, FMDV_REF, 639, lift)
    assert lifted and lift.calls == 1
    assert rows == direct + lift.rows


# ── through run_pipeline ──────────────────────────────────────────────────

def _pipeline(monkeypatch, lift_missing, lift_error=None):
    gene_a = LiftedFeature(
        name="A", source_name=None, ref_start=1, ref_end=9, strand="+", query_start=1, query_end=9,
        sequence="ATGAAATAA", coverage=1.0, status="ok", method="direct",
    )
    gene_b = LiftedFeature(
        name="B", source_name=None, ref_start=10, ref_end=18, strand="+", query_start=10, query_end=18,
        sequence="ATGAAATAA", coverage=1.0, status="ok", method="tblastn",
    )
    lifts = []

    def fake_tblastn(**kwargs):
        lifts.append(kwargs["query_record"].id)
        if lift_error:
            raise lift_error
        return [gene_a, gene_b]

    monkeypatch.setattr("app.src.pipeline.get_strategy", lambda *a, **k: ("direct", "mat_peptide"))
    monkeypatch.setattr("app.src.pipeline.direct_extract_with_alias", lambda **k: [gene_a])
    monkeypatch.setattr("app.src.pipeline.process_one_query_record", fake_tblastn)
    result = run_pipeline(
        ref_record=SeqRecord(Seq("A" * 30), id="ref"),
        query_records=[SeqRecord(Seq("A" * 30), id="query")],
        ref_features=[{"name": "A", "start": 1, "end": 9}, {"name": "B", "start": 10, "end": 18}],
        ref_feature_type="mat_peptide",
        alias_lookup={},
        config=PipelineConfig(lift_missing=lift_missing, catch_record_errors=lift_error is not None),
    )
    return result, lifts, gene_a, gene_b


def test_pipeline_leaves_annotated_records_alone_by_default(monkeypatch):
    result, lifts, gene_a, _ = _pipeline(monkeypatch, lift_missing=False)
    assert result.all_results == [("query", [gene_a])]
    assert lifts == [] and result.missing_lifted_count == 0


def test_pipeline_lifts_missing_genes_when_asked(monkeypatch):
    result, lifts, gene_a, gene_b = _pipeline(monkeypatch, lift_missing=True)
    assert result.all_results == [("query", [gene_a, gene_b])]
    assert lifts == ["query"]
    assert (result.direct_count, result.lifted_count, result.missing_lifted_count) == (1, 0, 1)
    assert result.summary["ok"] == 2


def test_failed_missing_gene_lift_keeps_the_annotated_genes(monkeypatch):
    result, _, gene_a, _ = _pipeline(monkeypatch, lift_missing=True, lift_error=RuntimeError("tblastn crashed"))
    assert result.all_results == [("query", [gene_a])]
    assert result.errors == [{"record_id": "query", "error": "tblastn crashed"}]


# ── end to end with BLAST+ ────────────────────────────────────────────────

def _coding_sequence(codons: int, seed: int) -> str:
    rng = random.Random(seed)
    sense = [a + b + c for a in "ACGT" for b in "ACGT" for c in "ACGT" if a + b + c not in ("TAA", "TAG", "TGA")]
    return "".join(rng.choice(sense) for _ in range(codons))


def _polyprotein_record(record_id, peptides):
    """A 600 bp genome with two contiguous 100-aa mat_peptides, A (1-300) and
    B (301-600); `peptides` names the ones this record annotates."""
    record = SeqRecord(Seq(_coding_sequence(200, seed=7)), id=record_id, annotations={"molecule_type": "RNA"})
    for name, (start, end) in {"A": (0, 300), "B": (300, 600)}.items():
        if name in peptides:
            record.features.append(SeqFeature(
                FeatureLocation(start, end, strand=1), type="mat_peptide", qualifiers={"product": [name]},
            ))
    return record


@pytest.mark.skipif(shutil.which("tblastn") is None, reason="BLAST+ (tblastn) not installed")
@pytest.mark.parametrize("lift_missing", [False, True])
def test_unannotated_peptide_is_lifted_end_to_end(lift_missing):
    reference = _polyprotein_record("REF", {"A", "B"})
    query = _polyprotein_record("QUERY", {"A"})
    result = run_pipeline(
        ref_record=reference,
        query_records=[query],
        ref_features=parse_mat_peptides(reference),
        ref_feature_type="mat_peptide",
        alias_lookup={},
        config=PipelineConfig(lift_missing=lift_missing),
    )
    rows = {f.name: f for f in result.all_results[0][1]}
    assert (rows["A"].method, rows["A"].query_start, rows["A"].query_end) == ("direct", 1, 300)
    if not lift_missing:
        assert set(rows) == {"A"}
        return
    assert (rows["B"].method, rows["B"].status) == ("tblastn", "ok")
    assert (rows["B"].query_start, rows["B"].query_end) == (301, 600)
