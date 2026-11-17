# Alias-manager page for the Streamlit UI.
#
# Layout: registered viruses on the left, the selected virus's editor on the
# right. Lists (aliases, keywords, excluded names) are selectable pills — click
# to select, then remove — and additions go through small forms. The Reference
# genomes tab manages the virus's saved references (ui/reference_library.py),
# which Run pipeline offers and suggests.
#
# Save model (single, predictable rule): every edit persists immediately and writes
# a timestamped backup. Destructive actions (delete canonical / delete virus) ask
# for confirmation first. Success is surfaced through a flash toast that survives the
# rerun, so an action never looks like "nothing happened".

import html
import json
import tempfile
from pathlib import Path
from typing import Dict, Iterable, List

import streamlit as st
import streamlit.components.v1 as components

from app.src.alias.alias_manager import (
    alias_config_to_tables,
    list_registry_entries,
    load_alias_config as manager_load_alias_config,
    move_excluded_to_alias,
    remove_registry_entry,
    resolve_config_path,
    save_alias_config as manager_save_alias_config,
    update_registry_entry,
    validate_alias_config,
)
from app.src.alias.alias_registry import get_detected_virus_name
from app.src.alias.gene_alias import get_excluded_names, normalize_text
from app.src.features.ref_loader import prepare_reference_features
from app.src.io.genbank_parser import load_single_genbank
from ui.components import _card, _render_nav_label, _render_page_intro, _render_section_title, _render_stats
from ui.guide import _open_guide
from ui.reference_library import (
    list_references,
    reference_file,
    references_for,
    remove_reference,
    rename_virus,
    save_reference,
    set_default,
)
from ui.state import REGISTRY_PATH, ROOT


# ── Flash feedback ──────────────────────────────────────────────────────
# st.success() written right before st.rerun() is discarded by the rerun, so the
# user never sees it. Stash the message and show it as a toast on the next run.

def _flash(message: str, icon: str = "✅") -> None:
    st.session_state["alias_manager_flash"] = (message, icon)


def _render_flash() -> None:
    payload = st.session_state.pop("alias_manager_flash", None)
    if payload:
        message, icon = payload
        st.toast(message, icon=icon)


def _scroll_to_top_once() -> None:
    if not st.session_state.pop("alias_manager_scroll_top", False):
        return
    components.html(
        """
        <script>
        const root = window.parent;
        root.scrollTo({ top: 0, behavior: "smooth" });
        </script>
        """,
        height=0,
    )


@st.dialog("Virus deleted")
def _delete_success_dialog(message: str) -> None:
    st.success(message)
    if st.button("OK", type="primary", width="stretch"):
        st.session_state.pop("alias_manager_delete_success", None)
        st.rerun()


@st.dialog("Delete virus?")
def _confirm_delete_virus_dialog(entry: Dict, archive_alias_config: bool) -> None:
    virus_name = entry.get("virus_name") or entry.get("alias_config") or "this virus"
    st.warning(f"Are you sure you want to delete `{virus_name}`?")
    st.caption(
        "This removes the virus from the Alias Manager registry. "
        "Auto-detection will no longer select it."
    )
    if archive_alias_config:
        st.caption("The active alias config file will also be archived and removed.")

    cancel_col, delete_col = st.columns(2)
    if cancel_col.button("Cancel", width="stretch"):
        st.rerun()
    if delete_col.button("Yes, delete virus", type="primary", width="stretch"):
        _delete_virus_entry(entry, archive_alias_config)


@st.dialog("Delete canonical?")
def _confirm_delete_canonical_dialog(config_path: Path, config: Dict, canonical: str) -> None:
    aliases = config.get("canonical_names", {}).get(canonical, []) or []
    st.warning(f"Delete canonical `{canonical}` and its {len(aliases)} alias(es)?")
    st.caption("This cannot be undone from the UI, but a backup is written first.")
    cancel_col, delete_col = st.columns(2)
    if cancel_col.button("Cancel", width="stretch"):
        st.rerun()
    if delete_col.button("Yes, delete canonical", type="primary", width="stretch"):
        _delete_canonical_now(config_path, config, canonical)


def _split_lines(raw_text: str) -> List[str]:
    values: List[str] = []
    seen = set()
    for line in (raw_text or "").splitlines():
        value = line.strip()
        key = normalize_text(value)
        if key and key not in seen:
            seen.add(key)
            values.append(value)
    return values


def _dedupe_values(values: Iterable[str]) -> List[str]:
    result: List[str] = []
    seen = set()
    for value in values:
        item = str(value or "").strip()
        key = normalize_text(item)
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(item)
    return sorted(result, key=normalize_text)


def _deepcopy_config(config: Dict) -> Dict:
    return json.loads(json.dumps(config))


def _checkbox_list(
    values: List[str],
    key_prefix: str,
    empty_message: str,
) -> List[str]:
    if not values:
        st.caption(empty_message)
        return []

    selected = st.pills(
        "Select to remove",
        list(dict.fromkeys(values)),
        selection_mode="multi",
        key=key_prefix,
        label_visibility="collapsed",
    )
    return list(selected or [])


def _delete_aliases(config_path: Path, config: Dict, canonical: str, aliases: List[str]) -> None:
    st.session_state.alias_manager_open_canonical = canonical
    updated = _deepcopy_config(config)
    selected_norms = {normalize_text(alias) for alias in aliases}
    updated["canonical_names"][canonical] = [
        alias
        for alias in updated.get("canonical_names", {}).get(canonical, [])
        if normalize_text(alias) not in selected_norms
    ]
    manager_save_alias_config(config_path, updated)
    _flash(f"Removed {len(aliases)} alias(es) from {canonical}.", icon="🗑️")
    st.rerun()


def _add_aliases(config_path: Path, config: Dict, canonical: str, aliases: List[str]) -> None:
    st.session_state.alias_manager_open_canonical = canonical
    updated = _deepcopy_config(config)
    existing = updated.setdefault("canonical_names", {}).setdefault(canonical, [])
    existing_norms = {normalize_text(alias) for alias in existing}
    added = []
    for alias in aliases:
        key = normalize_text(alias)
        if key and key not in existing_norms:
            existing.append(alias)
            existing_norms.add(key)
            added.append(alias)

    if not added:
        st.info("No new alias to add.")
        return

    manager_save_alias_config(config_path, updated)
    _flash(f"Added {len(added)} alias(es) to {canonical}.")
    st.rerun()


def _add_canonical(
    config_path: Path,
    config: Dict,
    canonical: str,
    aliases: List[str],
) -> None:
    canonical = canonical.strip()
    if not canonical:
        st.warning("Add a canonical name first.")
        return

    updated = _deepcopy_config(config)
    canonical_names = updated.setdefault("canonical_names", {})
    existing_key = next(
        (
            name
            for name in canonical_names
            if normalize_text(name) == normalize_text(canonical)
        ),
        None,
    )
    target = existing_key or canonical
    existing = canonical_names.setdefault(target, [])
    existing_norms = {normalize_text(alias) for alias in existing}

    for alias in aliases:
        key = normalize_text(alias)
        if key and key not in existing_norms:
            existing.append(alias)
            existing_norms.add(key)

    st.session_state.alias_manager_open_canonical = target
    manager_save_alias_config(config_path, updated)
    _flash(f"{'Updated' if existing_key else 'Added'} canonical {target}.")
    st.rerun()


def _delete_canonical_now(config_path: Path, config: Dict, canonical: str) -> None:
    updated = _deepcopy_config(config)
    updated.setdefault("canonical_names", {}).pop(canonical, None)
    manager_save_alias_config(config_path, updated)
    st.session_state.pop("alias_manager_open_canonical", None)
    _flash(f"Deleted canonical {canonical}.", icon="🗑️")
    st.rerun()


def _delete_names(config_path: Path, config: Dict, field: str, names: List[str], label: str) -> None:
    updated = _deepcopy_config(config)
    selected_norms = {normalize_text(name) for name in names}
    source_names = get_excluded_names(updated) if field == "excluded_names" else updated.get(field, [])
    updated[field] = [
        name
        for name in source_names
        if normalize_text(name) not in selected_norms
    ]
    if field == "excluded_names":
        updated.pop("ignored_names", None)
        updated.pop("ambiguous_names", None)
    manager_save_alias_config(config_path, updated)
    _flash(f"Removed {len(names)} {label}(s).", icon="🗑️")
    st.rerun()


def _add_excluded(config_path: Path, config: Dict, names: List[str]) -> None:
    updated = _deepcopy_config(config)
    existing = get_excluded_names(updated)
    existing_norms = {normalize_text(name) for name in existing}
    added = []
    for name in names:
        key = normalize_text(name)
        if key and key not in existing_norms:
            existing.append(name)
            existing_norms.add(key)
            added.append(name)

    if not added:
        st.info("No new excluded name to add.")
        return

    updated["excluded_names"] = sorted(existing, key=normalize_text)
    updated.pop("ignored_names", None)
    updated.pop("ambiguous_names", None)
    manager_save_alias_config(config_path, updated)
    _flash(f"Added {len(added)} excluded name(s).")
    st.rerun()


def _save_registry_entry(
    alias_config: str,
    virus_name: str,
    keywords: List[str],
    message: str,
) -> None:
    try:
        update_registry_entry(
            REGISTRY_PATH,
            alias_config=alias_config,
            virus_name=virus_name.strip(),
            keywords=keywords,
        )
        _flash(message)
        st.rerun()
    except Exception as e:
        st.error(f"Could not save registry entry: {e}")


def _delete_registry_keywords(entry: Dict, virus_name: str, keywords: List[str]) -> None:
    current_keywords = entry.get("keywords", [])
    selected_norms = {normalize_text(keyword) for keyword in keywords}
    kept_keywords = [
        keyword
        for keyword in current_keywords
        if normalize_text(keyword) not in selected_norms
    ]
    _save_registry_entry(
        alias_config=entry.get("alias_config", ""),
        virus_name=virus_name,
        keywords=kept_keywords,
        message=f"Removed {len(keywords)} keyword(s).",
    )


def _add_registry_keywords(entry: Dict, virus_name: str, keywords: List[str]) -> None:
    if not keywords:
        st.warning("Add at least one keyword first.")
        return

    existing = entry.get("keywords", [])
    merged = _dedupe_values([*existing, *keywords])
    added_count = len(merged) - len(_dedupe_values(existing))
    if added_count <= 0:
        st.info("No new keyword to add.")
        return

    _save_registry_entry(
        alias_config=entry.get("alias_config", ""),
        virus_name=virus_name,
        keywords=merged,
        message=f"Added {added_count} keyword(s).",
    )


def _delete_virus_entry(entry: Dict, archive_alias_config: bool) -> None:
    try:
        registry_backup, config_backup = remove_registry_entry(
            REGISTRY_PATH,
            alias_config=entry.get("alias_config", ""),
            root=ROOT,
            archive_alias_config=archive_alias_config,
        )
        if st.session_state.get("alias_manager_config_path"):
            del st.session_state["alias_manager_config_path"]
        st.session_state.pop("alias_manager_virus", None)
        message = f"Deleted virus from registry. Registry backup: `{registry_backup.name}`"
        if config_backup:
            message += f". Alias config archived as `{config_backup.name}`"
        elif archive_alias_config:
            message += ". Alias config file was already missing"
        st.session_state.alias_manager_delete_success = message
        st.session_state.alias_manager_scroll_top = True
        st.rerun()
    except Exception as e:
        st.error(f"Could not delete virus: {e}")


def _virus_picker(entries: List[Dict]) -> Dict:
    """Pick a virus by name (not by config file path)."""
    def _label(index: int) -> str:
        entry = entries[index]
        name = entry.get("virus_name") or Path(entry.get("alias_config", "")).stem or "unknown"
        keywords = entry.get("keywords", []) or []
        return f"{name}  ·  {len(keywords)} keyword(s)"

    selected_index = st.radio(
        "Virus",
        list(range(len(entries))),
        index=0,
        format_func=_label,
        key="alias_manager_virus",
        label_visibility="collapsed",
    )
    return entries[selected_index or 0]




def _render_registry_tab(entry: Dict, config: Dict, config_path: Path) -> None:
    st.caption("Auto-detection matches these keywords against the reference metadata. Virus name is the display label.")

    with st.container(horizontal=True, vertical_alignment="bottom"):
        registry_virus_name = st.text_input(
            "Virus name",
            value=entry.get("virus_name", config.get("virus", "")),
            key=f"registry_virus_name_{config_path}",
        )
        if st.button("Save", key=f"save_virus_name_{config_path}"):
            rename_virus(entry.get("virus_name", ""), registry_virus_name.strip())
            _save_registry_entry(
                alias_config=entry.get("alias_config", ""),
                virus_name=registry_virus_name,
                keywords=entry.get("keywords", []),
                message="Virus name saved.",
            )

    st.markdown("**Detection keywords**")
    st.caption("Click keywords to select them for removal, or add new ones below.")
    selected_keywords = _checkbox_list(
        entry.get("keywords", []),
        key_prefix=f"registry_keyword_select_{config_path}",
        empty_message="No detection keywords yet.",
    )
    if st.button(
        f"Remove selected ({len(selected_keywords)})",
        icon=":material/delete:",
        disabled=not selected_keywords,
        key=f"delete_selected_registry_keywords_{config_path}",
    ):
        _delete_registry_keywords(entry, registry_virus_name, selected_keywords)

    with st.form(f"registry_add_keywords_form_{config_path}", clear_on_submit=True):
        new_keywords_text = st.text_area(
            "Add detection keywords",
            value="",
            height=80,
            placeholder="One keyword per line",
            key=f"registry_keywords_add_{config_path}",
        )
        add_keywords_submitted = st.form_submit_button(
            "Add keywords",
            icon=":material/add:",
            type="primary",
        )

    if add_keywords_submitted:
        _add_registry_keywords(
            entry,
            registry_virus_name,
            _split_lines(new_keywords_text),
        )

    # Destructive action tucked away in a collapsed expander so it can't be
    # hit by accident and doesn't weigh down the tab.
    with st.expander("Danger zone · delete this virus", icon=":material/warning:", expanded=False):
        st.caption(
            "Delete this virus from the alias registry so ViraLift will no longer "
            "auto-detect or list it."
        )
        archive_alias_config = st.checkbox(
            "Also archive and remove the active alias config file",
            value=False,
            help=(
                "Copies the alias JSON into app/config/backups/ before removing "
                "the active config file."
            ),
            key=f"delete_virus_archive_config_{config_path}",
        )
        if st.button(
            "Delete virus from Alias Manager",
            icon=":material/delete_forever:",
            key="delete_virus_entry",
        ):
            _confirm_delete_virus_dialog(entry, archive_alias_config)


def _render_aliases_tab(config: Dict, config_path: Path) -> None:
    with st.container(horizontal=True, vertical_alignment="bottom"):
        search_text = st.text_input(
            "Search canonical or alias",
            value="",
            placeholder="e.g. ORF5 or GP5",
            key=f"alias_manager_search_{config_path}",
        )
        with st.popover("Add canonical", icon=":material/add:", type="primary"):
            with st.form(f"alias_manager_add_canonical_form_{config_path}", clear_on_submit=True):
                new_canonical = st.text_input(
                    "Canonical name",
                    value="",
                    key=f"alias_manager_new_canonical_{config_path}",
                ).strip()
                new_canonical_aliases = st.text_area(
                    "Initial aliases",
                    value="",
                    height=96,
                    help="Optional. One alias per line.",
                    key=f"alias_manager_new_canonical_aliases_{config_path}",
                )
                add_canonical_submitted = st.form_submit_button(
                    "Add canonical",
                    type="primary",
                )

            if add_canonical_submitted:
                _add_canonical(
                    config_path,
                    config,
                    new_canonical,
                    _split_lines(new_canonical_aliases),
                )

    st.caption(
        "Each canonical has its own editor. Removing and adding aliases save "
        "immediately; deleting a canonical asks for confirmation first."
    )

    canonical_names = config.get("canonical_names", {})
    search_norm = normalize_text(search_text)
    matches = 0
    for canonical in sorted(canonical_names, key=normalize_text):
        aliases = canonical_names.get(canonical, []) or []
        searchable = normalize_text(" ".join([canonical] + aliases))
        if search_norm and search_norm not in searchable:
            continue
        matches += 1

        should_expand = (
            bool(search_norm)
            or st.session_state.get("alias_manager_open_canonical") == canonical
        )
        with st.expander(f"**{canonical}** · {len(aliases)} alias(es)", expanded=should_expand):
            selected_aliases = _checkbox_list(
                aliases,
                key_prefix=f"alias_select_{config_path}_{normalize_text(canonical)}",
                empty_message="No aliases yet.",
            )

            with st.container(horizontal=True):
                if st.button(
                    f"Remove selected ({len(selected_aliases)})",
                    icon=":material/delete:",
                    disabled=not selected_aliases,
                    key=f"delete_selected_aliases_{config_path}_{normalize_text(canonical)}",
                ):
                    _delete_aliases(config_path, config, canonical, selected_aliases)

                if st.button(
                    "Delete canonical",
                    icon=":material/delete_forever:",
                    type="tertiary",
                    key=f"delete_canonical_{config_path}_{normalize_text(canonical)}",
                    help="Removes this canonical and all its aliases (asks for confirmation).",
                ):
                    _confirm_delete_canonical_dialog(config_path, config, canonical)

            with st.form(
                key=f"alias_add_form_{config_path}_{normalize_text(canonical)}",
                clear_on_submit=True,
            ):
                new_alias_text = st.text_area(
                    f"Add aliases for {canonical}",
                    value="",
                    height=96,
                    placeholder="One alias per line",
                    key=f"alias_add_{config_path}_{normalize_text(canonical)}",
                )
                add_submitted = st.form_submit_button("Add aliases", icon=":material/add:")

            if add_submitted:
                new_aliases = _split_lines(new_alias_text)
                if not new_aliases:
                    st.warning("Add at least one alias first.")
                    st.stop()
                _add_aliases(config_path, config, canonical, new_aliases)

    if search_norm and matches == 0:
        st.caption("No canonical or alias matches your search.")


def _render_excluded_tab(config: Dict, config_path: Path, excluded_existing: List[str]) -> None:
    st.caption(
        "Names here are skipped during automatic alias matching. Use this for "
        "generic, ambiguous, or unsafe names that should not become reusable aliases."
    )
    selected_excluded = _checkbox_list(
        excluded_existing,
        key_prefix=f"excluded_select_{config_path}",
        empty_message="No excluded names yet.",
    )
    if st.button(
        f"Remove selected ({len(selected_excluded)})",
        icon=":material/delete:",
        disabled=not selected_excluded,
        key=f"delete_selected_excluded_{config_path}",
    ):
        _delete_names(config_path, config, "excluded_names", selected_excluded, "excluded name")

    with st.form(f"alias_manager_excluded_add_form_{config_path}", clear_on_submit=True):
        new_excluded_text = st.text_area(
            "Add excluded names",
            value="",
            height=120,
            placeholder="One excluded name per line",
            key=f"alias_manager_excluded_add_{config_path}",
        )
        add_excluded_submitted = st.form_submit_button(
            "Add excluded names",
            icon=":material/add:",
            type="primary",
        )

    if add_excluded_submitted:
        names = _split_lines(new_excluded_text)
        if not names:
            st.warning("Add at least one excluded name first.")
            st.stop()
        _add_excluded(config_path, config, names)

    st.markdown("**Move an excluded name to a canonical**")
    canonical_options = sorted(config.get("canonical_names", {}))
    with st.container(horizontal=True, vertical_alignment="bottom"):
        excluded_choice = st.selectbox(
            "Excluded name",
            excluded_existing,
            key=f"move_excluded_name_{config_path}",
        ) if excluded_existing else None
        canonical_choice = st.selectbox(
            "Canonical",
            canonical_options,
            key=f"move_excluded_canonical_{config_path}",
        ) if canonical_options else None
        move_clicked = st.button(
            "Move",
            icon=":material/arrow_forward:",
            disabled=not (excluded_choice and canonical_choice),
            key=f"move_excluded_btn_{config_path}",
        )
    if move_clicked:
        updated = move_excluded_to_alias(config, excluded_choice, canonical_choice)
        warnings = validate_alias_config(updated)
        if warnings:
            st.warning("\n".join(warnings))
        else:
            manager_save_alias_config(config_path, updated)
            _flash(f"Moved {excluded_choice} to {canonical_choice}.")
            st.rerun()


# ── Reference genomes ───────────────────────────────────────────────────

def _make_default_reference(ref_id: str) -> None:
    set_default(ref_id)
    _flash(f"{ref_id} is now the default reference.")


def _remove_reference(ref_id: str) -> None:
    remove_reference(ref_id)
    _flash(f"Removed {ref_id} from the reference library.", icon="🗑️")


def _add_reference(uploaded, virus_name: str, config_path: Path) -> None:
    """Validate an uploaded GenBank reference the way a run would, then save it."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "reference.gb"
        path.write_bytes(uploaded.getvalue())
        try:
            record = load_single_genbank(path)
            features, feature_type, *_ = prepare_reference_features(
                record, alias_config_arg=str(config_path), alias_registry_arg=str(REGISTRY_PATH)
            )
        except Exception as e:
            st.error(f"Could not add `{uploaded.name}`: {e}")
            return
        save_reference(path, record, virus_name, feature_type, len(features))
    message = f"Added {record.id} to {virus_name}."
    detected = get_detected_virus_name(record, REGISTRY_PATH)
    if detected and detected != virus_name:
        message += f" Its metadata looks like {detected}."
    _flash(message)
    st.session_state.reference_upload_nonce = st.session_state.get("reference_upload_nonce", 0) + 1
    st.rerun()


def _render_references_tab(virus_name: str, config_path: Path) -> None:
    st.caption(
        "Reference genomes for this virus. Run pipeline suggests the default one when a query "
        "is detected as this virus, and every reference used in a run is added here."
    )
    saved = references_for(virus_name, list_references())
    if not saved:
        st.info("No reference saved for this virus yet. Add one below, or run the pipeline with one.")

    for index, ref in enumerate(saved):
        with _card(f"reference_{index}"):
            with st.container(horizontal=True, horizontal_alignment="distribute", vertical_alignment="center"):
                facts = " · ".join(filter(None, [
                    f"{ref.get('length', 0):,} bp",
                    f"{ref.get('genes', 0)} genes",
                    ref.get("feature_type") or "",
                    f"added {ref.get('added', '')[:10]}",
                    f"last used {ref.get('last_used', '')[:10]}" if ref.get("last_used") else "",
                ]))
                st.html(
                    "<div class='vl-ref-row'>"
                    f"<div class='vl-ref-id'>{html.escape(ref['id'])}"
                    + ("<span class='vl-badge tone-ok'>Default</span>" if ref.get("default") else "")
                    + "</div>"
                    f"<div class='vl-ref-desc'>{html.escape(ref.get('description', ''))}</div>"
                    f"<div class='vl-meta'>{html.escape(facts)}</div>"
                    "</div>"
                )
                with st.container(horizontal=True, width="content", vertical_alignment="center"):
                    path = reference_file(ref)
                    st.download_button(
                        ".gb",
                        data=path.read_bytes(),
                        file_name=path.name,
                        icon=":material/download:",
                        key=f"reference_download_{ref['id']}",
                        help="Download this GenBank file",
                        on_click="ignore",
                    )
                    if not ref.get("default"):
                        st.button(
                            "Make default",
                            icon=":material/star:",
                            key=f"reference_default_{ref['id']}",
                            on_click=_make_default_reference,
                            args=(ref["id"],),
                        )
                    with st.popover("Remove", icon=":material/delete:", key=f"reference_remove_{ref['id']}"):
                        st.caption(f"Remove {ref['id']} from the library? Results you already have are not affected.")
                        st.button(
                            "Remove reference",
                            type="primary",
                            key=f"reference_remove_confirm_{ref['id']}",
                            on_click=_remove_reference,
                            args=(ref["id"],),
                        )

    st.markdown("**Add a reference**")
    uploaded = st.file_uploader(
        "One well-annotated GenBank record (.gb, .gbk)",
        type=["gb", "gbk"],
        key=f"reference_upload_{config_path}_{st.session_state.get('reference_upload_nonce', 0)}",
    )
    if st.button(
        f"Add to {virus_name}",
        icon=":material/add:",
        type="primary",
        disabled=uploaded is None,
        key=f"reference_add_{config_path}",
    ):
        _add_reference(uploaded, virus_name, config_path)


def _render_virus_editor(entry: Dict) -> None:
    config_path = resolve_config_path(Path(entry.get("alias_config", "")), ROOT)
    st.session_state.alias_manager_config_path = config_path

    try:
        config = manager_load_alias_config(config_path)
    except Exception as e:
        st.error(f"Could not load alias config `{config_path}`: {e}")
        return

    _, excluded_rows, _ = alias_config_to_tables(config)
    excluded_existing = [row["excluded_name"] for row in excluded_rows]

    canonical_names_map = config.get("canonical_names", {})
    total_aliases = sum(len(aliases or []) for aliases in canonical_names_map.values())
    virus_label = entry.get("virus_name", config.get("virus", "unknown"))
    _render_section_title(virus_label, f"Config file · {config_path.name}")
    _render_stats([
        {"label": "Canonical", "value": len(canonical_names_map), "tone": "primary"},
        {"label": "Aliases", "value": total_aliases},
        {"label": "References", "value": len(references_for(virus_label, list_references()))},
        {"label": "Excluded", "value": len(excluded_existing)},
        {"label": "Keywords", "value": len(entry.get("keywords", []) or [])},
    ])

    # Always-on health check so config issues are visible without hunting for a Save button.
    config_warnings = validate_alias_config(config)
    if config_warnings:
        with st.expander(f"{len(config_warnings)} config warning(s)", icon=":material/warning:", expanded=False):
            for warning in config_warnings:
                st.markdown(f"- {warning}")

    tab_alias, tab_refs, tab_registry, tab_excluded = st.tabs([
        "Canonical aliases",
        "Reference genomes",
        "Detection keywords",
        "Excluded names",
    ])
    with tab_alias:
        _render_aliases_tab(config, config_path)
    with tab_refs:
        _render_references_tab(virus_label, config_path)
    with tab_registry:
        _render_registry_tab(entry, config, config_path)
    with tab_excluded:
        _render_excluded_tab(config, config_path, excluded_existing)

    # Advanced: raw config view + export. Not a daily-use surface, so it's collapsed.
    with st.expander("Advanced · raw JSON and export", icon=":material/data_object:", expanded=False):
        with st.container(horizontal=True):
            st.download_button(
                "Download alias config (JSON)",
                data=json.dumps(config, ensure_ascii=False, indent=2),
                file_name=config_path.name,
                mime="application/json",
                icon=":material/download:",
                on_click="ignore",
            )
            if st.button("Reload from disk", icon=":material/refresh:", key=f"alias_manager_reload_{config_path}"):
                st.rerun()
        st.json(config)


def page_alias_manager():
    _scroll_to_top_once()
    _render_flash()
    _render_page_intro(
        "Alias manager",
        "Alias database",
        (
            "The shared vocabulary every run uses to standardise gene names. "
            "Every edit saves immediately and writes a timestamped backup."
        ),
        show_stages=False,
        guide=_open_guide,
    )

    # Shown once: popping it here means a later rerun (e.g. opening the Guide)
    # never tries to open a second dialog in the same run.
    delete_message = st.session_state.pop("alias_manager_delete_success", None)
    if delete_message:
        _delete_success_dialog(delete_message)

    try:
        entries = list_registry_entries(REGISTRY_PATH)
    except Exception as e:
        st.error(f"Could not load alias registry: {e}")
        return

    if not entries:
        st.warning("No registered virus alias configs found.")
        return

    col_list, col_editor = st.columns([1, 3.2], gap="large")
    with col_list:
        _render_nav_label(f"Viruses · {len(entries)}")
        entry = _virus_picker(entries)
        st.caption("New viruses are added from Run pipeline when a reference is not recognised.")
    with col_editor:
        _render_virus_editor(entry)
