# ViraLift validation

How the tool is validated, and how to re-run every number. Scoring rules are in
[METHODOLOGY.md](METHODOLOGY.md); the restructuring plan and its status are in
[RESTRUCTURE_PROPOSAL.md](RESTRUCTURE_PROPOSAL.md).

Two questions, kept apart:

1. **How good is ViraLift's own engine?** (`units/02_lifting_accuracy`, `07`, `08`, `09`, `10`)
2. **How does it compare with other engines?** (`units/04_engine_comparison`, `units/05_tool_comparison`)

## Layout

```
validation/
  METHODOLOGY.md         scoring rules every unit shares
  configs/
    datasets.json        virus -> reference(s), query set, feature level
    engines.json         engines the suite can score, and what each needs on PATH
  valkit/                the library: truth, metrics, report, engines/, runner, notebooks
  tests/                 pytest for the scoring rules (python -m pytest validation/tests)
  units/                 one folder per question; notebooks read run folders and interpret
  outputs/               run folders (git-ignored) + latest/*.summary.json (tracked)
  docker/                validation image = production image + notebook tooling
  archive/               earlier runs, kept for reference, not a source of numbers
  _shared/               compatibility shim for notebooks not yet migrated to valkit
```

## Run the engine validation

Inputs are the local GenBank files under `app/data/` (git-ignored). BLAST+ (`tblastn`) must be on PATH.

```bash
# host (fast iteration)
python -m validation.valkit.runner lifting_accuracy --label local

# inside the production image (the numbers to quote)
docker compose build
docker compose --profile validation build
docker compose --profile validation run --rm validation lifting_accuracy --label docker
```

Each run writes `outputs/<time>_<commit>_<label>_lifting_accuracy/` with `manifest.json`
(commit, Python, Biopython, tblastn version, alias-config fingerprints, parameters),
`summary.json` (headline numbers, per gene, offset tiers, accuracy by identity bin, attribution
counts) and per-dataset tables (`per_prediction.tsv`, `per_gene.tsv`, `overall.tsv`,
`truth_presence.tsv`, `ref_model.tsv`, `attribution.tsv`, `unscored_predictions.tsv`).
`--axes forward,rc` also lifts the reverse complement of every record. `outputs/latest/` keeps
the newest summary. `reattribute --run <run_id>` recomputes the attribution of an existing run.

Compare two runs with `diff -r outputs/<run_a> outputs/<run_b>`.

## Read and interpret

```bash
python -m validation.valkit.notebooks validation/units/02_lifting_accuracy/lifting_accuracy.ipynb \
    --param DATASET=prrs --param RUN_ID=latest --out validation/outputs/<run_id>/notebooks
```

The notebook never runs tblastn; it reads the run folder, writes `coord_only_cases.tsv`,
`failed_cases.tsv`, `failure_adjudication.tsv`, `extra_without_truth_cases.tsv` and a figure next
to the data, and ends with an auto-generated summary.

## Units

| Unit | Question | State |
|---|---|---|
| `00_dataset` | which records are valid ground truth | legacy notebook |
| `01_alias_coverage` | how much GenBank name variation the alias map resolves | legacy notebook |
| `02_lifting_accuracy` | per-gene lifting accuracy of the tblastn engine | **migrated**: runner + `lifting_accuracy.ipynb` (one notebook, `DATASET` parameter) |
| `03_alias_suggestion` | alias config reconstruction, LLM-assisted review | legacy notebooks + scripts; needs an API key for the LLM part |
| `04_engine_comparison` | tblastn vs minimap2 | legacy; the minimap path in `app/src` is broken (see docs/CODE_REVIEW.md P1-28) |
| `05_tool_comparison` | ViraLift vs Liftoff, LiftOn, GATU, VAPiD | legacy; external tools not installed here |
| `06_run_tool_extract` | routing + ORF5 extraction on a mixed corpus | legacy |
| `07_ablation_runtime` | what alias map, router and rescue each contribute | legacy |
| `08_failure_attribution` | tool error vs annotation problem, with evidence per case | **migrated**: `valkit/attribution.py` + `failure_attribution.ipynb` reading a run folder |
| `09_recovery_unannotated` | annotating records with no annotation | legacy |
| `10_pipeline_end_to_end` | the shipped pipeline, routing included | runner task `pipeline_end_to_end`; notebook legacy |

"Legacy" notebooks still run: they import `validation._shared.validation_utils`, which now
re-exports `valkit`, so their numbers come from the same code as the migrated unit.

## Accuracy definition (short)

Denominator = `(record, gene)` pairs where the gene is in the reference **and** in the record's
own annotation (after alias normalisation). A prediction is correct if IoU ≥ 0.90 or both
boundaries are within ±6 bp of the annotation; for CDS references, genes whose reference CDS is
codon-clean must also lift as a valid CDS. A gene the tool does not lift counts as a failure.
Predictions with no same-name truth (name gap, granularity) are reported separately and are
not in the denominator.
