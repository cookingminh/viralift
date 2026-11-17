# 02 — Lifting accuracy of the ViraLift tblastn engine

Question: **per gene, how often does the forced tblastn lift land on the record's own annotation?**

Run and read:

```bash
docker compose --profile validation run --rm validation lifting_accuracy --label docker
python -m validation.valkit.notebooks validation/units/02_lifting_accuracy/lifting_accuracy.ipynb \
    --param DATASET=prrs --param RUN_ID=latest --out validation/outputs/<run_id>/notebooks
```

`lifting_accuracy.ipynb` takes `DATASET` (prrs, fmd, ped) and reads a run folder; it never runs
tblastn itself. The three per-virus notebooks it replaces are in git history (before `bff2328`).

## Result of run `20261006T044156Z_b5cfc35_docker_lifting_accuracy`

Engine: production image (Python 3.11.17, Biopython 1.88, tblastn 2.16.0), committed alias configs,
`PipelineConfig` defaults. Headline numbers are unchanged from the figures recorded in
`NOTEBOOK_MANIFEST.tsv` (99.75 / 99.83 / 99.80).

| Virus | (record, gene) pairs | exact | coord-only | failed | accuracy |
|---|---|---|---|---|---|
| PRRSV | 796 | 706 | 88 | 2 | 99.75 % |
| FMDV | 1171 | 1137 | 32 | 2 | 99.83 % |
| PEDV | 505 | 500 | 4 | 1 | 99.80 % |

The same run on the host (tblastn 2.17.0, Python 3.13) gives identical coordinates and statuses
for all 2,762 predictions; one FMDV row differs in bit score only. The BLAST version does not move
these numbers.

### What the non-exact cases are (written from the run's `coord_only_cases.tsv` / `failed_cases.tsv`)

**PRRSV.** 87 of the 88 coord-only cases are ORF1b starts: the lift places the start where the
reference does (85 of 87 predictions have exactly the reference length), while submitters place
the frameshift-product start −12, −3, +6 or −9 nt from there. This is a convention difference,
not a boundary error; ORF1b has no ATG of its own, so there is nothing for the lifter to anchor
on. Both failures are in one record, `AF331831.1`, whose annotation labels ORF1a "RNA polymerase"
(so it resolves to ORF1b) and puts ORF5's coordinates on ORF2b. Neither is a lifting error.

**FMDV.** All 32 coord-only cases are the VP1/2A junction in 16 records that annotate 2A as 16 aa
instead of the reference's 18 aa (VP1 ends 6 nt later, 2A starts 6 nt later). Failures:
`AY687334.1` VP2, where the record's own VP2 is 100 aa longer than the reference's (an annotation
anomaly), and `MG372730.1` 3A, which the lift truncates at a run of 93 `N` inside the gene. The
second one is the only tool-side failure in the three corpora.

**PEDV.** Three coord-only ORF1b starts (+135, +195, +210 nt) come from `PED_ref_1.gb`, whose ORF1b
is annotated from an internal ATG at 12811; the records start it further upstream. The fourth is
`MF577027.1` S, lifted 36 nt upstream of the annotation: IoU 0.99 keeps it "correct", but it is a
real start-rescue mistake (fixed on `chore/code-review-polish`, review P0-2). The one failure,
`KX550281.1`, annotates the whole ORF1ab (293–20637) under a name that resolves to ORF1b.

### Two things the metric should say out loud

1. **The denominator depends on the alias config.** The committed `prrsv_alias.json` gives 796
   pairs; the working-tree copy (two aliases removed by the UI) gives 823 pairs and 8 failures,
   because six records' full-ORF1ab features then resolve to ORF1b. Every run manifest now records a
   fingerprint of each config; quote numbers only with the committed configs.
2. **IoU ≥ 0.90 is lenient on long genes.** A 4 kb gene can start 400 nt off and still count as
   correct. The `exact` column, and `delta_start` / `delta_end` in `per_prediction.tsv`, are the
   strict view; `coord-only` should be read together with the delta tables above.

*Interpretation written by the assistant from the run outputs on 2026-10-06; review before quoting.*
