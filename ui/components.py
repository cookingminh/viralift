# Reusable HTML building blocks for the Streamlit UI. Every dynamic value is
# passed through html.escape() before it reaches st.html.
import html
import streamlit as st
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple
from ui.i18n import _t
from ui.state import STATUS_TONE


# The run pipeline shows three steps; each internal stage belongs to one.
PIPELINE_STEPS = (
    ("upload",),
    ("virus_review", "bootstrap_alias", "resolve"),
    ("running", "results"),
)
PIPELINE_STEP_KEYS = ("step_setup", "step_review", "step_results")

# Status -> visual tone. Passes that needed an adjustment get their own tone so
# they stand out from clean passes without looking like failures.
UI_STATUS_TONE = {
    "ok": "ok",
    "direct": "ok",
    "ok_rescued": "info",
    "ok_extrapolated": "info",
    "ok_no_start_codon": "info",
    "ok_gap_filled": "info",
    "not_in_reference": "neutral",
    "no_hit": "danger",
    "translation_fail": "danger",
}
# Tone -> Streamlit theme colour for pill cells in st.dataframe. Named theme
# colours resolve to the soft *BackgroundColor values in config.toml, so the
# pills follow light/dark without any CSS.
TONE_PILL_COLOR = {"ok": "green", "info": "blue", "warn": "orange", "danger": "red", "neutral": "gray"}


def _esc(value: object) -> str:
    return html.escape(str(value))


def _status_tone(status: str) -> str:
    if status in UI_STATUS_TONE:
        return UI_STATUS_TONE[status]
    return "warn" if STATUS_TONE.get(status, "review") == "review" else "ok"


def _status_label(status: str) -> str:
    return _t(f"status_{status}")


def _pill_column(
    label: str,
    options: Iterable[str],
    tone_of: Callable[[str], str],
    format_func: Callable[[str], str],
    help: Optional[str] = None,
    width: int = 150,
):
    """Read-only coloured pill column; each cell holds a one-item list."""
    options = list(options)
    return st.column_config.MultiselectColumn(
        label,
        options=options,
        color=[TONE_PILL_COLOR[tone_of(option)] for option in options],
        format_func=format_func,
        help=help,
        width=width,
    )


def _status_column(help: Optional[str] = None):
    statuses = dict.fromkeys([*STATUS_TONE, *UI_STATUS_TONE])
    return _pill_column("Status", statuses, _status_tone, _status_label, help, width=160)


def _status_cell(status: str) -> List[str]:
    """Cell value for _status_column (tables cannot hold HTML, so pills do the colour)."""
    return [status]


def _status_badge(status: str) -> str:
    return f"<span class='vl-badge tone-{_status_tone(status)}'>{_esc(_status_label(status))}</span>"


def _pipeline_step_index(stage: str) -> int:
    return next(
        (index for index, stages in enumerate(PIPELINE_STEPS) if stage in stages),
        0,
    )


def _render_page_intro(
    kicker: str,
    title: str,
    body: str,
    show_stages: bool = True,
    step_note: str = "",
    guide: Optional[Callable[[], None]] = None,
):
    """Page header; `guide` (ui.guide._open_guide) adds the (?) Guide button top right."""
    with st.container(
        horizontal=True, horizontal_alignment="distribute", vertical_alignment="top", gap="medium", key="vl_page_head"
    ):
        st.html(
            "<header class='vl-header'>"
            f"<div class='vl-kicker'>{_esc(kicker)}</div>"
            f"<div class='vl-title'>{_esc(title)}</div>"
            f"<div class='vl-sub'>{_esc(body)}</div>"
            "</header>"
        )
        open_guide = guide is not None and st.button(
            _t("guide"),
            icon=":material/help:",
            key="vl_guide",
            help=_t("guide_help"),
        )
    if show_stages:
        active = _pipeline_step_index(st.session_state.stage)
        parts = []
        for index, key in enumerate(PIPELINE_STEP_KEYS):
            state = "is-done" if index < active else "is-active" if index == active else ""
            dot = "✓" if index < active else str(index + 1)
            note = step_note if index == active and step_note else _t(f"{key}_note")
            if index:
                parts.append(f"<span class='vl-step-line {'is-done' if index <= active else ''}'></span>")
            parts.append(
                f"<div class='vl-step {state}'>"
                f"<span class='vl-step-dot'>{_esc(dot)}</span>"
                "<div class='vl-step-text'>"
                f"<div class='vl-step-name'>{_esc(_t(key))}</div>"
                f"<div class='vl-step-note'>{_esc(note)}</div>"
                "</div></div>"
            )
        st.html(f"<nav class='vl-stepper' aria-label='Pipeline progress'>{''.join(parts)}</nav>")
    if open_guide:
        guide()


def _card(name: str, **kwargs):
    """Bordered container painted as a card; theme.py styles the st-key-vl_card_* class."""
    return st.container(border=True, key=f"vl_card_{name}", **kwargs)


def _render_section_title(title: str, caption: str = "", step: Optional[int] = None):
    number = f"<span class='vl-section-num'>{step}</span>" if step is not None else ""
    caption_html = f"<div class='vl-section-caption'>{_esc(caption)}</div>" if caption else ""
    st.html(
        f"<div class='vl-section'>{number}<div>"
        f"<div class='vl-section-title'>{_esc(title)}</div>{caption_html}"
        "</div></div>"
    )


def _render_context_panel(items: List[Tuple[str, object]]):
    cells = "".join(
        "<div class='vl-fact'>"
        f"<div class='vl-fact-label'>{_esc(label)}</div>"
        f"<div class='vl-fact-value'>{_esc(value)}</div>"
        "</div>"
        for label, value in items
    )
    st.html(f"<div class='vl-facts'>{cells}</div>")


def _render_stats(tiles: Sequence[Dict[str, object]]):
    """Stat tiles: each dict has label, value, optional note and tone."""
    cells = "".join(
        f"<div class='vl-stat tone-{_esc(tile.get('tone', 'plain'))}'>"
        f"<div class='vl-stat-label'>{_esc(tile['label'])}</div>"
        f"<div class='vl-stat-value'>{_esc(tile['value'])}</div>"
        + (f"<div class='vl-stat-note'>{_esc(tile['note'])}</div>" if tile.get("note") else "")
        + "</div>"
        for tile in tiles
    )
    st.html(f"<div class='vl-stats'>{cells}</div>")


def _render_status_bar(summary: Dict[str, int]):
    counts = [(status, count) for status, count in summary.items() if count]
    total = sum(count for _, count in counts)
    if not total:
        return
    segments = "".join(
        f"<span class='tone-{_status_tone(status)}' style='flex:{count}' "
        f"title='{_esc(_status_label(status))}: {count}'></span>"
        for status, count in counts
    )
    legend = "".join(
        "<span class='vl-legend-item'>"
        f"<span class='vl-swatch tone-{_status_tone(status)}'></span>"
        f"{_esc(_status_label(status))} <b>{count}</b></span>"
        for status, count in counts
    )
    st.html(
        "<div class='vl-statusbar'>"
        f"<div class='vl-bar' role='img' aria-label='Status distribution'>{segments}</div>"
        f"<div class='vl-legend'>{legend}</div>"
        "</div>"
    )


def _render_callout(body_html: str, tone: str = "info", icon: str = "i"):
    """body_html must already be escaped by the caller."""
    st.html(
        f"<div class='vl-callout tone-{_esc(tone)}'>"
        f"<span class='vl-callout-icon'>{_esc(icon)}</span><div>{body_html}</div>"
        "</div>"
    )


def _chips_html(values: Iterable[object], primary: bool = False) -> str:
    cls = "vl-chip is-primary" if primary else "vl-chip"
    return "<div class='vl-chips'>" + "".join(
        f"<span class='{cls}'>{_esc(value)}</span>" for value in values
    ) + "</div>"


def _sequence_html(sequence: str, limit: int = 360) -> str:
    shown = sequence[:limit]
    letters = "".join(
        f"<span class='{base.lower()}'>{base}</span>" if base.upper() in "ACGT" else _esc(base)
        for base in shown
    )
    more = (
        f"<span class='more'> … +{len(sequence) - limit:,} nt</span>"
        if len(sequence) > limit else ""
    )
    return (
        "<div class='vl-seq'>"
        f"<div class='vl-seq-label'>Sequence · {len(sequence):,} nt</div>"
        f"{letters}{more}</div>"
    )


def _kv_html(items: Sequence[Tuple[str, object]]) -> str:
    return "<div class='vl-kv'>" + "".join(
        f"<div><div class='vl-kv-label'>{_esc(label)}</div>"
        f"<div class='vl-kv-value'>{_esc(value)}</div></div>"
        for label, value in items
    ) + "</div>"


def _render_brand():
    st.html(
        "<div class='vl-brand'>"
        "<div class='vl-brand-mark'>V</div>"
        "<div><div class='vl-brand-name'>ViraLift</div>"
        f"<div class='vl-brand-sub'>{_esc(_t('sidebar_subtitle'))}</div></div>"
        "</div>"
    )


def _render_nav_label(label: str):
    st.html(f"<div class='vl-nav-label'>{_esc(label)}</div>")


def _render_sidebar_context(items: List[Tuple[str, object]]):
    if not items:
        return
    rows = "".join(
        "<div class='vl-ctx-row'>"
        f"<span class='vl-ctx-label'>{_esc(label)}</span>"
        f"<span class='vl-ctx-value'>{_esc(value)}</span>"
        "</div>"
        for label, value in items
    )
    st.html(f"<div class='vl-ctx'>{rows}</div>")


def _format_percent(value: Optional[float], digits: int = 1) -> str:
    if value is None:
        return "NA"
    return f"{value:.{digits}f}%"


def _format_fraction_percent(value: Optional[float], digits: int = 0) -> str:
    if value is None:
        return "NA"
    return f"{value * 100:.{digits}f}%"


def _error_by_record(errors: List[Dict[str, str]]) -> Dict[str, str]:
    return {err["record_id"]: err["error"] for err in errors}
