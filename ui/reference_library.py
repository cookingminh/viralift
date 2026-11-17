# Saved references: the reference of every run is kept so that next time the
# user only adds the query file. When the query's virus is recognised (the same
# registry keywords that pick the alias config), its saved reference is
# suggested. Files live in app/config/references/ (bind-mounted in Docker and
# git-ignored, like the rest of the runtime state) next to an index.json.
import io
import json
import re
import shutil
import warnings
from collections import Counter
from datetime import datetime, timezone
from itertools import islice
from pathlib import Path
from typing import Dict, List, Optional, TextIO, Tuple
from Bio import BiopythonParserWarning, SeqIO
from Bio.SeqRecord import SeqRecord
from app.src.alias.alias_registry import find_registry_entry_for_record, load_alias_registry
from ui.state import CONFIG_DIR


REFERENCE_DIR = CONFIG_DIR / "references"
INDEX_FILE = "index.json"
# Virus detection reads only the head of the query file: enough for this many
# records without parsing a whole multi-thousand-record download.
DETECT_SAMPLE = 25
DETECT_BYTES = 2_000_000


def _directory(directory: Optional[Path]) -> Path:
    return Path(directory) if directory else REFERENCE_DIR


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _read_index(directory: Path) -> List[Dict]:
    try:
        return json.loads((directory / INDEX_FILE).read_text(encoding="utf-8")).get("references", [])
    except (OSError, ValueError):
        return []


def _write_index(directory: Path, entries: List[Dict]) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    tmp = directory / f"{INDEX_FILE}.tmp"
    tmp.write_text(json.dumps({"references": entries}, indent=2), encoding="utf-8")
    tmp.replace(directory / INDEX_FILE)


def list_references(directory: Optional[Path] = None) -> List[Dict]:
    """Saved references whose file still exists, grouped by virus, newest use first."""
    root = _directory(directory)
    entries = [entry for entry in _read_index(root) if (root / entry.get("file", "")).is_file()]
    entries.sort(key=lambda entry: entry.get("last_used", ""), reverse=True)
    entries.sort(key=lambda entry: entry.get("virus_name", "").lower())
    return entries


def reference_file(entry: Dict, directory: Optional[Path] = None) -> Path:
    return _directory(directory) / entry["file"]


def save_reference(
    source: Path,
    record: SeqRecord,
    virus_name: Optional[str],
    feature_type: Optional[str],
    n_features: int,
    directory: Optional[Path] = None,
) -> Dict:
    """Copy a reference GenBank file into the library, or refresh its entry."""
    root = _directory(directory)
    root.mkdir(parents=True, exist_ok=True)
    file_name = f"{re.sub(r'[^A-Za-z0-9._-]', '_', record.id) or 'reference'}.gb"
    if Path(source).resolve() != (root / file_name).resolve():
        shutil.copyfile(source, root / file_name)

    entries = _read_index(root)
    entry = next((e for e in entries if e.get("id") == record.id), None)
    if entry is None:
        entry = {"id": record.id, "added": _now()}
        entries.append(entry)
    entry.update(
        file=file_name,
        virus_name=virus_name or "",
        description=record.description,
        length=len(record.seq),
        feature_type=feature_type or "",
        genes=n_features,
        last_used=_now(),
    )
    _write_index(root, entries)
    return entry


def mark_used(ref_id: str, directory: Optional[Path] = None) -> None:
    root = _directory(directory)
    entries = _read_index(root)
    for entry in entries:
        if entry.get("id") == ref_id:
            entry["last_used"] = _now()
    _write_index(root, entries)


def remove_reference(ref_id: str, directory: Optional[Path] = None) -> None:
    root = _directory(directory)
    entries = _read_index(root)
    for entry in entries:
        if entry.get("id") == ref_id:
            (root / entry.get("file", "")).unlink(missing_ok=True)
    _write_index(root, [entry for entry in entries if entry.get("id") != ref_id])


def suggest_reference(virus_name: Optional[str], entries: List[Dict]) -> Optional[Dict]:
    """The most recently used saved reference for this virus, if any."""
    matches = [entry for entry in entries if virus_name and entry.get("virus_name") == virus_name]
    return max(matches, key=lambda entry: entry.get("last_used", "")) if matches else None


def detect_virus(handle: TextIO, registry_path: Path, sample: int = DETECT_SAMPLE) -> Optional[Tuple[str, int, int]]:
    """Registry virus that most of the first `sample` records match.

    Returns (virus_name, matched, checked), or None when no virus covers at
    least half of the records checked.
    """
    registry = load_alias_registry(registry_path)
    names: List[Optional[str]] = []
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", BiopythonParserWarning)
            for record in islice(SeqIO.parse(handle, "genbank"), sample):
                entry = find_registry_entry_for_record(record, registry)
                names.append(entry.get("virus_name") if entry else None)
    except Exception:
        pass  # the head may end mid-record; malformed files are reported at load time
    if not names:
        return None
    name, matched = Counter(names).most_common(1)[0]
    if name is None or matched * 2 < len(names):
        return None
    return name, matched, len(names)


def detect_virus_in_bytes(data: bytes, registry_path: Path) -> Optional[Tuple[str, int, int]]:
    return detect_virus(io.StringIO(data[:DETECT_BYTES].decode("utf-8", errors="replace")), registry_path)
