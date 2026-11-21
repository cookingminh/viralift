"""Display text used by the Streamlit UI."""

UI_TEXT = {
    "en": {
        # ── shell ─────────────────────────────────────────────────────
        "brand_subtitle": "Viral gene name standardisation",
        "records_loaded": "{count} records",
        "theme_hint": "Light / dark follows your system; switch it from the ⋮ menu at the top right.",
        "step": "Step",
        "step_of": "{index} of 3 · {name}",
        "step_setup": "Setup",
        "step_setup_note": "Reference + query files",
        "step_review": "Review names",
        "step_review_note": "Only if names are unknown",
        "step_results": "Results",
        "step_results_note": "Inspect and export",
        "guide": "Guide",
        "guide_help": "How this page works, the two annotation paths, and what each status means",
        "guide_this_page": "This page",
        "guide_workflow": "How ViraLift works",
        "guide_reference": "Statuses & terms",
        # ── step 1 · setup ────────────────────────────────────────────
        "run_setup": "Run pipeline",
        "upload_title": "Set up a run",
        "upload_body": (
            "Upload one well-annotated reference and the genomes to standardise. "
            "ViraLift picks direct extraction or tblastn lifting per record and only "
            "asks about gene names it cannot resolve."
        ),
        "reference_record": "Reference",
        "reference_caption": "One well-annotated GenBank record (.gb, .gbk)",
        "query_records": "Query records",
        "query_caption": "One or more genomes; annotation is optional",
        "crawler_query_ready": "Using Data crawler output",
        "saved_reference": "Saved reference",
        "ref_upload_new": "Upload a new reference…",
        "ref_option": "{virus} · {id} · {length} bp · {genes} genes",
        "unknown_virus": "Unknown virus",
        "ref_saved_hint": "The reference is remembered after the run, so next time you only add the query. Manage saved references in Alias manager.",
        "ref_suggested": "Suggested: the query looks like {virus}, and this is its {kind} reference.",
        "ref_default": "default",
        "ref_most_recent": "most recently used",
        "ref_virus_mismatch": "This reference is {ref_virus}, but the query looks like {query_virus}.",
        "ref_none_for_virus": "The query looks like {virus}. No saved reference for it yet: upload one and it is remembered for next time.",
        "forget_reference": "Forget",
        "forget_reference_help": "Remove this reference from the saved list. Your results are not affected.",
        "query_detected": "Looks like {virus} ({matched} of the first {checked} records).",
        "clear_crawler_query": "Use a different file",
        "ref_preview_title": "What this reference will look for",
        "ref_preview_caption": "{count} {level} genes, named by {source}. Every query record is placed against this map.",
        "ref_preview_no_alias": "their own annotation (no alias config for this virus yet)",
        "ref_preview_error": "This reference cannot be used: {error}",
        "ref_preview_raw": "{count} gene(s) are not in the alias config and keep their raw names: {names}.",
        "ref_preview_query": (
            "Query: {count} record(s) · {full} near full length · {partial} partial (under {share} of the "
            "reference length). Genes outside a partial record show as Not in sequence."
        ),
        "run_options": "Run options",
        "run_options_caption": "Defaults suit most viral datasets.",
        "file_requirements": "File requirements",
        "file_requirements_body": (
            "- Reference file: exactly one GenBank record with usable CDS or mat_peptide annotations.\n"
            "- Query file: one or more GenBank records; annotations are optional.\n"
            "- Supported extensions: `.gb` and `.gbk`.\n"
            "- The alias config is auto-detected from `app/config/virus_alias_registry.json`."
        ),
        "lifting_thresholds": "Thresholds (tblastn and annotation check)",
        "threshold_caption": "Defaults are permissive for divergent viral genomes. Tighten them for higher-confidence extraction.",
        "min_coverage": "Min coverage",
        "min_identity": "Min identity",
        "evalue": "E-value",
        "rescue_window": "Rescue window (bp)",
        "lift_missing": "Lift genes the annotation is missing",
        "lift_missing_help": (
            "ON (default): when an annotated record does not name some reference genes (a genome "
            "annotated only as P1/P2/P3 precursors, or short peptides such as 2A and 3B left out), "
            "those genes are lifted with tblastn. The annotated genes are kept exactly as they are, "
            "and genes that lie outside a partial record are not searched.\n\n"
            "OFF: annotated records return only the genes they name (the CLI default)."
        ),
        "check_annotations": "Check annotations against the reference",
        "check_annotations_help": (
            "ON (default): every annotated gene is translated and aligned to the reference protein of "
            "the same name, so its coverage and identity are real (a 69 nt \"VP1\" fragment gets 11%, "
            "not 100%). A gene that is partial, too divergent or longer than the gene is searched with "
            "tblastn, which replaces it when it places the gene differently; the annotation stays "
            "visible and you can switch back.\n\n"
            "OFF: annotated genes are taken as they are (coverage 100%), as in the CLI by default."
        ),
        "use_ref_names": "Output the reference's own gene names",
        "use_ref_names_help": (
            "OFF (default): output canonical names from the alias config key (e.g. 'Lpro').\n\n"
            "ON: output the reference's original gene name instead (e.g. 'Lab' if that's what the reference says)."
        ),
        "ready_to_run": "Ready · {ref} → {query}",
        "add_files_hint": "Add a reference and a query file to continue.",
        "run_button": "Continue",
        "loading_files": "Reading GenBank files...",
        "load_error": "We could not load these files",
        "reference_file": "Reference file",
        "query_file": "Query file",
        "name_mode": "Name mode",
        "reference_names": "reference names",
        "canonical_names": "canonical names",
        # ── step 2 · review names ─────────────────────────────────────
        "alias_review": "Run pipeline",
        "resolve_title": "Review unknown names",
        "resolve_body": (
            "These names are not covered by the alias database. Map the ones you trust; "
            "anything left as raw keeps its original name in the output."
        ),
        "virus_banner": "Virus <b>{virus}</b> · alias config <span class='vl-mono'>{config}</span> · {count} canonical names.",
        "reference": "Reference",
        "detected_virus": "Virus",
        "alias_keys": "Canonical names",
        "ref_missing_title": "{count} reference gene(s) are not in the alias database",
        "ref_missing_body": (
            "Lifting still works for them (tblastn matches protein sequence, not names), "
            "but they will appear with their raw annotation name. Add them as canonical "
            "names so future runs recognise them."
        ),
        "ref_names_pick": "Reference names to add",
        "save_ref_names": "Add as canonical names",
        "canonicals_added": "{count} new canonical name(s) added to the alias config",
        "already_exists": "All selected names already exist in the config.",
        "names_to_decide": "Names to decide",
        "unknown_query_intro": "{count} name(s) in the query file are not in the {virus} alias config.",
        "all_known": "Every query gene name is already in the alias config. Nothing to decide here.",
        "add_canonical_target": "Add canonical name",
        "add_canonical_caption": "Create a target like `ORF1ab` first if the right one is missing.",
        "llm_suggest": "Suggest with LLM",
        "llm_caption": "Sends names, qualifier values, record IDs, coordinates and canonical names, never sequences. Suggestions pre-fill the dropdowns; you still decide.",
        "ignore_option": "-- exclude / keep raw name --",
        "keep_raw_note": "Kept as the raw name. Nothing is saved.",
        "position_checking": "Checking where each name sits on the reference…",
        "position_progress": "Checking positions · {done} of {total} records aligned",
        "position_unavailable": "Position check unavailable (tblastn could not run). Decide from the names, or use the LLM.",
        "position_summary": "Position check: {match} row(s) match one reference gene, {spans} span several genes, {other} undecided.",
        "position_match": "Position: matches {gene} at {start}–{end} · IoU {iou} · {agree}/{checked} records",
        "position_spans": "Position: spans {count} genes, {first}–{last}. A precursor, not one gene: keep it raw, or add a canonical for it.",
        "position_spans_lifted": (
            "Position: spans {count} genes, {first}–{last}. A precursor, not one gene: its genes are "
            "lifted on their own (Lift genes the annotation is missing), so keeping it raw loses nothing."
        ),
        "position_inside": "Position: lies inside {gene}. A sub-part, not a gene of its own.",
        "position_overlaps": "Position: only partly overlaps {gene} (IoU {iou}).",
        "position_mixed": "Position: the checked records disagree ({agree} of {checked} alike).",
        "position_none": "Position: no reference gene found on {checked} record(s).",
        "position_unplaced": "Position: not checked; the names were not found on the sampled records.",
        "llm_disagrees": "The coordinates say {gene}, so the mapping follows them.",
        "shared_name_warning": "{names} also names other genes in this file. Saved as an alias it would rename them in every later run.",
        "blocked_rows": (
            "Kept raw this run: {rows}. Their only names also appear on genes meant to end up "
            "differently, so mapping them would rename those too. Map them through a more "
            "specific name, or add one in Alias manager."
        ),
        "unknown_prefix": "Unknown",
        "appears_in": "Appears in",
        "map_to_canonical": "Map to canonical",
        "save_aliases": "Save to alias config",
        "save_candidate_help": "Selected values are added to the alias config so future runs recognise them. Unselected values apply to this run only.",
        "decision_summary": "{mapped} mapped · {raw} kept raw",
        "back": "Back",
        "continue": "Run annotation",
        "aliases_saved": "{count} alias(es) saved to config",
        # ── running ───────────────────────────────────────────────────
        "processing": "Processing",
        "running_title": "Running annotation",
        "running_body": "Each query record is routed independently. Records that fail are logged and listed in the results.",
        "starting": "Starting...",
        "done": "Done.",
        # ── step 3 · results ──────────────────────────────────────────
        "run_review": "Run pipeline",
        "results_title": "Results",
        "results_body": "Check run health, open any feature for detail, then export TSV or FASTA.",
        "ref_names_caption": "Showing reference gene names. Start a new run to use canonical names.",
        "new_run": "New run",
        "records_processed": "Records",
        "features_found": "Features",
        "pass_rate": "Pass rate",
        "needs_review": "Needs review",
        "failed_delta": "{count} failed",
        "all_processed": "all processed",
        "passed_count": "{count} passed",
        "review_note": "boundary, coverage or no hit",
        "not_in_sequence_note": "+{count} not in sequence",
        "partial_records_banner": (
            "<b>{partial} of {total} records are partial</b>: they cover only part of the "
            "reference genome. Their {absent} genes outside the sequenced region are marked "
            "<i>Not in sequence</i> and left out of the pass rate and review counts."
        ),
        "not_in_sequence_help": (
            "tblastn found nothing for this gene, and the genes it did find place it outside "
            "this record: the record covers only part of the genome. There is nothing to "
            "review; the gene is left out of the pass rate."
        ),
        "nothing_to_review": "nothing to review",
        # ── annotation check ─────────────────────────────────────────
        "check_confirmed": "Matches reference",
        "check_partial": "Partial",
        "check_fragment": "Fragment",
        "check_low_identity": "Low identity",
        "check_overlong": "Longer than gene",
        "check_replaced": "{verdict} → tblastn",
        "check_looks_like": "{verdict} · looks like {gene}",
        "annotation_check_banner": (
            "<b>Annotation check</b>: {confirmed} of {checked} annotated genes match the reference"
            "{issues}.{replaced} Click a gene on the genome map to compare its annotation with tblastn."
        ),
        "annotation_check_issue": "{count} {label}",
        "annotation_check_replaced": " For {count} of them tblastn's more exact placement is used.",
        "check_section": "Annotation check",
        "check_annotation_line": (
            "Annotation {start}–{end} ({length} nt, reference {ref_length} nt): "
            "{coverage} of the reference protein at {identity} identity."
        ),
        "check_best_match": "The annotated sequence matches reference {gene} far better than {name}.",
        "check_using_tblastn": "Using tblastn {start}–{end} ({length} nt) instead of the annotation.",
        "check_using_annotation": "Using the annotation. tblastn places {gene} at {start}–{end} ({length} nt, {status}).",
        "check_tblastn_same": "tblastn places {gene} at the same position ({status}).",
        "check_tblastn_none": "tblastn found no better placement for {gene} ({status}).",
        "use_annotation": "Use the annotation",
        "use_tblastn": "Use tblastn",
        "check_with_tblastn": "Check with tblastn",
        "check_with_tblastn_help": "Search the whole record with the reference protein and compare.",
        "checking_tblastn": "Searching {record} with tblastn…",
        "processing_error": "{count} query record(s) failed during processing. They are excluded from the pass rate and listed below.",
        "processing_errors": "Processing errors",
        "view_map": "Genome map",
        # ── gene detail (Genome map and Features) ─────────────────────
        "seq_show_all": "Show all",
        "seq_show_less": "Show less",
        "detail_record": "Record",
        "detail_reference": "Reference",
        "detail_not_placed": "not placed on this record",
        "detail_no_reference": "no reference gene of this name",
        "detail_share": "{share} of the reference gene's length",
        "detail_not_aligned": "Taken from the record's annotation as it is, not aligned to the reference protein.",
        "detail_turn_on_check": "Turn on Check annotations against the reference to measure coverage and identity.",
        "detail_coverage": "Coverage",
        "detail_identity": "Identity",
        "detail_cutoff": "Run cut-off: {value}",
        "detail_rescue": "Rescue",
        "detail_raw_hit": "Raw tblastn hit",
        "detail_bit_score": "Bit score",
        "detail_annotated_as": "Annotated as “{name}”",
        "view_export": "Export",
        # ── genome map (ui/genome_map.py) ─────────────────────────────
        "map_matrix_title": "Every record against the reference",
        "map_matrix_caption": (
            "{shown} of {total} records · one row per record, one column per reference gene. "
            "Click a row or a cell to open it below, a gene name to see that gene in every record."
        ),
        "map_matrix_legend": (
            "Green: OK · blue: OK after an adjustment · orange: needs review · red: no hit · "
            "dashed: outside a partial record · orange corner: much shorter than the reference gene · "
            "+n: annotated names the reference does not have."
        ),
        "map_sort": "Sort",
        "map_sort_order": "Sort: run order",
        "map_sort_review": "Sort: needs review first",
        "map_sort_identity": "Sort: lowest identity",
        "map_sort_coverage": "Sort: lowest coverage",
        "map_sort_length": "Sort: shortest against the reference",
        "map_metric_identity": "identity",
        "map_metric_coverage": "coverage",
        "map_metric_length": "length against the reference gene",
        "map_sorted_gene": "Sorted by {gene}'s {metric}, lowest first. Close the gene to sort by each record's lowest instead.",
        "map_sorted_lowest": "Sorted by each record's lowest {metric}, lowest first. Click a gene name to sort by that gene.",
        "map_tone_ok": "OK",
        "map_tone_info": "OK, adjusted",
        "map_tone_warn": "Needs review",
        "map_tone_danger": "No hit",
        "map_tone_neutral": "Not in reference",
        "map_tone_absent": "Not in sequence",
        "map_focus_ref": "reference {start}–{end} · {length} nt",
        "map_focus_median": "median placed length {length} nt",
        "map_export_gene": "Export {gene} · {count}",
        "map_close_focus": "Close",
        "map_focus_check": "{count} record(s) to check for this gene:",
        "map_share_of_ref": "{share} of reference length",
        "map_prev": "Previous",
        "map_next": "Next",
        "map_attention": "Worth a look · {count}",
        "map_tracks_legend": (
            "Ribbons join each reference gene to where it landed on this record. Drag to pan, "
            "pinch or Ctrl + scroll to zoom, double-click to zoom in. For CDS the lanes are reading "
            "frames +1, +2, +3. A dashed orange bar under the record is the raw tblastn hit before "
            "a boundary rescue moved it."
        ),
        "map_short": "Passes, but is {share} of the reference gene's length.",
        "map_short_edge": "{share} of the reference gene's length: the record ends inside this gene.",
        "map_short_raw": (
            "The raw tblastn hit runs {raw_start}–{raw_end}; the stop-codon rescue ended the CDS at {end}. "
            "It still exports with the passing genes."
        ),
        "map_length": "Length",
        "map_shift": "Shift vs reference",
        "map_reverse": "reverse complement",
        "map_method": "Method",
        "map_pick_gene": "Pick a gene on the map above to see its coordinates, checks and sequence here.",
        "map_select_tip": (
            "Tip: click a gene on the map below, its ribbon, or a cell in the matrix above to see that "
            "gene's coordinates, coverage, identity, annotation check and sequence under the map."
        ),
        "map_showing_gene": "Showing {gene} under the map. Click another gene to switch, or {gene} again to close it.",
        "filter_all": "All",
        "method_direct": "Direct",
        "method_tblastn": "tblastn",
        "method_both": "Direct + tblastn",
        "search_record": "Search record ID",
        "health_filter": "Health",
        "record_overview": "Records",
        "all": "all",
        "failed": "Failed",
        "empty": "Empty",
        "health_partial": "Partial",
        "health_no_genes": "No genes found",
        "passed": "Passed",
        "invalid_boundary_help": (
            "tblastn found a strong protein match, but the extracted CDS did not pass the "
            "start/stop/frame checks. start = ATG at the beginning, stop = TAA/TAG/TGA at "
            "the end, frame = length divisible by 3. The rescue action shows which boundary "
            "was moved, e.g. start -12 bp or stop +6 bp."
        ),
        "export": "Export",
        "tsv": "Results table (TSV)",
        "fasta": "Sequences (FASTA)",
        "download_table": "Every feature with coordinates, status and method.",
        "download_display": "TSV · display names",
        "download_raw": "TSV · raw source names",
        "fasta_intro": "Pick genes and quality filters, then generate the downloads.",
        "genes_to_extract": "Genes to extract",
        "genes_picked": "{count} of {total} selected",
        "pick_all": "Select all",
        "pick_none": "Unselect all",
        "pick_hint": "Click a gene on the reference or in the list below it to add or remove it. Numbers are sequences that passed.",
        "pick_hint_empty": "No gene selected. Click genes on the reference, or Select all.",
        "output_format": "Output format",
        "one_fasta": "One file per gene",
        "all_fasta": "All genes in one file",
        "quality_filter": "Quality filter",
        "include_rescued": "Include rescued",
        "include_extrapolated": "Include extrapolated",
        "manual_approve_features": "Include features that need review",
        "manual_approve_help": "Tick review cases you have inspected. Approved features are exported even if they miss the status and quality filters.",
        "approve_column": "Approve",
        "clear_approvals": "Clear approvals",
        "approved_export_count": "{count} reviewed feature(s) approved for FASTA export.",
        "candidate_count": "{count} sequence(s) pass these filters.",
        "generate_fasta": "Generate FASTA",
        "fasta_names": "Sequence names",
        "fasta_names_default": "Default",
        "fasta_names_isolate_host": "Accession_Isolate_Host",
        "fasta_name_fields": "Name fields, in order",
        "fasta_name_fields_help": (
            "Pick the parts of each sequence name in the order they should appear. Isolate falls back "
            "to the strain, Country reads geo_loc_name; both come from the record's source feature. "
            "Spaces and characters that break tree files ( ( ) , ; : ) become underscores. Your choice is remembered for the next run."
        ),
        "fasta_name_separator": "Separator",
        "fasta_name_missing": "Missing value",
        "fasta_name_missing_help": "NA keeps every field in its place; skip leaves an empty field out.",
        "fasta_name_preview": "First names in {file}:",
        "fasta_names_add_gene": "Add Gene to the name fields: with all genes in one file, a record's genes would otherwise share a name.",
        "fasta_names_renamed": "{count} repeated name(s) got a _2, _3 … suffix so every name in a file is unique.",
        "download_all_fasta": "Download all_genes.fasta",
        "no_sequences": "No sequences for `{gene}` passed the filter.",
        "gene_download": "{gene}.fasta · {count}",
        "skipped": "{count} feature(s) skipped by the quality filter or missing a sequence.",
        # ── shared labels ─────────────────────────────────────────────
        "alias_config": "Alias config",
        "loaded": "{count} loaded",
        "yes": "yes",
        "no": "no",
        # ── status labels ─────────────────────────────────────────────
        "status_ok": "OK",
        "status_ok_rescued": "Rescued",
        "status_ok_extrapolated": "Extrapolated",
        "status_ok_no_start_codon": "No start codon",
        "status_ok_gap_filled": "Gap-filled",
        "status_direct": "Direct",
        "status_invalid_boundaries": "Invalid boundary",
        "status_low_coverage": "Low coverage",
        "status_low_identity": "Low identity",
        "status_low_coverage_and_identity": "Low coverage + identity",
        "status_no_hit": "No hit",
        "status_translation_fail": "Translation fail",
        "status_unresolved_name": "Unresolved name",
        "status_ambiguous_name": "Excluded name",
        "status_not_in_reference": "Not in reference",
        "status_not_in_sequence": "Not in sequence",
        "status_overlong_annotation": "Longer than gene",
    },
}
