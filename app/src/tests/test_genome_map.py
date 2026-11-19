"""Data behind the genome map (ui/genome_map.py): how a record lines up with the
reference, which genes are flagged, and the payloads the component draws."""
from pathlib import Path

from app.src.lifting.base import LiftedFeature
from ui import genome_map
from ui.genome_map import (
    CELL_CODES,
    NO_CELL,
    evidence_payload,
    is_much_shorter,
    matrix_payload,
    record_metric,
    record_placement,
    reference_payload,
    reference_strands,
    tracks_payload,
)


def lf(name, rs, re_, qs, qe, status="ok", strand="+", method="tblastn", **extra):
    return LiftedFeature(
        name=name, source_name=None, ref_start=rs, ref_end=re_, strand=strand,
        query_start=qs, query_end=qe, sequence="ATG" if qs else None,
        coverage=1.0 if qs else 0.0, status=status, method=method, **extra,
    )


REF_FEATURES = [
    {"name": "B", "raw_name": "gene b", "start": 501, "end": 900, "strand": "+"},
    {"name": "A", "raw_name": "gene a", "start": 101, "end": 400, "strand": "+"},
]
REF = reference_payload("REF.1", 1000, REF_FEATURES, "CDS")


def test_reference_genes_are_in_genome_order_with_labels():
    ref = reference_payload("REF.1", 1000, REF_FEATURES, "mat_peptide", label_of={"A": "gene a"}.get)
    assert ref["genes"] == [["A", 101, 400, "+", "gene a"], ["B", 501, 900, "+", "B"]]
    assert ref["ftype"] == "mat_peptide"
    assert reference_strands(REF) == {"A": "+", "B": "+"}


def test_placement_of_a_collinear_record_is_the_median_shift():
    # The record lacks the first 100 bp of the genome: every gene sits 100 bp lower,
    # except B, which an insertion pushed 20 bp further; the median ignores it.
    features = [lf("A", 101, 400, 1, 300), lf("B", 501, 900, 381, 780), lf("C", 901, 950, 801, 850)]
    assert record_placement(features, {}, 900) == (100, False)


def test_placement_ignores_genes_that_failed():
    features = [
        lf("A", 101, 400, 101, 400),
        lf("B", 501, 900, 10, 300, status="invalid_boundaries"),
    ]
    assert record_placement(features, {"A": "+", "B": "+"}, 1000) == (0, False)


def test_placement_of_a_reverse_complement_record():
    # Worked example: a 1,000 bp record that is the reverse complement of the
    # reference carries A (ref 101-400, +) at 601-900 on the minus strand and
    # B (ref 501-900, +) at 101-500 on the minus strand. Mirrored, A starts at
    # 1000 - 900 + 1 = 101 and B at 1000 - 500 + 1 = 501: offset 0, flipped.
    features = [lf("A", 101, 400, 601, 900, strand="-"), lf("B", 501, 900, 101, 500, strand="-")]
    assert record_placement(features, {"A": "+", "B": "+"}, 1000) == (0, True)


def test_placement_without_located_genes():
    assert record_placement([lf("A", 101, 400, None, None, status="no_hit")], {"A": "+"}, 500) == (0, False)


def test_much_shorter_flags_a_passing_gene_cut_to_half():
    # PRRSV LQ249403.1 ORF1a: ok_rescued at 3,159-6,965 against a 7,512 nt reference gene.
    orf1a = lf("ORF1a", 191, 7702, 3159, 6965, status="ok_rescued")
    assert is_much_shorter(orf1a)
    assert not is_much_shorter(lf("ORF1a", 191, 7702, 191, 7702))
    assert not is_much_shorter(lf("ORF1a", 191, 7702, 3159, 6965, status="invalid_boundaries"))
    assert not is_much_shorter(lf("ORF5a", None, None, 13778, 13933, status="not_in_reference", method="direct"))


def test_matrix_rows_are_compact():
    features = [
        lf("A", 101, 400, 101, 400, identity=97.25),
        lf("B", 501, 900, None, None, status="not_in_sequence"),
        lf("3B1", None, None, 950, 990, status="not_in_reference", method="direct"),
    ]
    payload = matrix_payload(REF, [("Q.1", features, "partial")], {"partial": ("Partial", "info")}, selected="Q.1")
    assert payload["columns"] == ["A", "B"]
    statuses = [row[0] for row in payload["statuses"]]
    record_id, health, codes, extras, passed, total = payload["rows"][0]
    assert (record_id, health) == ("Q.1", "partial")
    # One character per gene: the status's index in the payload's status table.
    assert [statuses[CELL_CODES.index(code)] for code in codes] == ["ok", "not_in_sequence"]
    assert extras == [["3B1", statuses.index("not_in_reference")]]
    # A gene outside the record is neither passed nor counted.
    assert (passed, total) == (1, 1)
    assert payload["health"] == {"partial": ["Partial", "info"]}


def test_matrix_sends_every_record_and_marks_short_and_missing_genes():
    rows = [(f"Q.{i}", [lf("A", 101, 400, 101, 400)], "passed") for i in range(9000)]
    rows.append(("CUT", [lf("A", 101, 400, 101, 200, status="ok_rescued")], "passed"))
    payload = matrix_payload(REF, rows, {})
    assert len(payload["rows"]) == 9001
    assert payload["rows"][0][2].endswith(NO_CELL)  # no row for B
    assert len(payload["rows"][0]) == 6  # no short genes: no seventh item
    assert payload["rows"][-1][6] == [0]  # A is a third of its reference gene


def test_records_sort_by_their_lowest_value_or_one_gene():
    weak_b = [lf("A", 101, 400, 101, 400, identity=99.0), lf("B", 501, 900, 501, 900, identity=40.0)]
    weak_a = [lf("A", 101, 400, 101, 400, identity=60.0), lf("B", 501, 900, 501, 900, identity=95.0)]
    assert record_metric(weak_b, "identity") == 40.0
    assert record_metric(weak_b, "identity", gene="A") == 99.0
    assert record_metric(weak_a, "identity", gene="A") == 60.0
    assert record_metric(weak_a, "length", gene="B") == 1.0
    assert record_metric([lf("A", 101, 400, None, None, status="no_hit")], "coverage") is None
    assert record_metric(weak_b, "identity", gene="C") is None


def test_tracks_keep_the_raw_hit_only_when_rescue_moved_it():
    moved = lf("A", 101, 400, 101, 250, status="ok_rescued", raw_start=101, raw_end=398, rescue_action="stop +72 bp")
    kept = lf("B", 501, 900, 501, 900, raw_start=501, raw_end=880)
    payload = tracks_payload(REF, "Q.1", 1000, [moved, kept], selected="A")
    rows = {row[0]: row for row in payload["record"]["features"]}
    assert rows["A"][11:15] == [101, 398, "stop +72 bp", 1]
    assert rows["B"][11:13] == [None, None]
    assert payload["record"]["offset"] == 0 and payload["record"]["flipped"] is False
    assert payload["selected"] == "A"


def test_evidence_draws_only_the_genes_placed_on_the_record():
    lifted = [lf("ORF4", 13242, 13778, 13241, 13777), lf("ORF5", 13789, 14391, 13788, 14390), lf("ORF7", 14890, 15261, None, None, status="no_hit")]
    payload = evidence_payload("MT746146.1", 15411, lifted, 13778, 13933, "ORF5a", ["ORF5"])
    assert payload["genes"] == [["ORF4", 13241, 13777, "+"], ["ORF5", 13788, 14390, "+"]]
    assert payload["span"] == [13778, 13933, "ORF5a"]
    assert payload["highlight"] == ["ORF5"]


def test_component_assets_ship_with_the_ui():
    js = (Path(genome_map.__file__).parent / "genome_map.js").read_text(encoding="utf-8")
    assert "export default function" in js
    for view in ("matrix", "tracks", "reference", "picker", "evidence"):
        assert f'"{view}"' in js
    for event in ('"select"', '"focus"', '"pick"'):
        assert event in js
    assert (Path(genome_map.__file__).parent / "genome_map.css").exists()


def test_matrix_rows_scroll_under_a_sticky_header():
    # Thousands of records must not push the record map far down the page.
    css = (Path(genome_map.__file__).parent / "genome_map.css").read_text(encoding="utf-8")
    js = (Path(genome_map.__file__).parent / "genome_map.js").read_text(encoding="utf-8")
    matrix = css.split(".gm-matrix {", 1)[1].split("}", 1)[0]
    header = css.split(".gm-mhead {", 1)[1].split("}", 1)[0]
    assert "max-height" in matrix and "overflow: auto" in matrix
    assert "position: sticky" in header and "top: 0" in header
    assert 'class="gm-mhead"' in js and 'class="gm-mrows"' in js
