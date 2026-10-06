"""
Run one validation task over the configured datasets and write a run-stamped
output folder.

    python -m validation.valkit.runner lifting_accuracy [--datasets prrs,fmd,ped]
                                                        [--label local] [--out validation/outputs]

Writes validation/outputs/<run_id>/ with

    manifest.json           commit, environment, tool versions, parameters
    summary.json            headline numbers per dataset (machine-readable)
    <dataset>/              per_prediction.tsv, per_gene.tsv, overall.tsv,
                            truth_presence.tsv, ref_model.tsv

and refreshes validation/outputs/latest/ (summary.json + manifest.json), which is
the only run output tracked in git. run_id = <UTC time>_<commit>_<label>_<task>.
Two runs are compared with `diff -r` on their folders.
"""
from __future__ import annotations

import argparse
import json
import platform
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from validation.valkit.paths import OUTPUTS, ROOT
from validation.valkit.datasets import load_datasets

TASKS = ("lifting_accuracy", "pipeline_end_to_end")


def _cmd(args: List[str]) -> str:
    try:
        return subprocess.run(args, capture_output=True, text=True, check=False).stdout.strip()
    except OSError:
        return ""


def _config_fingerprints() -> Dict[str, str]:
    """
    sha256 (first 12 hex) of every alias config and the registry that this run used.

    The alias config decides which annotation names count as truth, so the same
    code on the same data gives a different denominator when the config differs.
    The PRRSV denominator moved from 796 to 823 (record, gene) pairs after a UI
    edit removed two aliases, which is why the fingerprint is part of the run id's
    provenance.
    """
    import hashlib
    out = {}
    for path in sorted((ROOT / "app" / "config").glob("*.json")):
        out[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()[:12]
    return out


def _commit_from_dotgit() -> str:
    """Short HEAD commit read from .git without a git binary (bind-mounted .git in the image)."""
    dotgit = ROOT / ".git"
    try:
        head = (dotgit / "HEAD").read_text().strip()
        if head.startswith("ref: "):
            ref = head[5:]
            ref_file = dotgit / ref
            if ref_file.exists():
                return ref_file.read_text().strip()[:7]
            for line in (dotgit / "packed-refs").read_text().splitlines():
                if line.endswith(" " + ref):
                    return line.split()[0][:7]
            return ""
        return head[:7]
    except OSError:
        return ""


def environment_manifest() -> Dict:
    import Bio
    tblastn = _cmd(["tblastn", "-version"]).splitlines()
    git = ["git", "-C", str(ROOT), "-c", f"safe.directory={ROOT}"]
    commit = _cmd([*git, "rev-parse", "--short", "HEAD"]) or _commit_from_dotgit() or "unknown"
    # In the container the working tree is a COPY of the host tree, so `git status`
    # compares the index with that copy: a modified config on the host shows as dirty.
    # Without a git binary (the slim image has none) dirtiness is unknown; the alias
    # config fingerprints below are the reliable provenance in that case.
    has_git = bool(_cmd(["git", "--version"]))
    dirty_files = _cmd([*git, "status", "--porcelain", "--", "app/config", "app/src", "validation"]) if has_git else ""
    return {
        "commit": commit,
        "dirty": bool(dirty_files) if has_git else None,
        "dirty_files": sorted(line[3:] for line in dirty_files.splitlines()),
        "alias_configs": _config_fingerprints(),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "biopython": Bio.__version__,
        "tblastn": tblastn[0] if tblastn else "not found",
        "in_container": Path("/.dockerenv").exists(),
    }


def run_lifting_accuracy_task(datasets: Dict[str, Dict], out_dir: Path, progress: bool,
                              axes: Sequence[str] = ("forward",)) -> Dict:
    from app.src.io.genbank_parser import load_genbank_records
    from app.src.pipeline import PipelineConfig
    from validation.valkit.attribution import (
        accuracy_by_identity, attribute_cases, check_unscored_predictions, offset_tiers,
    )
    from validation.valkit.datasets import load_reference_bundle
    from validation.valkit.engines.viralift import run_lifting_accuracy
    from validation.valkit.truth import parse_truth_features, ref_codon_checkable_genes

    cfg = PipelineConfig()
    result = {"task": "lifting_accuracy", "engine": "viralift_tblastn",
              "parameters": {"min_coverage": cfg.min_coverage, "min_identity": cfg.min_identity,
                             "evalue": cfg.evalue, "rescue_window": cfg.rescue_window,
                             "iou_threshold": 0.90, "bp_tolerance": 6, "axes": list(axes)},
              "datasets": {}}
    jobs = [(label, ds, axis) for label, ds in datasets.items() for axis in axes]
    for base_label, ds, axis in jobs:
        label = base_label if axis == "forward" else f"{base_label}_{axis}"
        t0 = time.time()
        ds_out = out_dir / label
        per_pred, per_gene, overall, truth_presence, ref_model = run_lifting_accuracy(
            base_label, Path(ds["references"][0]), Path(ds["query"]), ds_out, progress=progress,
            reverse_complement=(axis == "rc"))
        # the runner labels rows by dataset+axis so tables of one run never collide
        per_pred["virus"] = label
        per_gene["virus"] = label
        overall["virus"] = overall["virus"].replace({base_label: label})
        # attach truth presence so every downstream table knows what is in the denominator
        per_pred = per_pred.merge(
            truth_presence.rename(columns={"gene": "ref_name"}), on=["record_id", "ref_name"], how="left")
        per_pred.to_csv(ds_out / "per_prediction.tsv", sep="\t", index=False)
        per_gene.to_csv(ds_out / "per_gene.tsv", sep="\t", index=False)
        overall.to_csv(ds_out / "overall.tsv", sep="\t", index=False)
        truth_presence.to_csv(ds_out / "truth_presence.tsv", sep="\t", index=False)
        ref_model.to_csv(ds_out / "ref_model.tsv", sep="\t", index=False)
        # evidence-based attribution of every non-exact scored prediction, the strict
        # offset tiers, accuracy by divergence, and a check of the unscored predictions
        bundle = load_reference_bundle(Path(ds["references"][0]))
        records = {r.id: r for r in load_genbank_records(Path(ds["query"]))}
        codon_required = ref_codon_checkable_genes(bundle)
        attributed = attribute_cases(per_pred, records, ds["feature_level"], codon_required)
        attributed.to_csv(ds_out / "attribution.tsv", sep="\t", index=False)
        all_truth = {
            rid: parse_truth_features(rec, bundle["alias_lookup"], bundle["feature_type"], filter_nested=False)[0]
            for rid, rec in records.items()
        }
        unscored = check_unscored_predictions(per_pred, all_truth)
        unscored.to_csv(ds_out / "unscored_predictions.tsv", sep="\t", index=False)
        tiers = offset_tiers(per_pred)
        by_identity = accuracy_by_identity(per_pred)
        attribution_summary = (
            attributed.groupby(["bucket", "side", "category"]).size().reset_index(name="n").to_dict("records")
            if not attributed.empty else []
        )
        unscored_summary = unscored["check"].value_counts().to_dict() if not unscored.empty else {}

        row = overall[overall["virus"] == label].iloc[0]
        result["datasets"][label] = {
            "virus": ds["virus"], "feature_level": ds["feature_level"], "axis": axis,
            "reference": Path(ds["references"][0]).name, "query": Path(ds["query"]).name,
            "records_scored": int(per_pred["record_id"].nunique()) if not per_pred.empty else 0,
            "truth_genes": int(row["total"]), "exact": int(row["exact"]),
            "coord_only": int(row["coord_only"]), "failed": int(row["failed"]),
            "no_hit": int(row["no_hit"]),
            "exact_pct": float(row["exact_pct"]), "accuracy_pct": float(row["accuracy_pct"]),
            "offset_tiers": tiers,
            "accuracy_by_identity": by_identity,
            "attribution": attribution_summary,
            "unscored_predictions": {"n": int(len(unscored)), **{str(k): int(v) for k, v in unscored_summary.items()}},
            "seconds": round(time.time() - t0, 1),
            "per_gene": {
                g["gene"]: {"total": int(g["total"]), "exact": int(g["exact"]), "coord_only": int(g["coord_only"]),
                            "failed": int(g["failed"]), "accuracy_pct": g["accuracy_pct"]}
                for g in per_gene.to_dict("records")
            },
        }
        print(f"{label}: {int(row['total'])} truth genes, exact {int(row['exact'])}, "
              f"coord_only {int(row['coord_only'])}, failed {int(row['failed'])}, "
              f"accuracy {row['accuracy_pct']}%  ({result['datasets'][label]['seconds']}s)", flush=True)
    return result


def run_pipeline_end_to_end_task(datasets: Dict[str, Dict], out_dir: Path, progress: bool) -> Dict:
    from validation.valkit.engines.viralift import run_production_pipeline_against_truth
    from validation.valkit.report import summarize_evaluable

    result = {"task": "pipeline_end_to_end", "engine": "viralift_pipeline", "datasets": {}}
    for label, ds in datasets.items():
        t0 = time.time()
        ds_out = out_dir / label
        per_pred, _summary = run_production_pipeline_against_truth(
            label, Path(ds["references"][0]), Path(ds["query"]), ds_out)
        ev = summarize_evaluable(per_pred, ["virus", "method"]) if not per_pred.empty else None
        if ev is not None:
            ev.to_csv(ds_out / "evaluable_by_method.tsv", sep="\t", index=False)
        result["datasets"][label] = {
            "virus": ds["virus"], "predictions": int(len(per_pred)),
            "by_method": ev.to_dict("records") if ev is not None else [],
            "seconds": round(time.time() - t0, 1),
        }
        print(f"{label}: {len(per_pred)} predictions ({result['datasets'][label]['seconds']}s)", flush=True)
    return result


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("task", choices=TASKS)
    parser.add_argument("--datasets", default="prrs,fmd,ped", help="Comma-separated labels from configs/datasets.json")
    parser.add_argument("--label", default="local", help="Environment tag for the run id, e.g. local or docker")
    parser.add_argument("--out", default=str(OUTPUTS), help="Output root (default validation/outputs)")
    parser.add_argument("--axes", default="forward",
                        help="Comma-separated: forward (deposited orientation), rc (lift the reverse "
                             "complement and map coordinates back). Default: forward")
    parser.add_argument("--no-progress", action="store_true")
    args = parser.parse_args(argv)
    axes = tuple(a.strip() for a in args.axes.split(",") if a.strip())
    if any(a not in ("forward", "rc") for a in axes):
        raise SystemExit(f"unknown axis in {args.axes!r}; use forward and/or rc")

    all_datasets = load_datasets()
    chosen = {}
    for label in args.datasets.split(","):
        label = label.strip()
        if label not in all_datasets:
            raise SystemExit(f"unknown dataset {label!r}; known: {sorted(all_datasets)}")
        ds = all_datasets[label]
        missing = [p for p in [*ds["references"], ds["query"]] if not Path(p).exists()]
        if missing:
            raise SystemExit(f"dataset {label!r}: missing input file(s): {missing}")
        chosen[label] = ds

    env = environment_manifest()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_id = f"{stamp}_{env['commit']}_{args.label}_{args.task}"
    out_dir = Path(args.out) / run_id
    out_dir.mkdir(parents=True, exist_ok=False)

    started = time.time()
    if args.task == "lifting_accuracy":
        result = run_lifting_accuracy_task(chosen, out_dir, progress=not args.no_progress, axes=axes)
    else:
        result = run_pipeline_end_to_end_task(chosen, out_dir, progress=not args.no_progress)

    manifest = {"run_id": run_id, "started_utc": stamp, "seconds": round(time.time() - started, 1),
                "environment": env, "label": args.label, **{k: v for k, v in result.items() if k != "datasets"}}
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    summary = {"run_id": run_id, "task": args.task, "commit": env["commit"], "dirty": env["dirty"],
               "label": args.label, "tblastn": env["tblastn"], "python": env["python"],
               "biopython": env["biopython"], "alias_configs": env["alias_configs"],
               "datasets": result["datasets"]}
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")

    latest = Path(args.out) / "latest"
    latest.mkdir(parents=True, exist_ok=True)
    for name in ("summary.json", "manifest.json"):
        shutil.copy2(out_dir / name, latest / f"{args.task}.{name}")
    print(f"\nrun: {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
