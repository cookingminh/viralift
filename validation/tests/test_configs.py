import json
import shutil

import pytest

from validation.valkit.datasets import load_datasets
from validation.valkit.paths import CONFIGS, ROOT


def test_dataset_config_is_well_formed():
    datasets = load_datasets()
    assert set(datasets) == {"prrs", "fmd", "ped"}
    for label, ds in datasets.items():
        assert ds["references"] and ds["query"] and ds["feature_level"] in ("CDS", "mat_peptide")


def test_engine_config_points_at_existing_adapters():
    engines = json.loads((CONFIGS / "engines.json").read_text(encoding="utf-8"))["engines"]
    production = [name for name, e in engines.items() if e["production"]]
    assert production == ["viralift_tblastn", "viralift_pipeline"]
    for name in production:
        assert (ROOT / "validation" / "valkit" / "engines" / f"{engines[name]['adapter']}.py").exists()


@pytest.mark.skipif(shutil.which("tblastn") is None, reason="tblastn (BLAST+) not installed on PATH")
def test_runner_manifest_records_tool_versions():
    from validation.valkit.runner import environment_manifest
    env = environment_manifest()
    assert env["tblastn"].startswith("tblastn:")
    assert env["python"] and env["biopython"]
