# Step 1 · Setup — pick the reference (saved or uploaded) and the query, and
# configure the run. The query is read first: the virus it is detected as
# decides which saved reference to suggest (ui/reference_library.py).
import html
import io
import re
import streamlit as st
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from Bio import SeqIO
from app.src.alias.alias_bootstrap import build_seed_alias_config_from_ref
from app.src.features.ref_loader import prepare_reference_features
from app.src.io.genbank_parser import load_genbank_records, load_single_genbank
from app.src.io.run_logger import log_error
from ui.components import _card, _render_callout, _render_page_intro, _render_section_title
from ui.guide import _open_guide
from ui.i18n import _t
from ui.services import _load_excluded_names, _record_metadata_candidates, _save_upload, _scan_unknown_names, _scan_unknown_ref_names, _suggest_virus_name
from ui.reference_library import (
    DETECT_BYTES,
    detect_virus_in_bytes,
    list_references,
    reference_file,
    remove_reference,
    suggest_reference,
)
from ui.state import REGISTRY_PATH
from ui import genome_map


UPLOAD_NEW = "__upload__"
# Record lengths come from the LOCUS lines, so the preview never parses the query.
LOCUS_LENGTH = re.compile(rb"^LOCUS\s+\S+\s+(\d+)\s+bp", re.MULTILINE)
# Below this share of the reference length a query record counts as partial.
PARTIAL_SHARE = 0.6
# (virus_name, records matched, records checked)
VirusMatch = Tuple[str, int, int]


def _clear_crawler_query() -> None:
    st.session_state.crawler_query_path = None
    st.session_state.crawler_query_label = ""


def _forget_reference(ref_id: str) -> None:
    remove_reference(ref_id)
    st.session_state.ref_choice = UPLOAD_NEW


def _query_virus(query_file, crawled_query_path: Optional[str]) -> Tuple[Optional[str], Optional[VirusMatch]]:
    """(cache key, detected virus) for the current query; detection runs once per file."""
    if query_file is not None:
        key = f"upload:{getattr(query_file, 'file_id', None) or query_file.name}"
    elif crawled_query_path:
        key = f"path:{crawled_query_path}"
    else:
        return None, None
    cache = st.session_state.query_virus_cache
    if key not in cache:
        try:
            if query_file is not None:
                head = query_file.getvalue()[:DETECT_BYTES]
            else:
                with open(crawled_query_path, "rb") as handle:
                    head = handle.read(DETECT_BYTES)
            cache[key] = detect_virus_in_bytes(head, REGISTRY_PATH)
        except Exception as e:  # a convenience only: never block the upload
            log_error("detecting query virus", e)
            cache[key] = None
    return key, cache[key]


def _reference_label(entry: Dict) -> str:
    label = _t(
        "ref_option",
        virus=entry.get("virus_name") or _t("unknown_virus"),
        id=entry["id"],
        length=f"{entry.get('length', 0):,}",
        genes=entry.get("genes", 0),
    )
    return f"{label} · {_t('ref_default')}" if entry.get("default") else label


def _render_reference_picker(query_key: Optional[str], query_virus: Optional[VirusMatch]):
    """Saved-reference dropdown plus uploader. Returns (saved entry, uploaded file)."""
    saved = list_references()
    if not saved:
        ref_file = st.file_uploader(
            "Reference GenBank (.gb)", type=["gb", "gbk"], key="ref_upload", label_visibility="collapsed"
        )
        st.caption(_t("ref_saved_hint"))
        return None, ref_file

    by_id = {entry["id"]: entry for entry in saved}
    suggestion = suggest_reference(query_virus[0] if query_virus else None, saved)
    # Pre-select the suggestion once per query file, unless a reference was
    # already uploaded by hand; after that the user's choice stands.
    if (
        suggestion
        and st.session_state.ref_suggested_for != query_key
        and not st.session_state.get("ref_upload")
    ):
        st.session_state.ref_choice = suggestion["id"]
        st.session_state.ref_suggested_for = query_key
    if st.session_state.get("ref_choice") not in (*by_id, UPLOAD_NEW):
        st.session_state.ref_choice = UPLOAD_NEW

    choice = st.selectbox(
        _t("saved_reference"),
        [*by_id, UPLOAD_NEW],
        format_func=lambda value: _t("ref_upload_new") if value == UPLOAD_NEW else _reference_label(by_id[value]),
        key="ref_choice",
        label_visibility="collapsed",
    )
    if choice == UPLOAD_NEW:
        ref_file = st.file_uploader(
            "Reference GenBank (.gb)", type=["gb", "gbk"], key="ref_upload", label_visibility="collapsed"
        )
        if query_virus and not suggestion:
            st.caption(_t("ref_none_for_virus", virus=query_virus[0]))
        return None, ref_file

    entry = by_id[choice]
    if query_virus and entry.get("virus_name") and entry["virus_name"] != query_virus[0]:
        _render_callout(
            html.escape(_t("ref_virus_mismatch", ref_virus=entry["virus_name"], query_virus=query_virus[0])),
            tone="warn",
            icon="!",
        )
    elif suggestion and entry["id"] == suggestion["id"]:
        _render_callout(
            html.escape(_t(
                "ref_suggested",
                virus=query_virus[0],
                kind=_t("ref_default") if entry.get("default") else _t("ref_most_recent"),
            )),
            tone="ok",
            icon="✓",
        )
    with st.container(horizontal=True, horizontal_alignment="distribute", vertical_alignment="center"):
        st.caption(entry.get("description", ""))
        st.button(
            _t("forget_reference"),
            icon=":material/delete:",
            type="tertiary",
            key="forget_reference",
            help=_t("forget_reference_help"),
            on_click=_forget_reference,
            args=(entry["id"],),
        )
    return entry, None


def _reference_preview(saved_ref: Optional[Dict], ref_file) -> Optional[Dict]:
    """The chosen reference's genes as the run will read them, cached per file."""
    if saved_ref:
        key = f"saved:{saved_ref['id']}"

        def load():
            return load_single_genbank(reference_file(saved_ref))
    elif ref_file is not None:
        key = f"upload:{getattr(ref_file, 'file_id', None) or ref_file.name}"

        def load():
            text = ref_file.getvalue().decode("utf-8", errors="replace")
            records = list(SeqIO.parse(io.StringIO(text), "genbank"))
            if len(records) != 1:
                raise ValueError(f"Expected 1 record, found {len(records)} in {ref_file.name}")
            return records[0]
    else:
        return None

    cache = st.session_state.setdefault("ref_preview_cache", {})
    if key not in cache:
        try:
            record = load()
            features, feature_type, alias_path, virus, _ = prepare_reference_features(
                ref_record=record, alias_config_arg=None, alias_registry_arg=str(REGISTRY_PATH),
            )
            cache[key] = {
                "ref": genome_map.reference_payload(record.id, len(record.seq), features, feature_type),
                "feature_type": feature_type,
                "genes": len(features),
                "alias": Path(alias_path).name if alias_path else None,
                "raw": [f.get("raw_name") or f.get("name") for f in features if f.get("name_source") == "raw"],
            }
        except Exception as e:  # shown in the preview; the run reports it again
            log_error("previewing the reference", e)
            cache[key] = {"error": str(e)}
    return cache[key]


def _query_lengths(query_key: Optional[str], query_file, crawled_path: Optional[str]) -> List[int]:
    if query_key is None:
        return []
    cache = st.session_state.setdefault("query_length_cache", {})
    if query_key not in cache:
        try:
            data = query_file.getvalue() if query_file is not None else Path(crawled_path).read_bytes()
            cache[query_key] = [int(length) for length in LOCUS_LENGTH.findall(data)]
        except OSError as e:
            log_error("reading query record lengths", e)
            cache[query_key] = []
    return cache[query_key]


def _render_reference_preview(preview: Dict, lengths: List[int]) -> None:
    with _card("ref_preview"):
        if preview.get("error"):
            _render_section_title(_t("ref_preview_title"))
            _render_callout(html.escape(_t("ref_preview_error", error=preview["error"])), tone="warn", icon="!")
            return
        ref = preview["ref"]
        _render_section_title(
            _t("ref_preview_title"),
            _t(
                "ref_preview_caption",
                count=preview["genes"],
                level=preview["feature_type"],
                source=preview["alias"] or _t("ref_preview_no_alias"),
            ),
        )
        genome_map.render({"view": "reference", "ref": ref}, "vl_map_reference")
        notes = []
        if preview["raw"]:
            notes.append(_t("ref_preview_raw", count=len(preview["raw"]), names=", ".join(preview["raw"][:6])))
        if lengths:
            partial = sum(1 for length in lengths if length < PARTIAL_SHARE * ref["length"])
            notes.append(_t(
                "ref_preview_query",
                count=f"{len(lengths):,}",
                full=f"{len(lengths) - partial:,}",
                partial=f"{partial:,}",
                share=f"{PARTIAL_SHARE:.0%}",
            ))
        for note in notes:
            st.caption(note)


def stage_upload():
    _render_page_intro(
        _t("run_setup"),
        _t("upload_title"),
        _t("upload_body"),
        guide=_open_guide,
    )

    col_ref, col_query = st.columns(2, gap="medium")
    with col_query, _card("query"):
        _render_section_title(_t("query_records"), _t("query_caption"))
        crawled_query_path = st.session_state.get("crawler_query_path")
        if crawled_query_path:
            _render_callout(
                f"<b>{html.escape(_t('crawler_query_ready'))}</b><br>"
                f"<span class='vl-mono'>{html.escape(Path(crawled_query_path).name)}</span>",
                tone="ok",
                icon="✓",
            )
            st.button(_t("clear_crawler_query"), key="clear_crawler_query", on_click=_clear_crawler_query)
            query_file = None
        else:
            query_file = st.file_uploader("Query GenBank (.gb)", type=["gb", "gbk"], label_visibility="collapsed")
        query_key, query_virus = _query_virus(query_file, crawled_query_path)
        if query_virus:
            virus, matched, checked = query_virus
            st.caption(_t("query_detected", virus=virus, matched=matched, checked=checked))
    with col_ref, _card("ref"):
        _render_section_title(_t("reference_record"), _t("reference_caption"))
        saved_ref, ref_file = _render_reference_picker(query_key, query_virus)

    preview = _reference_preview(saved_ref, ref_file)
    if preview:
        _render_reference_preview(preview, _query_lengths(query_key, query_file, crawled_query_path))

    with _card("options"):
        _render_section_title(_t("run_options"), _t("run_options_caption"))
        st.session_state.use_ref_names = st.toggle(
            _t("use_ref_names"),
            value=False,
            help=_t("use_ref_names_help"),
        )
        st.session_state.lift_missing = st.toggle(
            _t("lift_missing"),
            value=st.session_state.lift_missing,
            help=_t("lift_missing_help"),
        )
        st.session_state.check_annotations = st.toggle(
            _t("check_annotations"),
            value=st.session_state.check_annotations,
            help=_t("check_annotations_help"),
        )
        with st.expander(_t("lifting_thresholds"), expanded=False):
            st.caption(_t("threshold_caption"))
            c1, c2, c3, c4 = st.columns(4)
            st.session_state.min_coverage   = c1.number_input(_t("min_coverage"),  0.0, 1.0, 0.5, 0.05)
            st.session_state.min_identity   = c2.number_input(_t("min_identity"),  0.0, 1.0, 0.3, 0.05)
            st.session_state.evalue         = c3.number_input(_t("evalue"),       value=1e-5, format="%.0e")
            st.session_state.rescue_window  = c4.number_input(_t("rescue_window"), 10,  500,   200,   10)
        with st.expander(_t("file_requirements"), expanded=False):
            st.markdown(_t("file_requirements_body"))

    ready = (saved_ref or ref_file) and (query_file or st.session_state.get("crawler_query_path"))
    with st.container(horizontal=True, horizontal_alignment="distribute", vertical_alignment="center"):
        if ready:
            ref_label = saved_ref["id"] if saved_ref else ref_file.name
            query_label = query_file.name if query_file else Path(st.session_state.crawler_query_path).name
            st.caption(_t("ready_to_run", ref=ref_label, query=query_label))
        else:
            st.caption(_t("add_files_hint"))
        run_clicked = st.button(
            _t("run_button"),
            icon=":material/arrow_forward:",
            disabled=not ready,
            type="primary",
        )

    if run_clicked:
        # persist files to temp dir
        if st.session_state.tmp is None:
            st.session_state.tmp = tempfile.TemporaryDirectory()

        with st.spinner(_t("loading_files")):
            try:
                ref_path = reference_file(saved_ref) if saved_ref else _save_upload(ref_file)
                # Remembered when the run starts (stages/running.py).
                st.session_state.ref_source_path = str(ref_path)
                st.session_state.ref_saved_id = saved_ref["id"] if saved_ref else None
                if query_file:
                    query_path = _save_upload(query_file)
                else:
                    query_path = Path(st.session_state.crawler_query_path)

                ref_record    = load_single_genbank(ref_path)
                query_records = load_genbank_records(query_path)

                ref_features, ref_feature_type, alias_config_path, virus_name, alias_lookup = (
                    prepare_reference_features(
                        ref_record=ref_record,
                        alias_config_arg=None,
                        alias_registry_arg=str(REGISTRY_PATH),
                    )
                )

                if alias_config_path is None:
                    virus_guess = _suggest_virus_name(ref_record)
                    seed_config = build_seed_alias_config_from_ref(
                        ref_record=ref_record,
                        ref_features=ref_features,
                        virus_name=virus_guess,
                    )

                    st.session_state.ref_record        = ref_record
                    st.session_state.query_records     = query_records
                    st.session_state.ref_features      = ref_features
                    st.session_state.ref_feature_type  = ref_feature_type
                    st.session_state.alias_lookup      = {}
                    st.session_state.alias_config_path = None
                    st.session_state.virus_name        = virus_guess
                    st.session_state.canonical_list    = sorted(seed_config["canonical_names"])
                    st.session_state.unknown_names     = {}
                    st.session_state.unknown_ref_names = []
                    st.session_state.bootstrap_alias_config = seed_config
                    st.session_state.bootstrap_virus_name = virus_guess
                    st.session_state.bootstrap_keywords = virus_guess
                    st.session_state.bootstrap_suggestions = []
                    st.session_state.bootstrap_diagnostics = {}
                    st.session_state.virus_review_metadata = _record_metadata_candidates(ref_record)
                    st.session_state.virus_review_guess = virus_guess
                    st.session_state.stage = "virus_review"
                    st.rerun()

                # canonical list for resolver dropdowns
                canonical_list = sorted(set(alias_lookup.values())) if alias_lookup else []

                # scan for unknown names in query records AND in ref
                excluded = _load_excluded_names(alias_config_path)
                unknown     = _scan_unknown_names(query_records, alias_lookup, excluded, ref_feature_type)
                unknown_ref = _scan_unknown_ref_names(ref_features, excluded)
            except Exception as e:
                log_error("loading UI inputs", e)
                st.error(f"{_t('load_error')}: {e}")
                return

        # store to session state
        st.session_state.ref_record        = ref_record
        st.session_state.query_records     = query_records
        st.session_state.ref_features      = ref_features
        st.session_state.ref_feature_type  = ref_feature_type
        st.session_state.alias_lookup      = alias_lookup
        st.session_state.alias_config_path = alias_config_path
        st.session_state.virus_name        = virus_name
        st.session_state.canonical_list    = canonical_list
        st.session_state.unknown_names     = unknown
        st.session_state.unknown_ref_names = unknown_ref

        if unknown or unknown_ref:
            st.session_state.stage = "resolve"
        else:
            st.session_state.stage = "running"

        st.rerun()
