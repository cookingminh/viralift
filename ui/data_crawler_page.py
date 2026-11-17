from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd
import streamlit as st

from gbcrawler import fetch as fetch_mod
from gbcrawler import split as split_mod
from ui.components import _card, _render_page_intro, _render_section_title, _render_stats
from ui.guide import _open_guide
from ui.state import REGISTRY_PATH, ROOT


DEFAULT_OUT_DIR = ROOT / "output" / "gbcrawler"
DEFAULT_LEDGER = ROOT / "output" / "gbcrawler_ledger.txt"


FALLBACK_VIRUSES = {
    "PRRSV": "Porcine reproductive and respiratory syndrome virus",
    "FMDV": "Foot-and-mouth disease virus",
    "PEDV": "Porcine epidemic diarrhea virus",
}

BY_QUERY = "By NCBI query"
BY_ACCESSION = "By accession list"


def _sync_crawler_credentials() -> None:
    """Copy the NCBI inputs into plain state so they survive leaving this page."""
    st.session_state.crawler_email_value = st.session_state.get("crawler_email_input", "")
    st.session_state.crawler_api_key_value = st.session_state.get("crawler_api_key_input", "")


def _virus_options(registry_path: Path) -> Dict[str, str]:
    try:
        registry = split_mod.load_registry(registry_path)
    except Exception:
        return dict(FALLBACK_VIRUSES)

    options = {}
    for name, keywords in registry:
        organism = max(keywords, key=len) if keywords else name
        options[name] = organism.strip()
    return options or dict(FALLBACK_VIRUSES)


def _parse_accessions(raw: str) -> List[str]:
    accessions = []
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        accessions.extend(part.strip() for part in line.replace(",", " ").split())
    return [acc for acc in accessions if acc]


def _dataset_type_clause(dataset_type: str) -> Optional[str]:
    if dataset_type == "Complete genomes":
        return "complete genome[Title]"
    if dataset_type == "Gene records / fragments":
        return "NOT complete genome[Title]"
    return None


def build_ncbi_query(
    organism: str,
    dataset_type: str,
    length: Optional[Tuple[int, int]],
    dates,
    region: str,
    extra: str,
) -> str:
    parts = []
    if organism:
        parts.append(f'"{organism}"[Organism]')

    dataset_clause = _dataset_type_clause(dataset_type)
    if dataset_clause:
        parts.append(dataset_clause)

    if length:
        lo, hi = length
        parts.append(f'("{lo}"[SLEN] : "{hi}"[SLEN])')

    if dates:
        d0, d1 = dates
        parts.append(f'("{d0:%Y/%m/%d}"[PDAT] : "{d1:%Y/%m/%d}"[PDAT])')

    if region:
        parts.append(f'"{region}"[All Fields]')

    if extra and extra.strip():
        parts.append(extra.strip())

    return " AND ".join(parts)


def _need_email(email: str) -> bool:
    if not email.strip():
        st.error("Enter an email address first. NCBI requires it for Entrez requests.")
        return True
    return False


def _crawl_signature(mode: str, query: str, accessions: List[str], db: str, retmax: int) -> str:
    payload = {
        "mode": mode,
        "query": query.strip(),
        "accessions": sorted(accessions),
        "db": db,
        "retmax": int(retmax),
    }
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=True)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _use_species_file_as_query(file_path: Path, label: str) -> None:
    st.session_state.crawler_query_path = str(file_path)
    st.session_state.crawler_query_label = label
    st.session_state.app_mode = "Run pipeline"
    st.session_state.stage = "upload"
    st.toast(f"Selected `{file_path.name}` as query input.")


def _render_query_builder(viruses: Dict[str, str]) -> str:
    top_left, top_right = st.columns([2, 1])
    with top_left:
        labels = list(viruses.keys()) + ["Other / custom"]
        selected_virus = st.selectbox("Virus", labels, key="crawler_virus")
        if selected_virus == "Other / custom":
            organism = st.text_input(
                "NCBI organism name",
                placeholder="e.g. Classical swine fever virus",
                key="crawler_custom_organism",
            )
        else:
            organism = viruses[selected_virus]
            st.caption(f'NCBI organism query: `"{organism}"[Organism]`')
    with top_right:
        dataset_type = st.selectbox(
            "Dataset type",
            ["Complete genomes", "Gene records / fragments", "Both"],
            key="crawler_dataset_type",
        )

    st.markdown("**Optional filters**")
    f1, f2, f3 = st.columns(3)
    with f1:
        use_len = st.checkbox("Length range", key="crawler_use_length")
        length = None
        if use_len:
            length = st.slider(
                "Sequence length",
                0,
                35000,
                (14000, 16000),
                step=500,
                key="crawler_length",
            )
    with f2:
        use_date = st.checkbox("Publication date", key="crawler_use_date")
        dates = None
        if use_date:
            picked_dates = st.date_input(
                "Date range",
                value=(date(2020, 1, 1), date.today()),
                max_value=date.today(),
                key="crawler_dates",
            )
            if isinstance(picked_dates, (tuple, list)) and len(picked_dates) == 2:
                dates = picked_dates
    with f3:
        region_choice = st.selectbox(
            "Country",
            ["Any (global)", "Vietnam", "Custom country…"],
            key="crawler_region_choice",
        )
        region = ""
        if region_choice == "Vietnam":
            region = "Vietnam"
        elif region_choice == "Custom country…":
            region = st.text_input("Country name", placeholder="e.g. China")
        if region:
            st.caption(
                "⚠️ Country filter is text-based and approximate on nuccore. "
                "For exact geographic subsets, filter by the /country "
                "qualifier after download (or use NCBI Virus)."
            )

    extra = st.text_input(
        "Extra NCBI condition",
        placeholder='e.g. NOT partial[Title]',
        key="crawler_extra",
    )
    query = build_ncbi_query(organism, dataset_type, length, dates, region, extra)

    with st.expander("Edit the query manually"):
        use_manual_query = st.checkbox(
            "Use manual query override",
            value=False,
            key="crawler_use_manual_query",
            help="Leave this off to use the query built from the virus and filters above.",
        )
        manual_query = st.text_area(
            "Override query",
            value=query,
            height=90,
            key="crawler_manual_query",
            disabled=not use_manual_query,
        )
        if use_manual_query and manual_query.strip():
            query = manual_query.strip()

    st.markdown("**NCBI query preview**")
    st.code(query or "No query yet.", language="text")
    return query


def page_data_crawler() -> None:
    _render_page_intro(
        "Data crawler",
        "Fetch genomes from NCBI",
        (
            "Build a GenBank dataset from NCBI, split it by virus, then send "
            "one species file into the pipeline as query input."
        ),
        show_stages=False,
        guide=_open_guide,
    )

    registry_path = REGISTRY_PATH
    viruses = _virus_options(registry_path)

    with _card("ncbi"):
        with st.container(horizontal=True, horizontal_alignment="distribute", vertical_alignment="top"):
            _render_section_title("NCBI account", "Entrez requires an email; an API key raises the rate limit.")
            with st.popover("Advanced settings", icon=":material/tune:"):
                db = st.text_input("Database", value="nuccore", key="crawler_db")
                out_dir = st.text_input(
                    "Output folder",
                    value=str(DEFAULT_OUT_DIR),
                    key="crawler_out_dir_input",
                )
                use_ledger = st.checkbox("Use dedup ledger", value=True, key="crawler_use_ledger")
                ledger_path = st.text_input(
                    "Ledger file",
                    value=str(DEFAULT_LEDGER),
                    disabled=not use_ledger,
                    key="crawler_ledger_path",
                )
        email_col, key_col = st.columns(2)
        email = email_col.text_input(
            "NCBI email",
            value=st.session_state.get("crawler_email_value", ""),
            key="crawler_email_input",
            placeholder="you@lab.org",
            on_change=_sync_crawler_credentials,
        )
        api_key = key_col.text_input(
            "NCBI API key",
            value=st.session_state.get("crawler_api_key_value", ""),
            key="crawler_api_key_input",
            type="password",
            placeholder="optional",
            on_change=_sync_crawler_credentials,
        )

    query = ""
    accessions: List[str] = []
    with _card("crawl_build"):
        _render_section_title("Build the input dataset", "Search NCBI by organism and filters, or paste accessions.", step=1)
        mode = st.segmented_control(
            "Input source",
            [BY_QUERY, BY_ACCESSION],
            default=BY_QUERY,
            required=True,
            label_visibility="collapsed",
            key="crawler_mode",
        )
        if mode == BY_QUERY:
            query = _render_query_builder(viruses)
        else:
            uploaded = st.file_uploader("Accession file (.txt/.csv)", type=["txt", "csv"])
            pasted = st.text_area(
                "Or paste accessions",
                height=140,
                placeholder="PP209408.1\nAF176348.2",
                key="crawler_accessions_text",
            )
            raw = pasted
            if uploaded is not None:
                raw = uploaded.getvalue().decode("utf-8", "ignore") + "\n" + raw
            accessions = _parse_accessions(raw)
            st.caption(f"{len(accessions)} accession(s) detected.")

        retmax = st.number_input(
            "Max records to fetch",
            min_value=1,
            max_value=100000,
            value=1000,
            step=100,
            key="crawler_retmax",
        )

    current_signature = _crawl_signature(mode, query, accessions, db, int(retmax))

    with _card("crawl_run"):
        _render_section_title("Preview and crawl", "Check the match count before downloading.", step=2)
        with st.container(horizontal=True):
            count_clicked = st.button(
                "Count records",
                icon=":material/tag:",
                disabled=mode != BY_QUERY,
            )
            crawl_clicked = st.button(
                "Crawl GenBank and split",
                icon=":material/cloud_download:",
                type="primary",
            )

        if count_clicked and not _need_email(email):
            if not query.strip():
                st.error("Build or enter an NCBI query first.")
            else:
                fetch_mod.configure(email, api_key or None)
                with st.spinner("Counting matching records on NCBI..."):
                    try:
                        st.session_state.crawler_count_result = fetch_mod.count_query(
                            query,
                            db=db,
                            api_key=api_key or None,
                        )
                        st.session_state.crawler_count_signature = current_signature
                    except Exception as exc:
                        st.session_state.crawler_count_result = None
                        st.session_state.crawler_count_signature = None
                        st.error(f"NCBI count failed: {exc}")

        if (
            st.session_state.crawler_count_result is not None
            and st.session_state.get("crawler_count_signature") == current_signature
        ):
            count = st.session_state.crawler_count_result
            tone = st.warning if count > 50000 else st.success
            tone(f"{count:,} record(s) match this query.")

        if crawl_clicked and not _need_email(email):
            if mode == BY_QUERY and not query.strip():
                st.error("Build or enter an NCBI query first.")
            elif mode == BY_ACCESSION and not accessions:
                st.error("Provide at least one accession.")
            else:
                out = Path(out_dir)
                out.mkdir(parents=True, exist_ok=True)
                raw_path = out / "raw_combined.gb"
                try:
                    fetch_mod.configure(email, api_key or None)
                    progress = st.progress(0.0, text="Starting NCBI download...")
                    with open(raw_path, "w", encoding="utf-8") as handle:
                        if mode == BY_QUERY:
                            fetched = fetch_mod.fetch_from_query(
                                query,
                                handle,
                                db=db,
                                retmax=int(retmax),
                                api_key=api_key or None,
                                quiet=True,
                            )
                        else:
                            fetched = fetch_mod.fetch_from_accessions(
                                accessions,
                                handle,
                                db=db,
                                api_key=api_key or None,
                                quiet=True,
                            )
                    progress.progress(0.75, text=f"Downloaded {fetched} record(s). Splitting...")

                    registry = split_mod.load_registry(registry_path)
                    seen = (
                        split_mod.load_ledger(Path(ledger_path))
                        if use_ledger and ledger_path
                        else set()
                    )
                    summary = split_mod.split_genbank(raw_path, registry, out, seen=seen)
                    if use_ledger and ledger_path:
                        split_mod.append_ledger(Path(ledger_path), summary["new_accessions"])
                    progress.progress(1.0, text="Done.")
                    st.session_state.crawler_summary = summary
                    st.session_state.crawler_out_dir = str(out)
                    st.session_state.crawler_summary_signature = current_signature
                except Exception as exc:
                    st.error(f"Crawl failed: {exc}")

    summary = st.session_state.crawler_summary
    if not summary:
        return
    if st.session_state.get("crawler_summary_signature") != current_signature:
        st.info("The crawler output below belongs to a previous query. Run `Crawl GenBank and split` again for the current query.")
        return

    with _card("crawl_output"):
        _render_section_title("Use the crawler output", "Download a species file or send it to the pipeline.", step=3)
        _render_stats([
            {"label": "Total fetched", "value": summary["total"]},
            {"label": "New records", "value": summary["new"], "tone": "primary"},
            {"label": "Duplicate in batch", "value": summary["dup_in_batch"]},
            {"label": "Duplicate in ledger", "value": summary["dup_in_ledger"]},
        ])

        if summary["counts"]:
            st.markdown("**Species files**")
            for index, (key, count) in enumerate(sorted(summary["counts"].items())):
                file_path = Path(summary["files"][key])
                label = key if key != split_mod.UNMATCHED else "Unmatched records"
                with _card(f"species_{index}", horizontal=True, vertical_alignment="center"):
                    st.markdown(f"**{label}** · {count} record(s) · `{file_path.name}`")
                    if file_path.exists():
                        st.download_button(
                            "Download .gb",
                            data=file_path.read_bytes(),
                            file_name=file_path.name,
                            icon=":material/download:",
                            key=f"crawler_download_{file_path.name}",
                            on_click="ignore",
                        )
                        st.button(
                            "Use as query",
                            icon=":material/arrow_forward:",
                            type="primary",
                            key=f"crawler_use_{file_path.name}",
                            on_click=_use_species_file_as_query,
                            args=(file_path, label),
                        )

        manifest_path = Path(summary["manifest"])
        if manifest_path.exists():
            with st.expander("manifest.csv", expanded=False):
                manifest = pd.read_csv(manifest_path)
                st.dataframe(manifest, width="stretch", height=320)
                st.download_button(
                    "Download manifest.csv",
                    data=manifest_path.read_bytes(),
                    file_name="manifest.csv",
                    on_click="ignore",
                )
