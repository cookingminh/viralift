from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

from Bio.SeqRecord import SeqRecord

from app.src.features.annotation_strategy import get_strategy, reference_levels
from app.src.features.direct_extractor import direct_extract_with_alias
from app.src.io.result_writer import summarize_counts
from app.src.io.run_logger import log_error
from app.src.lifting.base import LiftedFeature
from app.src.lifting.missing_genes import add_missing_genes
from app.src.lifting.tblastn_lifter import process_one_query_record


ProgressCallback = Callable[[int, int, str], None]


@dataclass(frozen=True)
class PipelineConfig:
    min_coverage: float = 0.5
    min_identity: float = 0.3
    evalue: float = 1e-5
    rescue_window: int = 200
    catch_record_errors: bool = False
    # Also lift, with tblastn, the reference genes an annotated record does not
    # name (app/src/lifting/missing_genes.py). Off by default so the CLI output
    # stays as validated; the UI turns it on.
    lift_missing: bool = False


@dataclass
class PipelineRunResult:
    all_results: List[Tuple[str, List[LiftedFeature]]] = field(default_factory=list)
    summary: Dict[str, int] = field(default_factory=dict)
    direct_count: int = 0
    lifted_count: int = 0
    missing_lifted_count: int = 0    # annotated records that were also lifted
    errors: List[Dict[str, str]] = field(default_factory=list)


def run_pipeline(
    ref_record: SeqRecord,
    query_records: List[SeqRecord],
    ref_features: List[Dict],
    ref_feature_type: str,
    alias_lookup: Dict[str, str],
    config: Optional[PipelineConfig] = None,
    progress_callback: Optional[ProgressCallback] = None,
) -> PipelineRunResult:
    """
    Run the core ViraLift pipeline over query records.

    CLI and UI both call this function so direct extraction, tblastn lifting,
    summary counting, and per-record error handling stay in one place.
    """
    cfg = config or PipelineConfig()
    result = PipelineRunResult()
    total = len(query_records)

    for index, query_record in enumerate(query_records, start=1):
        if progress_callback is not None:
            progress_callback(index - 1, total, query_record.id)

        # The reference defines the working level for the whole run. A query
        # that happens to carry mature-peptide annotations must not silently
        # switch level on its own: the resulting genes would have no reference
        # counterpart, so asking for a gene like ORF5 across a corpus would
        # return it for every record except that one.
        strategy, query_feature_type = get_strategy(
            query_record,
            alias_lookup,
            allowed_types=reference_levels(ref_feature_type),
        )

        def lift() -> List[LiftedFeature]:
            return process_one_query_record(
                ref_record=ref_record,
                query_record=query_record,
                ref_cds=ref_features,
                ref_feature_type=ref_feature_type,
                min_coverage=cfg.min_coverage,
                min_identity=cfg.min_identity,
                evalue=cfg.evalue,
                rescue_window=cfg.rescue_window,
                quiet=True,
            )

        # A failure keeps whatever rows the record already has, so a failed
        # missing-gene lift still returns the annotated genes.
        features: List[LiftedFeature] = []
        try:
            if strategy == "direct":
                features = direct_extract_with_alias(
                    query_record=query_record,
                    query_feature_type=query_feature_type,
                    ref_features=ref_features,
                    alias_lookup=alias_lookup,
                )
                result.direct_count += 1
                if cfg.lift_missing:
                    features, lifted = add_missing_genes(
                        features, ref_features, len(query_record.seq), lift,
                    )
                    result.missing_lifted_count += lifted
            else:
                features = lift()
                result.lifted_count += 1
        except Exception as exc:
            if not cfg.catch_record_errors:
                raise
            log_error(f"processing record {query_record.id}", exc)
            result.errors.append({"record_id": query_record.id, "error": str(exc)})

        result.all_results.append((query_record.id, features))

    if progress_callback is not None:
        progress_callback(total, total, "done")

    result.summary = summarize_counts(result.all_results)
    return result
