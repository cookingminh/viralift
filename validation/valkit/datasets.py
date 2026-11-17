"""
Reference bundles and dataset configs (validation/configs/datasets.json).

Functions here were moved verbatim from validation/_shared/validation_utils.py
(validation branch @ b9f5894). Any change to a scoring rule must come with a
test in validation/tests/ and a note in validation/METHODOLOGY.md.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional

from app.src.alias.alias_registry import detect_alias_config_for_record, get_detected_virus_name
from app.src.features.ref_loader import prepare_reference_features
from app.src.io.genbank_parser import load_single_genbank

from validation.valkit.paths import CONFIG, CONFIGS, DATA, ROOT


def load_reference_bundle(ref_path: Path, registry_path: Path = CONFIG / "virus_alias_registry.json") -> Dict:
    ref_record = load_single_genbank(ref_path)
    alias_config_path = detect_alias_config_for_record(ref_record, registry_path)
    if alias_config_path is not None and not alias_config_path.is_absolute():
        alias_config_path = ROOT / alias_config_path
    ref_features, ref_feature_type, alias_config_path, virus_name, alias_lookup = prepare_reference_features(
        ref_record=ref_record,
        alias_config_arg=str(alias_config_path) if alias_config_path else None,
        alias_registry_arg=str(registry_path),
    )
    return {
        "record": ref_record,
        "features": ref_features,
        "feature_type": ref_feature_type,
        "alias_config_path": alias_config_path,
        "alias_lookup": alias_lookup,
        "virus_name": virus_name or get_detected_virus_name(ref_record, registry_path),
    }


def load_datasets(config_path: Path = CONFIGS / "datasets.json") -> Dict[str, Dict]:
    """
    Dataset declarations: {label: {"virus", "references": [...], "query", "feature_level", ...}}.

    `references` is a list so that a multi-reference run is a configuration
    change, not a code change. Single-reference runs use references[0]. Paths
    are relative to app/data unless absolute.
    """
    data = json.loads(Path(config_path).read_text(encoding="utf-8"))
    out: Dict[str, Dict] = {}
    for label, entry in data["datasets"].items():
        refs = [str((DATA / r) if not Path(r).is_absolute() else Path(r)) for r in entry["references"]]
        query = entry["query"]
        out[label] = {
            **entry,
            "label": label,
            "references": refs,
            "query": str((DATA / query) if not Path(query).is_absolute() else Path(query)),
        }
    return out
