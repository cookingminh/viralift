"""
valkit — the validation library behind validation/units/*.ipynb.

Scoring lives here, once, with tests; notebooks only call and interpret.
"""
from validation.valkit.paths import APP, CONFIG, CONFIGS, CROSS_CHECK, DATA, OUTPUTS, ROOT, VALIDATION  # noqa: F401
from validation.valkit.datasets import load_datasets, load_reference_bundle  # noqa: F401
from validation.valkit.truth import (  # noqa: F401
    build_truth_presence,
    dedupe_truth_by_name,
    filter_subfeatures,
    parse_features_for_type,
    parse_truth_features,
    parse_validation_truth_features,
    ref_codon_checkable_genes,
    should_use_target_truth_filter,
    truth_target_names,
)
from validation.valkit.metrics import (  # noqa: F401
    best_overlap,
    classify_prediction,
    compare_predictions_to_truth,
    iou,
    lifted_to_rows,
)
from validation.valkit.report import (  # noqa: F401
    adjudicate_failures,
    attach_ref_lengths,
    collect_alias_rows,
    evaluate_alias_rows,
    summarize_comparison,
    summarize_evaluable,
    summarize_overall,
    summarize_per_gene,
)
from validation.valkit.engines.viralift import (  # noqa: F401
    run_lifting_accuracy,
    run_production_pipeline_against_truth,
    run_tblastn_against_truth,
)
