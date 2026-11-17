# Visual theme for the Streamlit UI.
#
# Streamlit owns the light/dark switch: .streamlit/config.toml defines the
# [theme.light] and [theme.dark] palettes, so native widgets (inputs, tables,
# buttons, alerts) always match. This module mirrors the same values as CSS
# tokens for ViraLift's own HTML components, and a tiny script tags <html>
# with data-vl-theme by reading the background Streamlit actually painted —
# so custom components follow the settings menu too, not just the OS.
import streamlit as st


# Keep in sync with .streamlit/config.toml (checked by test_ui_theme.py).
PALETTE = {
    "light": {
        "bg": "#F7F8FB",
        "surface": "#FFFFFF",
        "surface-2": "#F1F2F7",
        "border": "#E3E5ED",
        "border-strong": "#CDD0DB",
        "text": "#1B1E2B",
        "muted": "#5E6373",
        "faint": "#8E92A3",
        "primary": "#5B5BD6",
        "primary-strong": "#4C4BC4",
        "primary-soft": "#EEEEFD",
        "primary-text": "#4644B8",
        "on-primary": "#FFFFFF",
        "ok": "#18794E",
        "ok-soft": "#E8F5EE",
        "info": "#0B68C1",
        "info-soft": "#E7F2FD",
        "warn": "#A35200",
        "warn-soft": "#FFF3DF",
        "danger": "#C9282E",
        "danger-soft": "#FDEBEC",
        "neutral": "#5E6373",
        "neutral-soft": "#F0F1F4",
        "coral": "#F0643C",
        "nt-a": "#18794E",
        "nt-c": "#0B68C1",
        "nt-g": "#A35200",
        "nt-t": "#C9282E",
        "shadow": "0 1px 2px rgba(27, 30, 43, 0.04), 0 8px 24px rgba(27, 30, 43, 0.05)",
    },
    "dark": {
        "bg": "#111218",
        "surface": "#171922",
        "surface-2": "#1E2130",
        "border": "#2A2D3B",
        "border-strong": "#3A3E50",
        "text": "#ECEDF3",
        "muted": "#A6AABB",
        "faint": "#737889",
        "primary": "#6E6ADE",
        "primary-strong": "#7D79E6",
        "primary-soft": "rgba(124, 120, 240, 0.16)",
        "primary-text": "#B4AFFF",
        "on-primary": "#FFFFFF",
        "ok": "#4CD69B",
        "ok-soft": "rgba(76, 214, 155, 0.13)",
        "info": "#73B9FF",
        "info-soft": "rgba(115, 185, 255, 0.13)",
        "warn": "#F5B65A",
        "warn-soft": "rgba(245, 182, 90, 0.13)",
        "danger": "#FF8E8C",
        "danger-soft": "rgba(255, 142, 140, 0.14)",
        "neutral": "#A6AABB",
        "neutral-soft": "rgba(166, 170, 187, 0.12)",
        "coral": "#FF8259",
        "nt-a": "#4CD69B",
        "nt-c": "#73B9FF",
        "nt-g": "#F5B65A",
        "nt-t": "#FF8E8C",
        "shadow": "0 1px 2px rgba(0, 0, 0, 0.3), 0 8px 24px rgba(0, 0, 0, 0.22)",
    },
}


def _token_block(mode: str) -> str:
    return "".join(f"--vl-{name}: {value};" for name, value in PALETTE[mode].items())


_CSS = """
:root {
    __LIGHT_TOKENS__
    --vl-mono: "JetBrains Mono", ui-monospace, SFMono-Regular, Menlo, monospace;
    --vl-radius: 0.75rem;
    --vl-radius-sm: 0.5rem;
}
html[data-vl-theme="dark"] { __DARK_TOKENS__ }
@media (prefers-color-scheme: dark) {
    html:not([data-vl-theme]) { __DARK_TOKENS__ }
}

/* ── page frame ─────────────────────────────────────────────────── */
/* top padding clears Streamlit's 3.75rem toolbar so the header's Guide button is never under it */
.stMainBlockContainer, .main .block-container {
    max-width: 1240px;
    padding-top: 4.5rem;
    padding-bottom: 4rem;
}
h1, h2, h3, h4 { letter-spacing: -0.015em; text-wrap: balance; }
[data-testid="stElementContainer"]:has(.vl-boot) { display: none; }

/* cards (components._card) sit as white panels on the tinted page */
[class*="st-key-vl_card_"] {
    background: var(--vl-surface);
    box-shadow: var(--vl-shadow);
}

/* ── sidebar ────────────────────────────────────────────────────── */
[data-testid="stSidebarUserContent"] { padding-top: 0.6rem; }
[data-testid="stSidebar"] .stButton button {
    justify-content: flex-start;
    padding: 0.55rem 0.75rem;
    font-weight: 600;
    color: var(--vl-muted);
    border-radius: var(--vl-radius-sm);
}
[data-testid="stSidebar"] .stButton button:hover {
    color: var(--vl-text);
    background: var(--vl-surface-2);
}
[data-testid="stSidebar"] .stButton button > div { justify-content: flex-start; }

/* ── native widget polish (colours come from config.toml) ───────── */
[data-testid="stFileUploaderDropzone"] {
    border: 1.5px dashed var(--vl-border-strong);
    background: var(--vl-surface-2);
    transition: border-color 160ms ease, background 160ms ease;
}
[data-testid="stFileUploaderDropzone"]:hover {
    border-color: var(--vl-primary);
    background: var(--vl-primary-soft);
}
[data-testid="stExpander"] details { background: var(--vl-surface); }
[data-testid="stExpander"] summary { font-weight: 600; }
.stButton button, .stDownloadButton button, .stFormSubmitButton button { font-weight: 600; }
[data-testid="stBaseButton-primary"]:not(:disabled) { box-shadow: 0 4px 14px -6px var(--vl-primary); }

/* ── page header + stepper ──────────────────────────────────────── */
.vl-header { margin: 0 0 0.3rem; }
/* keep the Guide button top right on narrow screens too, instead of wrapping below */
.st-key-vl_page_head { flex-wrap: nowrap !important; }
.st-key-vl_page_head > div:first-child { min-width: 0; }
.st-key-vl_guide { flex: none; }
.st-key-vl_guide button {
    border-radius: 999px;
    padding: 0.3rem 0.9rem 0.3rem 0.7rem;
    min-height: 2.2rem;
    color: var(--vl-muted);
    background: var(--vl-surface);
    box-shadow: var(--vl-shadow);
}
.st-key-vl_guide button:hover { color: var(--vl-primary-text); border-color: var(--vl-primary); }
.vl-kicker {
    font-size: 0.72rem;
    font-weight: 700;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    color: var(--vl-primary-text);
}
.vl-title {
    font-size: clamp(1.6rem, 2.6vw, 2.15rem);
    font-weight: 800;
    line-height: 1.15;
    color: var(--vl-text);
    margin: 0.3rem 0 0.4rem;
    letter-spacing: -0.02em;
}
.vl-sub { color: var(--vl-muted); font-size: 0.97rem; line-height: 1.6; max-width: 46rem; }

.vl-stepper {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    margin: 0 0 0.6rem;
    padding: 0.8rem 1rem;
    background: var(--vl-surface);
    border: 1px solid var(--vl-border);
    border-radius: var(--vl-radius);
    box-shadow: var(--vl-shadow);
}
.vl-step { display: flex; align-items: center; gap: 0.6rem; min-width: 0; }
.vl-step-dot {
    flex: none;
    width: 1.75rem;
    height: 1.75rem;
    border-radius: 999px;
    display: grid;
    place-items: center;
    font-size: 0.78rem;
    font-weight: 700;
    color: var(--vl-faint);
    background: var(--vl-surface-2);
    border: 1px solid var(--vl-border);
}
.vl-step-text { min-width: 0; }
.vl-step-name { font-size: 0.86rem; font-weight: 700; color: var(--vl-faint); white-space: nowrap; }
.vl-step-note { font-size: 0.72rem; color: var(--vl-faint); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.vl-step-line { flex: 1; height: 2px; min-width: 1.5rem; border-radius: 2px; background: var(--vl-border); }
.vl-step.is-done .vl-step-dot { background: var(--vl-primary-soft); color: var(--vl-primary-text); border-color: transparent; }
.vl-step.is-done .vl-step-name { color: var(--vl-text); }
.vl-step-line.is-done { background: var(--vl-primary); }
.vl-step.is-active .vl-step-dot {
    background: var(--vl-primary);
    color: var(--vl-on-primary);
    border-color: var(--vl-primary);
    box-shadow: 0 0 0 4px var(--vl-primary-soft);
}
.vl-step.is-active .vl-step-name { color: var(--vl-text); }
.vl-step.is-active .vl-step-note { color: var(--vl-primary-text); }

/* ── section titles inside cards ────────────────────────────────── */
.vl-section { display: flex; gap: 0.7rem; align-items: flex-start; }
.vl-section-num {
    flex: none;
    width: 1.6rem;
    height: 1.6rem;
    border-radius: 0.45rem;
    display: grid;
    place-items: center;
    font-size: 0.78rem;
    font-weight: 800;
    color: var(--vl-primary-text);
    background: var(--vl-primary-soft);
}
.vl-section-title { font-size: 1.02rem; font-weight: 700; color: var(--vl-text); line-height: 1.6rem; }
.vl-section-caption { font-size: 0.84rem; color: var(--vl-muted); line-height: 1.5; margin-top: 0.1rem; }

/* ── facts strip (label / value pairs) ──────────────────────────── */
.vl-facts {
    display: flex;
    flex-wrap: wrap;
    gap: 0.5rem 1.6rem;
    padding: 0.75rem 1rem;
    border: 1px solid var(--vl-border);
    border-radius: var(--vl-radius);
    background: var(--vl-surface);
    margin: 0 0 1rem;
}
.vl-fact { min-width: 0; }
.vl-fact-label {
    font-size: 0.68rem;
    font-weight: 700;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: var(--vl-faint);
}
.vl-fact-value {
    font-family: var(--vl-mono);
    font-size: 0.86rem;
    font-weight: 600;
    color: var(--vl-text);
    overflow-wrap: anywhere;
}

/* ── stat tiles ─────────────────────────────────────────────────── */
.vl-stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(10rem, 1fr)); gap: 0.75rem; margin: 0 0 1rem; }
.vl-stat {
    background: var(--vl-surface);
    border: 1px solid var(--vl-border);
    border-radius: var(--vl-radius);
    padding: 0.95rem 1.05rem;
    box-shadow: var(--vl-shadow);
}
.vl-stat-label { font-size: 0.74rem; font-weight: 700; letter-spacing: 0.06em; text-transform: uppercase; color: var(--vl-muted); }
.vl-stat-value {
    font-size: 1.85rem;
    font-weight: 800;
    letter-spacing: -0.03em;
    color: var(--vl-text);
    line-height: 1.2;
    margin-top: 0.2rem;
    font-variant-numeric: tabular-nums;
}
.vl-stat-note { font-size: 0.78rem; color: var(--vl-faint); margin-top: 0.15rem; }
.vl-stat.tone-primary { background: var(--vl-primary-soft); border-color: transparent; }
.vl-stat.tone-primary .vl-stat-value { color: var(--vl-primary-text); }
.vl-stat.tone-ok .vl-stat-value { color: var(--vl-ok); }
.vl-stat.tone-warn .vl-stat-value { color: var(--vl-warn); }
.vl-stat.tone-danger .vl-stat-value { color: var(--vl-danger); }

/* ── status distribution bar ────────────────────────────────────── */
.vl-statusbar { margin: 0 0 1.2rem; }
.vl-bar {
    display: flex;
    height: 0.6rem;
    border-radius: 999px;
    overflow: hidden;
    background: var(--vl-surface-2);
    gap: 2px;
}
.vl-bar span { display: block; min-width: 4px; }
.vl-legend { display: flex; flex-wrap: wrap; gap: 0.4rem 1rem; margin-top: 0.6rem; font-size: 0.8rem; color: var(--vl-muted); }
.vl-legend-item { display: inline-flex; align-items: center; gap: 0.4rem; }
.vl-legend-item b { color: var(--vl-text); font-variant-numeric: tabular-nums; }
.vl-swatch { width: 0.6rem; height: 0.6rem; border-radius: 3px; }

/* ── chips and badges ───────────────────────────────────────────── */
.vl-chips { display: flex; flex-wrap: wrap; gap: 0.35rem; }
.vl-chip {
    display: inline-flex;
    align-items: center;
    max-width: 100%;
    padding: 0.18rem 0.6rem;
    border-radius: 999px;
    border: 1px solid var(--vl-border);
    background: var(--vl-surface-2);
    color: var(--vl-text);
    font-family: var(--vl-mono);
    font-size: 0.78rem;
    overflow-wrap: anywhere;
}
.vl-chip.is-primary { background: var(--vl-primary-soft); border-color: transparent; color: var(--vl-primary-text); }
.vl-badge {
    display: inline-flex;
    align-items: center;
    gap: 0.35rem;
    padding: 0.15rem 0.6rem;
    border-radius: 999px;
    font-size: 0.76rem;
    font-weight: 700;
    white-space: nowrap;
}
.vl-badge::before { content: ""; width: 0.45rem; height: 0.45rem; border-radius: 999px; background: currentColor; }
.tone-ok.vl-badge, .vl-swatch.tone-ok { background: var(--vl-ok-soft); color: var(--vl-ok); }
.tone-info.vl-badge, .vl-swatch.tone-info { background: var(--vl-info-soft); color: var(--vl-info); }
.tone-warn.vl-badge, .vl-swatch.tone-warn { background: var(--vl-warn-soft); color: var(--vl-warn); }
.tone-danger.vl-badge, .vl-swatch.tone-danger { background: var(--vl-danger-soft); color: var(--vl-danger); }
.tone-neutral.vl-badge, .vl-swatch.tone-neutral { background: var(--vl-neutral-soft); color: var(--vl-neutral); }
.vl-bar .tone-ok, .vl-swatch.tone-ok { background: var(--vl-ok); }
.vl-bar .tone-info, .vl-swatch.tone-info { background: var(--vl-info); }
.vl-bar .tone-warn, .vl-swatch.tone-warn { background: var(--vl-warn); }
.vl-bar .tone-danger, .vl-swatch.tone-danger { background: var(--vl-danger); }
.vl-bar .tone-neutral, .vl-swatch.tone-neutral { background: var(--vl-faint); }
.vl-meta { font-size: 0.76rem; color: var(--vl-faint); margin-top: 0.35rem; overflow-wrap: anywhere; }

/* ── callouts ───────────────────────────────────────────────────── */
.vl-callout {
    display: flex;
    gap: 0.75rem;
    align-items: flex-start;
    padding: 0.8rem 1rem;
    border-radius: var(--vl-radius);
    font-size: 0.9rem;
    line-height: 1.55;
    color: var(--vl-text);
    margin: 0 0 1rem;
    border: 1px solid transparent;
}
.vl-callout-icon { flex: none; font-weight: 800; width: 1.3rem; height: 1.3rem; border-radius: 999px; display: grid; place-items: center; font-size: 0.75rem; }
.vl-callout.tone-info { background: var(--vl-primary-soft); }
.vl-callout.tone-info .vl-callout-icon { background: var(--vl-primary); color: var(--vl-on-primary); }
.vl-callout.tone-warn { background: var(--vl-warn-soft); }
.vl-callout.tone-warn .vl-callout-icon { background: var(--vl-warn); color: var(--vl-surface); }
.vl-callout.tone-ok { background: var(--vl-ok-soft); }
.vl-callout.tone-ok .vl-callout-icon { background: var(--vl-ok); color: var(--vl-surface); }
.vl-callout code, .vl-callout .vl-mono { font-family: var(--vl-mono); font-size: 0.84em; }

/* ── feature detail panel ───────────────────────────────────────── */
.vl-detail-head { display: flex; flex-wrap: wrap; align-items: center; gap: 0.5rem; margin-bottom: 0.9rem; }
.vl-detail-title { font-family: var(--vl-mono); font-weight: 700; font-size: 1rem; color: var(--vl-text); margin-right: 0.3rem; }
.vl-kv { display: grid; grid-template-columns: repeat(auto-fit, minmax(11rem, 1fr)); gap: 0.8rem 1.2rem; }
.vl-kv-label { font-size: 0.68rem; font-weight: 700; letter-spacing: 0.08em; text-transform: uppercase; color: var(--vl-faint); }
.vl-kv-value { font-family: var(--vl-mono); font-size: 0.86rem; color: var(--vl-text); margin-top: 0.15rem; overflow-wrap: anywhere; }
.vl-explain { margin-top: 0.9rem; font-size: 0.84rem; line-height: 1.55; color: var(--vl-muted); }
.vl-seq {
    margin-top: 0.9rem;
    padding: 0.75rem 0.9rem;
    border-radius: var(--vl-radius-sm);
    background: var(--vl-surface-2);
    border: 1px solid var(--vl-border);
    font-family: var(--vl-mono);
    font-size: 0.78rem;
    line-height: 1.75;
    letter-spacing: 0.04em;
    word-break: break-all;
    color: var(--vl-muted);
}
.vl-seq-label { font-family: inherit; font-size: 0.68rem; letter-spacing: 0.08em; text-transform: uppercase; color: var(--vl-faint); margin-bottom: 0.3rem; }
.vl-seq .a { color: var(--vl-nt-a); }
.vl-seq .c { color: var(--vl-nt-c); }
.vl-seq .g { color: var(--vl-nt-g); }
.vl-seq .t { color: var(--vl-nt-t); }
.vl-seq .more { color: var(--vl-faint); }

/* ── result tables + tabs ───────────────────────────────────────── */
/* tab markup differs across Streamlit versions: baseweb tabs (≤1.58) and react-aria stTab (1.67+) */
:is([data-baseweb="tab"], [data-testid="stTab"]) p { font-weight: 600; font-size: 0.95rem; }
.st-key-features_table_help button, .st-key-records_table_help button { color: var(--vl-muted); }
.st-key-features_table_help button:hover, .st-key-records_table_help button:hover { color: var(--vl-primary-text); }

/* ── guide dialog + "How to read" popovers (ui/guide.py) ────────── */
/* Selectors are prefixed with .vl-guide so they outrank Streamlit's own
   list / paragraph styles inside st.html. */
.vl-guide { color: var(--vl-text); font-size: 0.9rem; line-height: 1.6; }
.vl-guide :is(p, ol, ul, li, dl, dt, dd) { font-size: inherit; line-height: inherit; }
.vl-guide code { font-family: var(--vl-mono); font-size: 0.84em; color: var(--vl-primary-text); background: var(--vl-primary-soft); padding: 0.05rem 0.3rem; border-radius: 0.3rem; }
.vl-guide-title { font-size: 1.15rem; font-weight: 800; letter-spacing: -0.01em; }
.vl-guide p.vl-guide-lead { color: var(--vl-muted); margin: 0.25rem 0 1rem; max-width: 42rem; }
.vl-guide-subtitle {
    font-size: 0.7rem;
    font-weight: 700;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    color: var(--vl-faint);
    margin: 1.2rem 0 0.55rem;
}
.vl-guide-subtitle:first-child { margin-top: 0; }
.vl-guide ol.vl-guide-steps { list-style: none; margin: 0 0 1rem; padding: 0; display: grid; gap: 0.75rem; }
.vl-guide .vl-guide-steps li { display: flex; gap: 0.75rem; align-items: flex-start; margin: 0; padding: 0; }
.vl-guide-num {
    flex: none;
    width: 1.5rem;
    height: 1.5rem;
    margin-top: 0.05rem;
    border-radius: 0.45rem;
    display: grid;
    place-items: center;
    font-size: 0.75rem;
    font-weight: 800;
    color: var(--vl-primary-text);
    background: var(--vl-primary-soft);
}
.vl-guide-step-title { font-weight: 700; }
.vl-guide-step-body { color: var(--vl-muted); }
.vl-guide-paths { display: grid; grid-template-columns: repeat(auto-fit, minmax(14rem, 1fr)); gap: 0.75rem; }
.vl-guide-path { border: 1px solid var(--vl-border); border-radius: var(--vl-radius); padding: 0.85rem 1rem; background: var(--vl-surface-2); }
.vl-guide-path-name { font-family: var(--vl-mono); font-weight: 700; color: var(--vl-primary-text); }
.vl-guide-path-when { font-weight: 700; margin: 0.1rem 0 0.3rem; }
.vl-guide-table-wrap { overflow-x: auto; border: 1px solid var(--vl-border); border-radius: var(--vl-radius); }
.vl-guide-table { width: 100%; border-collapse: collapse; font-size: 0.84rem; }
.vl-guide-table th {
    text-align: left;
    font-size: 0.68rem;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: var(--vl-faint);
    background: var(--vl-surface-2);
    padding: 0.55rem 0.8rem;
    white-space: nowrap;
}
.vl-guide-table td { padding: 0.6rem 0.8rem; border-top: 1px solid var(--vl-border); vertical-align: top; color: var(--vl-muted); }
.vl-guide-table td:first-child { white-space: nowrap; }
.vl-guide-group { white-space: nowrap; font-weight: 600; }
.vl-guide dl.vl-terms { margin: 0; padding: 0; display: grid; gap: 0.1rem; }
.vl-term { display: grid; grid-template-columns: 8.5rem 1fr; gap: 0.75rem; padding: 0.45rem 0; border-bottom: 1px solid var(--vl-border); }
.vl-term:last-child { border-bottom: 0; }
.vl-guide .vl-term dt, .vl-guide .vl-term dd { margin: 0; padding: 0; line-height: 1.5; }
.vl-guide .vl-term dt { font-weight: 700; color: var(--vl-text); }
.vl-guide .vl-term dd { color: var(--vl-muted); }
.vl-guide-legend { display: grid; gap: 0.45rem; }
.vl-guide-legend-row { display: grid; grid-template-columns: 12.5rem 1fr; gap: 0.6rem; align-items: center; color: var(--vl-muted); font-size: 0.82rem; }
.vl-guide-legend-row .vl-badge { justify-self: start; }
.vl-guide ul.vl-guide-tips { margin: 0; padding-left: 1.1rem; color: var(--vl-muted); }
.vl-guide .vl-guide-tips li { margin: 0.1rem 0; padding: 0; }
.vl-guide-compact { width: min(36rem, 80vw); font-size: 0.82rem; line-height: 1.5; }
.vl-guide-compact .vl-term { grid-template-columns: 6.5rem 1fr; padding: 0.3rem 0; }
.vl-guide-compact .vl-guide-subtitle { margin: 0.9rem 0 0.4rem; }
.vl-guide-compact .vl-guide-subtitle:first-child { margin-top: 0; }

/* ── sidebar components ─────────────────────────────────────────── */
.vl-brand { display: flex; align-items: center; gap: 0.7rem; padding: 0.2rem 0 0.4rem; }
.vl-brand-mark {
    position: relative;
    flex: none;
    width: 2.25rem;
    height: 2.25rem;
    border-radius: 0.65rem;
    background: var(--vl-primary);
    color: var(--vl-on-primary);
    display: grid;
    place-items: center;
    font-weight: 800;
    font-size: 1.05rem;
}
.vl-brand-mark::after {
    content: "";
    position: absolute;
    right: -3px;
    bottom: -3px;
    width: 0.7rem;
    height: 0.7rem;
    border-radius: 999px;
    background: var(--vl-coral);
    border: 2px solid var(--vl-surface);
}
.vl-brand-name { font-weight: 800; font-size: 1.12rem; color: var(--vl-text); letter-spacing: -0.02em; line-height: 1.2; }
.vl-brand-sub { font-size: 0.74rem; color: var(--vl-faint); line-height: 1.35; }
.vl-nav-label {
    font-size: 0.68rem;
    font-weight: 700;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    color: var(--vl-faint);
    margin: 0.4rem 0 -0.3rem 0.1rem;
}
.vl-ctx { border: 1px solid var(--vl-border); border-radius: var(--vl-radius); background: var(--vl-surface-2); padding: 0.35rem 0.85rem; }
.vl-ctx-row { display: flex; justify-content: space-between; gap: 0.75rem; padding: 0.45rem 0; border-bottom: 1px solid var(--vl-border); font-size: 0.8rem; }
.vl-ctx-row:last-child { border-bottom: 0; }
.vl-ctx-label { color: var(--vl-muted); white-space: nowrap; }
.vl-ctx-value { font-family: var(--vl-mono); font-weight: 600; color: var(--vl-text); text-align: right; overflow-wrap: anywhere; min-width: 0; }
.vl-sidebar-foot { font-size: 0.72rem; color: var(--vl-faint); line-height: 1.5; }

/* ── alias manager: virus list + danger button ──────────────────── */
.st-key-alias_manager_virus [role="radiogroup"] { gap: 0.25rem; width: 100%; }
.st-key-alias_manager_virus [role="radiogroup"] > label {
    width: 100%;
    margin: 0;
    padding: 0.55rem 0.75rem;
    border-radius: var(--vl-radius-sm);
    border: 1px solid transparent;
    transition: background 140ms ease;
}
.st-key-alias_manager_virus [role="radiogroup"] > label:hover { background: var(--vl-surface-2); }
.st-key-alias_manager_virus [role="radiogroup"] > label:has(input:checked) {
    background: var(--vl-surface);
    border-color: var(--vl-border);
    box-shadow: var(--vl-shadow);
}
.st-key-alias_manager_virus [role="radiogroup"] > label:has(input:checked) p { font-weight: 700; color: var(--vl-text); }
.st-key-delete_virus_entry button {
    color: var(--vl-danger) !important;
    border-color: var(--vl-danger) !important;
    background: var(--vl-danger-soft) !important;
}

@media (max-width: 760px) {
    .stMainBlockContainer, .main .block-container { padding-top: 4.2rem; }
    .vl-stepper { flex-wrap: wrap; }
    .vl-step-line { display: none; }
    .vl-step-note { display: none; }
    .vl-term, .vl-guide-compact .vl-term, .vl-guide-legend-row { grid-template-columns: 1fr; gap: 0.2rem; }
}
@media (prefers-reduced-motion: reduce) {
    * { transition: none !important; }
}
"""

# Reads the background Streamlit painted and tags <html> so the CSS tokens
# above switch with Streamlit's own light/dark setting. Installed once per
# browser tab; re-checks cheaply because Streamlit swaps themes without a
# DOM event we can listen to.
_THEME_SYNC_JS = """
<div class="vl-boot"></div>
<script>
(function () {
  if (window.__vlThemeSync) { window.__vlThemeSync(); return; }
  var root = document.documentElement;
  function luminance(color) {
    var parts = (color || "").match(/[\\d.]+/g);
    if (!parts || parts.length < 3) return null;
    if (parts.length > 3 && parseFloat(parts[3]) === 0) return null;
    var c = parts.slice(0, 3).map(function (v) {
      v = parseFloat(v) / 255;
      return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
    });
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2];
  }
  function sync() {
    var app = document.querySelector('[data-testid="stApp"]') || document.querySelector(".stApp");
    if (!app) return;
    var lum = luminance(getComputedStyle(app).backgroundColor);
    if (lum === null) return;
    var mode = lum < 0.35 ? "dark" : "light";
    if (root.getAttribute("data-vl-theme") !== mode) root.setAttribute("data-vl-theme", mode);
  }
  window.__vlThemeSync = sync;
  sync();
  setInterval(sync, 600);
})();
</script>
"""


def _theme_css() -> str:
    return (
        _CSS.replace("__LIGHT_TOKENS__", _token_block("light"))
        .replace("__DARK_TOKENS__", _token_block("dark"))
    )


def _inject_css():
    st.html("<style>" + _theme_css() + "</style>")
    st.html(_THEME_SYNC_JS, unsafe_allow_javascript=True)


def _nav_active_css(active_key: str) -> None:
    """Highlight the active sidebar workspace button (keyed by its widget key)."""
    st.html(
        "<style>"
        f".st-key-{active_key} button {{"
        "background: var(--vl-primary-soft) !important;"
        "color: var(--vl-primary-text) !important;"
        "}"
        f".st-key-{active_key} button p {{ font-weight: 700; }}"
        "</style>"
    )
