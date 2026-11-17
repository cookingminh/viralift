"""
Compatibility shim. The functions now live in validation/valkit/ (one module per
responsibility, with tests). Existing notebooks that do
`from validation._shared.validation_utils import *` keep working unchanged;
new code should import from validation.valkit directly.
"""
from validation.valkit import *  # noqa: F401,F403
from validation.valkit import (  # noqa: F401  (names `import *` would hide)
    APP, CONFIG, CROSS_CHECK, DATA, ROOT,
)
# Tool symbols the old module re-exported for notebooks.
from app.src.alias.alias_registry import detect_alias_config_for_record, get_detected_virus_name  # noqa: F401
from app.src.alias.gene_alias import (  # noqa: F401
    EXCLUSION_SENTINELS, apply_alias_to_feature, apply_alias_to_features, load_alias_lookup,
    lookup_field_value, normalize_text,
)
from app.src.features.annotation_strategy import get_strategy, select_feature_type  # noqa: F401
from app.src.features.direct_extractor import direct_extract_with_alias  # noqa: F401
from app.src.features.ref_loader import prepare_reference_features  # noqa: F401
from app.src.io.genbank_parser import (  # noqa: F401
    _LOOKUP_QUALIFIER_KEYS, load_genbank_records, load_single_genbank, parse_cds_features, parse_mat_peptides,
)
from app.src.lifting.tblastn_lifter import lift_all_tblastn, process_one_query_record  # noqa: F401
from app.src.pipeline import PipelineConfig, run_pipeline  # noqa: F401
import pandas as pd  # noqa: F401
from pathlib import Path  # noqa: F401
