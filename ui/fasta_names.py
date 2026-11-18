# Sequence names (FASTA headers) for the Results export.
#
# The default header is ">AJ294911.1|VP1|1|639|+". Labs often want the
# record's metadata in the name instead, e.g. ">AJ294911.1_O/HKN/21/70_porcine"
# (accession, isolate, host), so the header is built from a chosen list of
# fields. Metadata comes from the record's `source` feature. The last choice is
# saved in app/config (volume-mounted in Docker), so it is set once per lab.
import json
import re
from typing import Dict, Iterable, List, Optional, Sequence

from Bio.SeqRecord import SeqRecord

from app.src.lifting.base import LiftedFeature
from ui.state import CONFIG_DIR

SETTINGS_FILE = CONFIG_DIR / "export_settings.json"

# field key -> label shown in the picker
FIELDS = {
    "accession": "Accession",
    "isolate": "Isolate",
    "host": "Host",
    "country": "Country",
    "collection_date": "Collection date",
    "serotype": "Serotype",
    "gene": "Gene",
    "start": "Start",
    "end": "End",
    "strand": "Strand",
}
PRESETS = {
    "default": {"fields": ["accession", "gene", "start", "end", "strand"], "separator": "|", "missing": "NA"},
    "accession_isolate_host": {"fields": ["accession", "isolate", "host"], "separator": "_", "missing": "NA"},
}
SEPARATORS = ("_", "|")
MISSING = ("NA", "skip")
DEFAULT_SETTINGS = PRESETS["default"]


def _source_value(record: SeqRecord, *keys: str) -> str:
    source = next((f for f in record.features if f.type == "source"), None)
    if source is None:
        return ""
    for key in keys:
        values = source.qualifiers.get(key)
        if values and str(values[0]).strip():
            return str(values[0]).strip()
    return ""


def record_metadata(record: SeqRecord) -> Dict[str, str]:
    """The record-level fields a header can use. Isolate falls back to strain
    (766 of 8,553 FMDV records name a strain instead), country to the older
    /country qualifier."""
    return {
        "accession": record.id,
        "isolate": _source_value(record, "isolate", "strain"),
        "host": _source_value(record, "host"),
        "country": _source_value(record, "geo_loc_name", "country"),
        "collection_date": _source_value(record, "collection_date"),
        "serotype": _source_value(record, "serotype"),
    }


# Whitespace ends the name in most tools ("Hong Kong" -> "Hong_Kong"), and
# brackets, commas, colons, semicolons and quotes break Newick tree files,
# e.g. host "Boselaphus tragocamelus (nilgai)".
_UNSAFE = re.compile(r"[\s()\[\],;:'\"]+")


def clean(value: str) -> str:
    """One header token, safe for alignment and tree tools. '/' and '-' are
    kept, as in isolate names like O/HKN/21/70."""
    token = _UNSAFE.sub("_", str(value).replace(">", ""))
    return re.sub(r"_{2,}", "_", token).strip("_")


def build_header(
    fields: Sequence[str],
    separator: str,
    missing: str,
    metadata: Dict[str, str],
    gene: str,
    feature: LiftedFeature,
) -> str:
    """The header text, without the leading '>'."""
    values = {
        **metadata,
        "gene": gene,
        "start": "" if feature.query_start is None else str(feature.query_start),
        "end": "" if feature.query_end is None else str(feature.query_end),
        "strand": feature.strand or "",
    }
    parts = []
    for field in fields:
        value = clean(values.get(field, ""))
        if value:
            parts.append(value)
        elif missing == "NA":
            parts.append("NA")
    return separator.join(parts) or clean(metadata.get("accession", "")) or "sequence"


def make_unique(headers: Iterable[str], separator: str = "_") -> List[str]:
    """Suffix repeated headers with _2, _3 … so every name in a file is unique."""
    seen: Dict[str, int] = {}
    unique = []
    for header in headers:
        seen[header] = seen.get(header, 0) + 1
        unique.append(header if seen[header] == 1 else f"{header}{separator}{seen[header]}")
    return unique


def valid_settings(settings: Optional[Dict]) -> Dict:
    """Settings with unknown fields dropped and bad values replaced by the default."""
    settings = settings if isinstance(settings, dict) else {}
    fields = [f for f in settings.get("fields", []) if f in FIELDS] if isinstance(settings.get("fields"), list) else []
    return {
        "fields": fields or list(DEFAULT_SETTINGS["fields"]),
        "separator": settings.get("separator") if settings.get("separator") in SEPARATORS else DEFAULT_SETTINGS["separator"],
        "missing": settings.get("missing") if settings.get("missing") in MISSING else DEFAULT_SETTINGS["missing"],
    }


def load_settings(path=None) -> Dict:
    path = path or SETTINGS_FILE
    try:
        return valid_settings(json.loads(path.read_text()).get("fasta_header"))
    except (OSError, ValueError, AttributeError):
        return valid_settings(None)


def save_settings(settings: Dict, path=None) -> None:
    path = path or SETTINGS_FILE
    try:
        current = json.loads(path.read_text())
        current = current if isinstance(current, dict) else {}
    except (OSError, ValueError):
        current = {}
    current["fasta_header"] = valid_settings(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(current, indent=2) + "\n")
