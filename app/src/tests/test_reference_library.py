"""Saved references (ui/reference_library.py): save, suggest, forget, and
detect a query's virus from its first records. Everything runs in tmp_path."""
import io
from pathlib import Path

from Bio import SeqIO
from Bio.Seq import Seq
from Bio.SeqRecord import SeqRecord

from ui.reference_library import (
    detect_virus,
    detect_virus_in_bytes,
    list_references,
    mark_used,
    reference_file,
    remove_reference,
    save_reference,
    suggest_reference,
)
from ui.state import REGISTRY_PATH


def _record(record_id: str, organism: str) -> SeqRecord:
    record = SeqRecord(Seq("ATG" * 30), id=record_id, name=record_id.split(".")[0], description=f"{organism} complete genome")
    record.annotations.update(organism=organism, molecule_type="RNA")
    return record


def _genbank(records) -> str:
    handle = io.StringIO()
    SeqIO.write(records, handle, "genbank")
    return handle.getvalue()


def _source(tmp_path: Path, record: SeqRecord) -> Path:
    path = tmp_path / "upload" / f"{record.id}.gb"
    path.parent.mkdir(exist_ok=True)
    path.write_text(_genbank([record]))
    return path


def test_save_list_and_forget(tmp_path):
    library = tmp_path / "references"
    fmdv = _record("FJ175661.1", "Foot-and-mouth disease virus O")
    entry = save_reference(_source(tmp_path, fmdv), fmdv, "FMDV", "mat_peptide", 12, library)

    assert entry["virus_name"] == "FMDV" and entry["genes"] == 12 and entry["length"] == 90
    assert reference_file(entry, library).read_text() == _genbank([fmdv])
    assert [e["id"] for e in list_references(library)] == ["FJ175661.1"]

    # Saving the same accession again refreshes the entry instead of duplicating it.
    save_reference(_source(tmp_path, fmdv), fmdv, "FMDV", "mat_peptide", 12, library)
    assert len(list_references(library)) == 1

    remove_reference("FJ175661.1", library)
    assert list_references(library) == []
    assert not (library / "FJ175661.1.gb").exists()


def test_suggests_the_most_recently_used_reference_for_the_virus(tmp_path):
    library = tmp_path / "references"
    for record_id, organism, virus in (
        ("FJ175661.1", "Foot-and-mouth disease virus O", "FMDV"),
        ("AY593829.1", "Foot-and-mouth disease virus A", "FMDV"),
        ("PQ623173.1", "Porcine reproductive and respiratory syndrome virus", "PRRSV"),
    ):
        record = _record(record_id, organism)
        save_reference(_source(tmp_path, record), record, virus, "CDS", 10, library)
    entries = list_references(library)

    assert suggest_reference("PRRSV", entries)["id"] == "PQ623173.1"
    assert suggest_reference("Unknown virus", entries) is None
    assert suggest_reference(None, entries) is None

    mark_used("FJ175661.1", library)
    assert suggest_reference("FMDV", list_references(library))["id"] == "FJ175661.1"


def test_detects_the_query_virus_from_its_first_records():
    fmdv = [_record(f"AJ2949{n:02d}.1", "Foot-and-mouth disease virus O") for n in range(4)]
    other = _record("XX000001.1", "Some unrelated virus")

    assert detect_virus(io.StringIO(_genbank(fmdv + [other])), REGISTRY_PATH) == ("FMDV", 4, 5)
    assert detect_virus(io.StringIO(_genbank([other] * 3 + fmdv[:1])), REGISTRY_PATH) is None
    assert detect_virus(io.StringIO("not a genbank file"), REGISTRY_PATH) is None


def test_detection_survives_a_head_cut_mid_record():
    text = _genbank([_record(f"AJ2949{n:02d}.1", "Foot-and-mouth disease virus O") for n in range(3)])
    cut = text.encode()[: len(text) - 40]
    assert detect_virus_in_bytes(cut, REGISTRY_PATH)[0] == "FMDV"
