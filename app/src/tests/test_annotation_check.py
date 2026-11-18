"""Checking annotated genes against the reference protein
(app/src/lifting/annotation_check.py, PipelineConfig.check_annotations).

A synthetic two-peptide genome stands in for a polyprotein: A at 1-300 and B
at 301-600, 100 codons each. The cases mirror real records from NCBI
downloads: S72510.1 (a VP1 fragment at a record end), PV492667.1 ("VP1" over
1,032 nt), AF331831.1 (PRRSV ORF5 annotated under a name that maps to ORF2b)
and PV533621.1 (a PEDV ORF3 truncated by a deletion, where tblastn reports
the same span).
"""
import random
import shutil
from dataclasses import replace

import pytest
from Bio.Seq import Seq
from Bio.SeqFeature import FeatureLocation, SeqFeature
from Bio.SeqRecord import SeqRecord

from app.src.io.genbank_parser import parse_mat_peptides
from app.src.lifting.annotation_check import check_annotations, reference_proteins, worth_searching
from app.src.lifting.base import LiftedFeature
from app.src.pipeline import PipelineConfig, run_pipeline


def _coding(codons: int, seed: int) -> str:
    rng = random.Random(seed)
    sense = [a + b + c for a in "ACGT" for b in "ACGT" for c in "ACGT" if a + b + c not in ("TAA", "TAG", "TGA")]
    return "".join(rng.choice(sense) for _ in range(codons))


GENOME = _coding(200, seed=7)
REF_FEATURES = [
    {"name": "A", "start": 1, "end": 300, "strand": "+"},
    {"name": "B", "start": 301, "end": 600, "strand": "+"},
]
PROTEINS = reference_proteins(REF_FEATURES, lambda f: str(Seq(GENOME[f["start"] - 1:f["end"]]).translate()))


def _annotated(name, start, end, sequence=GENOME):
    ref = next(r for r in REF_FEATURES if r["name"] == name)
    return LiftedFeature(
        name=name, source_name=f"{name} protein", ref_start=ref["start"], ref_end=ref["end"], strand="+",
        query_start=start, query_end=end, sequence=sequence[start - 1:end], coverage=1.0,
        status="ok", method="direct",
    )


class FakeLift:
    """Stands in for the tblastn lift: one row per reference gene, in order."""

    def __init__(self, a=(1, 300, "ok")):
        self.calls = 0
        start, end, status = a
        self.rows = [
            LiftedFeature(
                name="A", source_name=None, ref_start=1, ref_end=300, strand="+", query_start=start,
                query_end=end, sequence=GENOME[start - 1:end], coverage=1.0, status=status, method="tblastn",
            ),
            LiftedFeature(
                name="B", source_name=None, ref_start=301, ref_end=600, strand="+", query_start=301,
                query_end=600, sequence=GENOME[300:600], coverage=1.0, status="ok", method="tblastn",
            ),
        ]

    def __call__(self):
        self.calls += 1
        return self.rows


def _check(features, lift, record_length=600):
    return check_annotations(features, REF_FEATURES, PROTEINS, lift, 0.5, 0.3, record_length)


def test_matching_annotation_is_confirmed_with_real_numbers():
    lift = FakeLift()
    [row] = _check([_annotated("A", 1, 300)], lift)
    assert (row.status, row.annotation_check, row.coverage, row.identity) == ("ok", "confirmed", 1.0, 100.0)
    assert lift.calls == 0


def test_fragment_at_a_record_end_is_kept_without_searching():
    # Like S72510.1: the record ends inside the gene, so tblastn cannot find more.
    record = GENOME[:90]
    lift = FakeLift()
    [row] = _check([_annotated("A", 1, 90, record)], lift, record_length=90)
    assert (row.status, row.annotation_check, row.method) == ("low_coverage", "partial", "direct")
    assert row.coverage == pytest.approx(0.3, abs=0.01)
    assert lift.calls == 0


def test_partial_annotation_in_a_longer_record_is_replaced_by_tblastn():
    # The record holds all of A but the annotation names only its first 30 codons.
    lift = FakeLift()
    [row] = _check([_annotated("A", 1, 90)], lift)
    assert lift.calls == 1
    assert (row.method, row.status, row.query_start, row.query_end) == ("tblastn", "ok", 1, 300)
    assert row.annotation_check == "partial" and row.source_name == "A protein"
    assert (row.annotation.query_start, row.annotation.query_end, row.annotation.status) == (1, 90, "low_coverage")


def test_overlong_annotation_is_replaced_by_tblastn():
    # Like PV492667.1: "A" annotated over A and B.
    lift = FakeLift()
    [row] = _check([_annotated("A", 1, 600)], lift)
    assert row.annotation.status == "overlong_annotation" and row.annotation_check == "overlong"
    assert (row.method, row.query_start, row.query_end) == ("tblastn", 1, 300)


def test_wrong_name_is_flagged_with_the_gene_it_matches():
    # Like AF331831.1: B's name on A's sequence. tblastn places B elsewhere.
    lift = FakeLift()
    annotated = replace(_annotated("B", 1, 300), sequence=GENOME[:300])
    [row] = _check([annotated], lift)
    assert row.annotation.best_match == "A" and row.best_match == "A"
    assert (row.method, row.query_start, row.query_end) == ("tblastn", 301, 600)


def test_same_span_or_failing_tblastn_keeps_the_annotation():
    # Like PV533621.1: tblastn reports the annotation's own span; nothing to gain.
    same = FakeLift(a=(1, 90, "ok_rescued"))
    [row] = _check([_annotated("A", 1, 90)], same)
    assert (row.method, row.status) == ("direct", "low_coverage")

    failing = FakeLift(a=(1, 150, "low_coverage"))
    [row] = _check([_annotated("A", 1, 90)], failing)
    assert (row.method, row.status) == ("direct", "low_coverage")


def test_only_resolved_annotated_genes_are_checked():
    unresolved = replace(_annotated("A", 1, 300), name="p1 protein", ref_start=None, ref_end=None, status="unresolved_name")
    lifted = replace(_annotated("A", 1, 300), method="tblastn")
    rows = _check([unresolved, lifted], FakeLift())
    assert rows == [unresolved, lifted]


def test_room_to_extend_follows_the_strand():
    row = replace(_annotated("A", 1, 90), annotation_check="partial", strand="-")

    class Match:
        ref_from, ref_to = 70, 100       # the gene's start is missing

    # On the minus strand the gene's start lies after the annotation's end.
    assert worth_searching(row, Match, 100, record_length=600)
    assert not worth_searching(row, Match, 100, record_length=92)


# ── through run_pipeline ──────────────────────────────────────────────────

def test_check_and_missing_genes_share_one_lift(monkeypatch):
    calls = []
    lifted = FakeLift().rows

    def fake_tblastn(**kwargs):
        calls.append(kwargs["query_record"].id)
        return lifted

    monkeypatch.setattr("app.src.pipeline.get_strategy", lambda *a, **k: ("direct", "mat_peptide"))
    monkeypatch.setattr("app.src.pipeline.direct_extract_with_alias", lambda **k: [_annotated("A", 1, 90)])
    monkeypatch.setattr("app.src.pipeline.process_one_query_record", fake_tblastn)
    monkeypatch.setattr("app.src.pipeline.translate_feature", lambda f, ref: PROTEINS[f["name"]])
    result = run_pipeline(
        ref_record=SeqRecord(Seq(GENOME), id="ref"),
        query_records=[SeqRecord(Seq(GENOME), id="query")],
        ref_features=REF_FEATURES,
        ref_feature_type="mat_peptide",
        alias_lookup={},
        config=PipelineConfig(check_annotations=True, lift_missing=True),
    )
    rows = result.all_results[0][1]
    assert calls == ["query"]
    assert [(r.name, r.method, r.query_start, r.query_end) for r in rows] == [("A", "tblastn", 1, 300), ("B", "tblastn", 301, 600)]
    assert (result.annotations_checked, result.annotations_replaced, result.missing_lifted_count) == (1, 1, 1)


def _polyprotein_record(record_id, peptides):
    record = SeqRecord(Seq(GENOME), id=record_id, annotations={"molecule_type": "RNA"})
    for name, (start, end) in peptides.items():
        record.features.append(SeqFeature(
            FeatureLocation(start, end, strand=1), type="mat_peptide", qualifiers={"product": [name]},
        ))
    return record


@pytest.mark.skipif(shutil.which("tblastn") is None, reason="BLAST+ (tblastn) not installed")
@pytest.mark.parametrize("check", [False, True])
def test_overlong_annotation_end_to_end(check):
    reference = _polyprotein_record("REF", {"A": (0, 300), "B": (300, 600)})
    query = _polyprotein_record("QUERY", {"A": (0, 600)})
    result = run_pipeline(
        ref_record=reference,
        query_records=[query],
        ref_features=parse_mat_peptides(reference),
        ref_feature_type="mat_peptide",
        alias_lookup={},
        config=PipelineConfig(check_annotations=check),
    )
    [row] = result.all_results[0][1]
    if not check:
        assert (row.method, row.status, row.query_end, row.coverage) == ("direct", "ok", 600, 1.0)
        return
    assert (row.method, row.status, row.query_start, row.query_end) == ("tblastn", "ok", 1, 300)
    assert (row.annotation.query_end, row.annotation.status) == (600, "overlong_annotation")


def test_tsv_gains_the_check_columns_only_when_it_ran(tmp_path):
    from app.src.io.result_writer import write_results_tsv

    plain = _annotated("A", 1, 300)
    [replaced] = _check([_annotated("A", 1, 600)], FakeLift())
    write_results_tsv([("query", [plain])], tmp_path / "plain.tsv")
    write_results_tsv([("query", [replaced])], tmp_path / "checked.tsv")
    plain_header = (tmp_path / "plain.tsv").read_text().splitlines()[0].split("\t")
    header, row = [line.split("\t") for line in (tmp_path / "checked.tsv").read_text().splitlines()]
    assert plain_header[-1] == "length" and "annotation_check" not in plain_header
    assert dict(zip(header, row))["annotation_check"] == "overlong"
    assert (dict(zip(header, row))["annotation_start"], dict(zip(header, row))["annotation_end"]) == ("1", "600")
