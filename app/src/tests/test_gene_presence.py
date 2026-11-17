"""Worked examples for ui/gene_presence.py: which `no_hit` genes are outside a
partial record and which are real misses.

Reference coordinates are FMDV FJ175661 (8,287 bp, 12 mat_peptides). The
records mirror real ones from an NCBI FMDV download: AJ294911.1 (VP1 only),
PV658500.1 (capsid region) and PP066264.1 (garbled, 2A really missing).
"""
from app.src.lifting.base import LiftedFeature
from ui.gene_presence import missing_genes_outside_record, nothing_located

FMDV_REF = {
    "Lpro": (1184, 1786), "VP4": (1787, 2041), "VP2": (2042, 2695), "VP3": (2696, 3355),
    "VP1": (3356, 3988), "2A": (3989, 4042), "2B": (4043, 4504), "2C": (4505, 5458),
    "3A": (5459, 5917), "3B": (5918, 6130), "3Cpro": (6131, 6769), "3Dpol": (6770, 8179),
}


def _record(located, strand="+"):
    """All 12 FMDV genes; `located` maps gene -> (query_start, query_end, status)."""
    features = []
    for name, (ref_start, ref_end) in FMDV_REF.items():
        q_start, q_end, status = located.get(name, (None, None, "no_hit"))
        features.append(LiftedFeature(
            name=name, source_name=None, ref_start=ref_start, ref_end=ref_end,
            strand=strand if q_start is not None else "+",
            query_start=q_start, query_end=q_end, sequence=None,
            coverage=1.0 if q_start is not None else 0.0, status=status, method="tblastn",
        ))
    return features


def _outside_names(features, record_length):
    return {features[i].name for i in missing_genes_outside_record(features, record_length)}


def test_vp1_only_record_has_every_other_gene_outside():
    # AJ294911.1, 639 bp: VP1 at 1-633, so q = r - 3355.
    # VP3 3355 -> 0 (before the record); 2A 3989-4042 -> 634-687, only 6 of 54 bp inside.
    features = _record({"VP1": (1, 633, "ok")})
    assert _outside_names(features, 639) == set(FMDV_REF) - {"VP1"}


def test_capsid_record_places_genes_from_truncated_ends():
    # PV658500.1, 2,202 bp: the record starts inside Lpro (found at 1-105) and ends
    # inside VP1 (1675-2202). Both truncated genes are placed by their intact edge:
    # Lpro end 1786 -> 105 and VP1 start 3356 -> 1675 both give q = r - 1681,
    # so 2A lands at 2308-2361, past the record end.
    features = _record({
        "Lpro": (1, 105, "low_coverage"), "VP4": (106, 360, "ok"), "VP2": (361, 1014, "ok"),
        "VP3": (1015, 1674, "ok"), "VP1": (1675, 2202, "ok"),
    })
    assert _outside_names(features, 2202) == {"2A", "2B", "2C", "3A", "3B", "3Cpro", "3Dpol"}


def test_gene_expected_inside_the_record_stays_a_real_miss():
    # PP066264.1, 1,227 bp: VP1 at 391-904 puts 2A at 1024-1077 (q = r - 2965),
    # well inside the record, yet tblastn found nothing: keep it for review.
    features = _record({"VP3": (13, 390, "ok"), "VP1": (391, 904, "ok")})
    outside = _outside_names(features, 1227)
    assert "2A" not in outside
    assert {"Lpro", "VP4", "VP2", "3Dpol"} <= outside


def test_reverse_complemented_record():
    # VP1 found on the minus strand at 500-1132 of a 2,000 bp record: q = 4488 - r.
    # VP3 (2696-3355) -> 1133-1792, inside: a real miss. Lpro -> 2702-3304 and
    # 3Dpol -> negative, both outside.
    features = _record({"VP1": (500, 1132, "ok")}, strand="-")
    outside = _outside_names(features, 2000)
    assert {"VP3", "2A"}.isdisjoint(outside)
    assert {"Lpro", "3Dpol"} <= outside


def test_disagreeing_genes_leave_every_miss_for_review():
    # VP3 and VP1 are adjacent on the reference but 4,000 bp apart here: the
    # record is rearranged or garbled, so nothing is reclassified.
    features = _record({"VP3": (1, 660, "ok"), "VP1": (4661, 5293, "ok")})
    assert _outside_names(features, 6000) == set()


def test_record_with_nothing_located():
    features = _record({})
    assert missing_genes_outside_record(features, 500) == []
    assert nothing_located(features)
    assert not nothing_located(_record({"VP1": (1, 633, "ok")}))
