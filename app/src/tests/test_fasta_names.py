"""FASTA sequence names (ui/fasta_names.py).

The records mirror real FMDV entries: AJ294911.1 (isolate O/HKN/21/70, host
porcine, Hong Kong) and S72510.1, whose source feature names no isolate,
host or country.
"""
import json

from Bio.Seq import Seq
from Bio.SeqFeature import FeatureLocation, SeqFeature
from Bio.SeqRecord import SeqRecord

from app.src.lifting.base import LiftedFeature
from ui.fasta_names import (
    PRESETS,
    build_header,
    load_settings,
    make_unique,
    record_metadata,
    save_settings,
    valid_settings,
)


def _record(record_id, **source):
    record = SeqRecord(Seq("A" * 639), id=record_id)
    record.features.append(SeqFeature(
        FeatureLocation(0, 639, strand=1), type="source",
        qualifiers={"organism": ["Foot-and-mouth disease virus O"], **{k: [v] for k, v in source.items()}},
    ))
    return record


AJ294911 = _record("AJ294911.1", isolate="O/HKN/21/70", host="porcine", geo_loc_name="Hong Kong")
S72510 = _record("S72510.1")
VP1 = LiftedFeature(
    name="VP1", source_name="VP1", ref_start=3356, ref_end=3988, strand="+", query_start=1, query_end=639,
    sequence="A" * 639, coverage=1.0, status="ok", method="direct",
)


def _header(preset_or_fields, record, separator=None, missing="NA"):
    preset = PRESETS.get(preset_or_fields) if isinstance(preset_or_fields, str) else None
    fields = preset["fields"] if preset else preset_or_fields
    separator = separator or (preset["separator"] if preset else "_")
    return build_header(fields, separator, missing, record_metadata(record), "VP1", VP1)


def test_default_name_is_unchanged():
    assert _header("default", AJ294911) == "AJ294911.1|VP1|1|639|+"


def test_accession_isolate_host_as_the_lab_asked():
    assert _header("accession_isolate_host", AJ294911) == "AJ294911.1_O/HKN/21/70_porcine"


def test_missing_metadata_is_na_or_left_out():
    assert _header("accession_isolate_host", S72510) == "S72510.1_NA_NA"
    assert _header("accession_isolate_host", S72510, missing="skip") == "S72510.1"


def test_spaces_become_underscores_and_strain_stands_in_for_isolate():
    assert _header(["accession", "country"], AJ294911) == "AJ294911.1_Hong_Kong"
    strain_only = _record("AF308157.1", strain="O1 Manisa")
    assert _header(["accession", "isolate"], strain_only) == "AF308157.1_O1_Manisa"


def test_characters_that_break_tree_files_are_replaced():
    # Real values: JQ041374.1's host and a geo_loc_name with a region.
    nilgai = _record("JQ041374.1", host="Boselaphus tragocamelus (nilgai)", geo_loc_name="Viet Nam: Hanoi")
    assert _header(["accession", "host", "country"], nilgai) == "JQ041374.1_Boselaphus_tragocamelus_nilgai_Viet_Nam_Hanoi"


def test_repeated_names_get_a_suffix():
    assert make_unique(["A_VP1", "A_VP1", "B_VP1", "A_VP1"]) == ["A_VP1", "A_VP1_2", "B_VP1", "A_VP1_3"]
    assert make_unique(["A", "A"], separator="|") == ["A", "A|2"]


def test_settings_survive_a_restart_and_bad_values_fall_back(tmp_path):
    path = tmp_path / "export_settings.json"
    assert load_settings(path) == PRESETS["default"]          # no file yet

    save_settings({"fields": ["accession", "isolate", "host"], "separator": "_", "missing": "skip"}, path)
    assert load_settings(path) == {"fields": ["accession", "isolate", "host"], "separator": "_", "missing": "skip"}

    path.write_text(json.dumps({"fasta_header": {"fields": ["accession", "bogus"], "separator": ";"}}))
    assert load_settings(path) == {"fields": ["accession"], "separator": "|", "missing": "NA"}
    assert valid_settings({"fields": []}) == PRESETS["default"]

    path.write_text("not json")
    assert load_settings(path) == PRESETS["default"]
