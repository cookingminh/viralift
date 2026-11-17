# 08 — Failure attribution

Question: **for every lift that is not base-exact, what does the sequence say about who is wrong?**

Attribution is computed by `validation/valkit/attribution.py` on every run of the
`lifting_accuracy` task (files `attribution.tsv` and `unscored_predictions.tsv` in each dataset
folder) and can be recomputed on an existing run without re-lifting:

```bash
python -m validation.valkit.runner reattribute --run <run_id>
python -m validation.valkit.notebooks validation/units/08_failure_attribution/failure_attribution.ipynb \
    --param RUN_ID=<run_id> --out validation/outputs/<run_id>/notebooks
```

## What changed from the earlier adjudication

The previous `adjudicate_failures` decided from length deltas alone. On the current corpus it
labelled four of the five failures "boundary convention", including two with IoU 0.00 and 0.001.
The new attribution checks things that can be verified and prints them next to the verdict:

| evidence column | checks |
|---|---|
| `truth_matches_other_pred`, `_iou` | the truth span coincides with another gene's prediction (label swap) |
| `truth_covers_other_preds` | the truth span contains another gene's whole prediction (merged feature) |
| `truth_frame_ok`, `truth_cds_valid` | the annotated span is in frame, ends on a stop, has no internal stop; and additionally starts with ATG |
| `pred_frame_ok`, `pred_cds_valid` | the same for the prediction |
| `n_in_uncovered_truth` | N bases in the part of the truth the lift did not cover |
| `offset_recurrence`, `pred_len_eq_ref` | the same (gene, Δstart, Δend) in how many records; whether the lift reproduces the reference length |

A missing ATG alone never blames the annotation: ORF1b-type frameshift products and alternative
starts are legitimate conventions, so a span that keeps frame and stop but lacks ATG is
`undecided / start_convention`. Both the `failed` bucket and the `coord-only` bucket (counted
correct by IoU or ±6 bp) are attributed, because the lenient bucket is where real mistakes hide.

## Result of run `20261006T071356Z_50336f7_docker_lifting_accuracy`

Engine on `main` (before the fixes on `chore/code-review-polish`), production image, committed
alias configs, forward and reverse-complement axes.

| Virus | non-exact | failed → verdict | coord-only → verdict |
|---|---|---|---|
| PRRSV | 90 | 2 `annotation/label_swap` (`AF331831.1`: ORF1a region labelled ORF1b, ORF5 region labelled ORF2b) | 82 `convention` (ORF1b start −12/−3/+6, lift = reference length), 2 `undecided/recurring_offset`, 3 `undecided/reference_vs_record_boundary` (ORF1b −9 ×2, −75 ×1), 1 `annotation/truth_not_valid_cds` (`DQ779791.1` ORF1a annotated end is out of frame) |
| FMDV | 34 | 1 `annotation/granularity` (`AY687334.1` VP2 annotation also covers VP4), 1 `data/sequencing_gap` (`MG372730.1` 3A: 93 N in the uncovered part) | 25 `convention` (2A −6 in 16 records; VP1 −6), 7 `undecided/recurring_offset` (VP1 −6 where the lift is not reference-length) |
| PEDV | 5 | 1 `annotation/granularity` (`KX550281.1` ORF1b annotation spans ORF1a+ORF1b) | 3 `undecided/start_convention` (ORF1b +135/+195/+210: record starts at the frameshift site, reference at an internal ATG), **1 `tool/pred_not_valid_cds`** (`MF577027.1` S: lift 36 nt upstream, contains an internal stop; fixed on `chore/code-review-polish`) |

Reverse-complement axis: identical to forward for all 2,472 scored pairs except `FJ175666.1` 2A
(FMDV), lifted on the forward strand by gap-filling and `no_hit` on the reverse complement. That
is the gap-fill strand bug fixed on `chore/code-review-polish`.

Strict view (offset tiers over scored pairs): PRRSV 706 exact / 32 within 3 bp / 12 within 6 bp /
43 within 30 bp / 3 beyond; FMDV 1137 / 0 / 32 / 0 / 2; PEDV 500 / 0 / 0 / 0 / 5.

Predictions outside the denominator (no same-name annotation), checked against the record's full
annotation: PEDV 181, of which 166 share a boundary with the merged ORF1ab the record annotates;
PRRSV 104, of which 50 are consistent with a merged ORF1ab and 51 are ORF2b predictions nested
inside the annotated ORF2a of records that do not annotate ORF2b; FMDV 5.

### Honest reading

- **Tool-side evidence in the whole corpus: one wrong lift (PEDV S) and one strand asymmetry
  (FMDV 2A on the reverse complement).** Both are known bugs with fixes waiting on the review
  branch. The 3A truncation is a sequencing gap in the record, not a lift error.
- **The accuracy metric did not see the PEDV S error.** It counted the lift correct (IoU 0.99).
  Only the attribution of the coord-only bucket surfaced it. Headline accuracy therefore overstates
  the engine slightly; the per-gene strict tiers and `attribution.tsv` are the numbers to read.
- **Everything else that is not exact is a convention or an annotation problem, with the evidence
  printed per row**, except 12 cases left `undecided` on purpose (recurring offsets where the lift
  is not reference-length, and single-record ORF1b start differences).

*Written from the run outputs on 2026-10-06; review before quoting.*
