# In-app help: the "Guide" dialog behind the (?) button in every page header,
# and the "How to read" popovers next to the result tables. Content is plain
# data; `code` and **bold** spans are the only markup and are applied after
# escaping, so every string still goes through html.escape().
import html
import re
import streamlit as st
from typing import Dict, List, Tuple
from app.src.lifting.base import STATUS_META
from ui.components import _status_badge, _status_label, _status_tone
from app.src.lifting.gene_presence import NOT_IN_SEQUENCE
from ui.i18n import _t


# (title, body) pairs rendered as a numbered list.
Steps = List[Tuple[str, str]]

# Engine statuses plus the one the results view derives for partial records.
GUIDE_STATUSES = [*STATUS_META, NOT_IN_SEQUENCE]

PAGE_GUIDES: Dict[str, Dict[str, object]] = {
    "setup": {
        "title": "Set up a run",
        "lead": (
            "Give ViraLift one annotated reference and the genomes you want standardised. "
            "It handles each record on its own and only stops to ask about names it cannot resolve."
        ),
        "steps": [
            ("Add the reference", (
                "One GenBank record of the same virus with good CDS or mat_peptide annotation. "
                "Its genes decide what is searched for and which names appear in the output. "
                "Every reference you run with is saved: next time pick it from the list, or just "
                "add the query and the saved reference for its virus is selected for you."
            )),
            ("Check the reference map", (
                "Once a reference is chosen, **What this reference will look for** draws its genes "
                "on the genome, says which alias config names them, and how many query records are "
                "partial. A wrong reference or the wrong feature level shows here, before the run."
            )),
            ("Add the query records", (
                "A `.gb` / `.gbk` file with one or many records. Records that already carry gene "
                "annotation are renamed (**direct**); records without it are annotated from the "
                "reference proteins (**tblastn**). A Data crawler download can be sent here with **Use as query**."
            )),
            ("Choose the output names", (
                "Off: canonical names from the alias config, e.g. `Lpro`. "
                "On: the reference's own gene names, e.g. `Lab`."
            )),
            ("Lift genes the annotation is missing", (
                "On (default): reference genes an annotated record does not name, such as a genome "
                "annotated only as P1/P2/P3 precursors or with 2A and 3B left out, are lifted with "
                "tblastn. Its annotated genes stay exactly as they are; such a record shows "
                "**Direct + tblastn** on the genome map. Off: annotated records return only the genes they name."
            )),
            ("Check annotations against the reference", (
                "On (default): every annotated gene is aligned to the reference protein of the same "
                "name, so a fragment, a gene with the wrong name or an annotation longer than the gene "
                "is caught, and tblastn's placement is used where it does better. Off: annotated genes "
                "are taken as they are."
            )),
            ("Change thresholds only if needed", (
                "**Min coverage** and **Min identity** decide when a tblastn hit is accepted, "
                "**E-value** drops weak hits, and **Rescue window** is how far (bp) a start or stop "
                "codon may move to repair a boundary. Min coverage and Min identity also apply to the "
                "annotation check."
            )),
            ("Continue", (
                "ViraLift reads both files and detects the virus from the reference metadata. "
                "If the virus is unknown, or the query uses names the alias config lacks, "
                "Review names opens first; otherwise the run starts straight away."
            )),
        ],
        "tip": (
            "The alias config is picked automatically through `app/config/virus_alias_registry.json`. "
            "Edit names and detection keywords in Alias manager."
        ),
    },
    "virus_review": {
        "title": "Choose the virus",
        "lead": (
            "The reference metadata (organism, definition, keywords) matched no registered virus, "
            "so ViraLift cannot tell which alias config to use."
        ),
        "steps": [
            ("Reuse a registered virus", (
                "Pick this for a virus you already have, for example a new strain name. Its alias "
                "config is used for this run. Optionally save one metadata value as a detection "
                "keyword so the next run recognises it without asking."
            )),
            ("Or create a new virus config", (
                "Starts a new alias config seeded from this reference's gene names. "
                "The next screen walks through it."
            )),
            ("Back", "Returns to Setup without changing anything."),
        ],
        "tip": "Nothing is written until you click **Use this config** or finish the new config.",
    },
    "bootstrap_alias": {
        "title": "Create an alias config",
        "lead": (
            "A new virus needs its own alias config: the standard gene names plus the other "
            "names that should map to them."
        ),
        "steps": [
            ("Reference canonical names", (
                "The reference's gene names become the first canonical names, the names ViraLift outputs. "
                "Add any that are missing."
            )),
            ("Virus registry entry", (
                "A display name and the detection keywords matched against reference metadata, "
                "so future runs pick this config automatically."
            )),
            ("Query-supported suggestions", (
                "**Generate suggestions** lifts the reference genes into the query genomes with tblastn "
                "and proposes query names whose annotation overlaps a lifted gene (IoU ≥ 0.90). "
                "For each row choose **Save alias**, **Exclude** or **Skip this run**."
            )),
            ("Save and continue", "Writes the config and the registry entry, then carries on with the run."),
        ],
        "tip": (
            "Save precise gene symbols such as `GP5`. Exclude broad descriptions such as "
            "`major envelope glycoprotein` that could match several genes."
        ),
    },
    "resolve": {
        "title": "Review unknown names",
        "lead": (
            "These query gene names are not in the alias config. Decide once per name; "
            "the decision applies to every record that uses it."
        ),
        "steps": [
            ("Check the virus and config", "The banner shows which alias config this run uses."),
            ("Reference genes missing from the config", (
                "If listed, add them as canonical names so they are recognised next time. "
                "Lifting works without this; they just keep their raw name."
            )),
            ("Position check", (
                "On opening, the reference genes are aligned to a few records carrying each name and "
                "compared with where the name is annotated. **Matches VP4** pre-fills the row; "
                "**spans VP4–VP1** means a precursor such as P1, never one gene. Each row draws it: "
                "the lifted reference genes on top, the annotated span as a dark bar under them."
            )),
            ("Map each name", (
                "Each row is one exact set of names, so a decision never covers a different "
                "annotation. Pick the canonical gene, or leave **exclude / keep raw name**."
            )),
            ("Choose what to save", (
                "Selected chips are written to the alias config for future runs. A name that also "
                "labels other genes in the file (such as `capsid protein`) is never pre-selected: "
                "as an alias it would rename those too."
            )),
            ("Suggest with LLM (optional)", (
                "A second opinion that also sees the position check and the existing aliases; it "
                "mainly judges whether a name is specific enough to save. Names, qualifier values, "
                "record IDs and coordinates are sent, never sequences."
            )),
            ("Run annotation", "Saves the selected aliases and starts the run."),
        ],
        "tip": "Missing a target? Use **Add canonical name** first, then map to it.",
    },
    "results": {
        "title": "Read the results",
        "lead": "Check the run's health first, then inspect individual genes and export what you trust.",
        "steps": [
            ("Run health", (
                "**Records**: query records processed (failures are listed below the tiles). "
                "**Features**: genes inside the sequenced records. **Pass rate**: share of those "
                "with a passing status. **Needs review**: genes to inspect before use."
            )),
            ("Partial records", (
                "Many GenBank entries hold one gene or region, e.g. a VP1-only sequence. Genes that "
                "fall outside such a record are marked **Not in sequence**: nothing to review, and "
                "they are left out of the pass rate. A **No hit** inside the record is a real miss."
            )),
            ("Status bar", "The share of each status across all features. The colours match the map."),
            ("Annotation check", (
                "How many annotated genes match the reference, and how many were partial, fragments, "
                "too divergent or longer than the gene. Click a gene on the genome map: its detail panel "
                "compares the annotation with tblastn and lets you choose which to use, or runs **Check "
                "with tblastn** on any annotated gene."
            )),
            ("Genome map tab", (
                "Opens first. The matrix has one row per record, every record of the run, and one column per "
                "reference gene, each column linked to its place on the reference bar: a partial record, "
                "a gene that fails everywhere or an odd record stands out at a glance. An orange corner "
                "marks a gene that passed but is much shorter than the reference gene. Filter by health, "
                "search, and **Sort** by needs review or by the lowest identity, coverage or length "
                "against the reference (each record's lowest, or the open gene's)."
            )),
            ("Genes and records", (
                "Click a gene name for that gene in every record, the records to check and a one-click "
                "FASTA export. Click a row or a cell to draw the record under the reference: ribbons join "
                "each reference gene to where it landed, so a shift, an insertion or a cut-short gene is "
                "visible. The detail panel under it shows the clicked gene's coordinates, its length "
                "against the reference, coverage and identity against the run's cut-offs, the boundary "
                "checks, the annotation check and the sequence."
            )),
            ("Export tab", (
                "TSV with every feature (display or raw source names), and FASTA per gene or combined, "
                "filtered by status, coverage and identity. Pick the genes by clicking them on the "
                "reference bar or in the list under it; **Select all** / **Unselect all** set them all "
                "at once. Review cases are left out unless you approve them. "
                "**Sequence names** builds each FASTA name from fields you pick, e.g. "
                "`AJ294911.1_O/HKN/21/70_porcine` (Accession_Isolate_Host); the choice is remembered."
            )),
        ],
        "tip": (
            "Green cells are ready to use. Blue cells passed after an adjustment; open one to see the "
            "**Rescue** if exact boundaries matter."
        ),
    },
    "crawler": {
        "title": "Fetch genomes from NCBI",
        "lead": "Download GenBank records from NCBI, split them by virus, and send one file into a run.",
        "steps": [
            ("NCBI account", (
                "NCBI requires an email address. An API key is optional and raises the limit from "
                "3 to 10 requests per second. **Advanced settings** holds the database, output folder "
                "and the dedup ledger, which skips records you downloaded before."
            )),
            ("Build the input dataset", (
                "**By query**: pick a registered virus (it fills the organism), the dataset type and "
                "optional length, date and region filters; the generated NCBI query is shown below. "
                "**By accession**: paste accession numbers."
            )),
            ("Preview and crawl", (
                "**Count records** shows how many records match before you download. "
                "**Crawl GenBank and split** downloads up to **Max records** and writes one GenBank file per virus."
            )),
            ("Use the output", (
                "Download a species file, or click **Use as query** to make it the query file in Run pipeline."
            )),
        ],
        "tip": "Records that match no registered virus go to an **Unmatched records** file.",
    },
    "alias": {
        "title": "Manage the alias database",
        "lead": (
            "Each virus has an alias config: its canonical gene names and every other name that "
            "should map to them. The registry decides which config a reference uses."
        ),
        "steps": [
            ("Pick a virus", "The list on the left shows every registered virus."),
            ("Reference genomes", (
                "The virus's saved references. Add one from a GenBank file, download it, remove it, "
                "or make it the **default**: the reference Run pipeline suggests when a query is "
                "detected as this virus, so everyone in the lab runs on the same one."
            )),
            ("Canonical aliases", (
                "Each canonical name is a standard output name. Its aliases are the spellings found "
                "in GenBank annotations, e.g. `GP5` and `ORF5 protein` for `ORF5`."
            )),
            ("Detection keywords", (
                "Matched against the reference metadata to pick this virus automatically. "
                "The virus name is the label shown in the app."
            )),
            ("Excluded names", (
                "Names that are never mapped automatically, such as `polyprotein`. "
                "Direct features with these names are skipped."
            )),
            ("Advanced", "Raw JSON and export. The danger zone removes a virus from the registry."),
        ],
        "tip": "Every edit is saved immediately, and a timestamped backup is written first.",
    },
}

STAGE_TOPICS = {
    "upload": "setup",
    "virus_review": "virus_review",
    "bootstrap_alias": "bootstrap_alias",
    "resolve": "resolve",
    "running": "results",
    "results": "results",
}

METHOD_GUIDE = [
    ("Direct", "The record is already annotated", (
        "Its CDS or mat_peptide names are matched against the alias config and renamed to canonical "
        "names. Coordinates stay exactly as annotated. Each annotated gene is also aligned to its "
        "reference protein (**Check annotations against the reference**), and one that fails is "
        "searched with tblastn. Reference genes the annotation does not name are lifted with tblastn "
        "(**Lift genes the annotation is missing**). Both options are on by default."
    )),
    ("tblastn", "The record has no usable annotation", (
        "Each reference protein is searched in the genome. The best hits are merged, checked for a "
        "start codon, a stop codon and an intact reading frame, and repaired within the rescue "
        "window when needed."
    )),
]

STATUS_GUIDE = {
    "ok": (
        "Clean result. tblastn: the hit clears both thresholds and the CDS has a start codon, a stop "
        "codon and whole codons. Direct: the annotated name maps to a reference gene."
    ),
    "ok_rescued": (
        "Passed after a boundary repair: the start and/or stop codon was moved within the rescue "
        "window. The detail panel shows the move, e.g. `start -12 bp`."
    ),
    "ok_extrapolated": (
        "mat_peptide only (no codon check). The alignment missed a few residues at an end of the "
        "reference peptide, so that end was extended by the same length."
    ),
    "ok_no_start_codon": (
        "The reference gene itself has no ATG start, e.g. a ribosomal-frameshift product such as "
        "PRRSV ORF1b, so the start follows the alignment."
    ),
    "ok_gap_filled": (
        "No usable hit, but the reference places this peptide directly between two neighbours that "
        "did lift, so it fills the gap between them."
    ),
    "not_in_reference": (
        "Direct: the name is a known canonical gene, but this reference does not annotate it. "
        "Kept as is."
    ),
    "invalid_boundaries": (
        "Strong protein match, but the CDS fails the start, stop or frame check and could not be repaired."
    ),
    "low_coverage": (
        "The alignment covers less of the reference protein than Min coverage. For an annotated gene "
        "the annotation check found it partial, e.g. a 69 nt \"VP1\" fragment of a short record."
    ),
    "low_identity": (
        "The alignment's amino-acid identity is below Min identity. For an annotated gene this often "
        "means the wrong name: the detail panel names the reference gene it really matches."
    ),
    "low_coverage_and_identity": "Both coverage and identity are below their thresholds.",
    "no_hit": "tblastn found no significant match for this reference protein.",
    "translation_fail": "The reference feature could not be translated into a protein, so it was not searched.",
    "overlong_annotation": (
        "Annotation check: the annotated gene is clearly longer than the reference gene, e.g. a "
        "\"VP1\" of 1,032 nt that also holds VP3's tail and 2A. When tblastn places the gene, its "
        "row is used instead; this status means it could not, so the annotation is kept for review."
    ),
    "unresolved_name": (
        "Direct: the annotated name is not in the alias config and was not mapped, so it keeps its raw name."
    ),
    NOT_IN_SEQUENCE: (
        "No hit, but the genes that were found place this one outside the record, which covers "
        "only part of the genome (e.g. a VP1-only sequence). Shown in the app only; exports keep `no_hit`."
    ),
}

TERMS = [
    ("Canonical name", "The standard gene name ViraLift writes to the output, e.g. `ORF5`."),
    ("Alias", "Another name for the same gene, e.g. `GP5`. Aliases live in the virus's alias config."),
    ("Raw name", "The gene name exactly as written in the query record's annotation."),
    ("Coverage", "Share of the reference protein covered by the alignment: tblastn's, or the annotation check's."),
    ("Identity", "Percentage of identical amino acids in that alignment."),
    ("E-value", "How likely a hit this good is by chance. Lower is stricter."),
    ("Bit score", "Alignment strength reported by tblastn. Higher is better."),
    ("Rescue", "Moving a start or stop codon so the CDS has valid boundaries."),
    ("Partial record", "A query record that covers only part of the reference genome, e.g. one gene."),
    ("Annotation check", (
        "Each annotated gene is translated and aligned to its reference protein. A gene that fails "
        "is searched with tblastn, which replaces it when it places the gene differently; the "
        "annotation stays in the detail panel and you can switch back."
    )),
]

# Shared by the table tooltips (column help) and the "How to read" popovers.
FEATURE_COLUMN_HELP = {
    "Record": "Query record (GenBank accession.version).",
    "Gene": "Standard gene name, or the reference's own name if you chose that.",
    "Status": "Outcome for this gene; the colour shows its group.",
    "Method": "Direct: renamed from the record's annotation. tblastn: found with the reference protein.",
    "Start": "First base on the query record, 1-based and inclusive (GenBank style). Blank when the gene was not found.",
    "End": "Last base. Start is the lower number on both strands.",
    "Length": "End − Start + 1, in nucleotides.",
    "Of reference": (
        "Length as a share of the reference gene's length. Far under 100% means a fragment or a "
        "gene cut short; over 100% an annotation longer than the gene."
    ),
    "Check": (
        "Annotation check for genes taken from the record's annotation: Matches reference, Partial, "
        "Fragment, Low identity or Longer than gene; → tblastn when tblastn's placement is used instead."
    ),
    "Coverage": (
        "Share of the reference protein the alignment covers: tblastn's, or for annotated genes the "
        "annotation check's (100% when the check is off). Blank when the gene was not placed."
    ),
    "Identity": "Amino-acid identity of the alignment. Blank for annotated genes when the check is off.",
    "Raw name": "Name as written in the query annotation. Blank for tblastn features.",
}

TONE_LEGEND = [
    ("ok", "Passed"),
    ("info", "Passed after an adjustment"),
    ("warn", "Needs review"),
    ("danger", "Not found"),
    ("neutral", "Informational"),
]

def _rich(text: str) -> str:
    """Escape, then turn `code` and **bold** spans into markup."""
    out = html.escape(text)
    out = re.sub(r"`([^`]+)`", r"<code>\1</code>", out)
    return re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", out)


def _steps_html(steps: Steps) -> str:
    items = "".join(
        "<li>"
        f"<span class='vl-guide-num'>{index}</span>"
        f"<div><div class='vl-guide-step-title'>{_rich(title)}</div>"
        f"<div class='vl-guide-step-body'>{_rich(body)}</div></div>"
        "</li>"
        for index, (title, body) in enumerate(steps, start=1)
    )
    return f"<ol class='vl-guide-steps'>{items}</ol>"


def _terms_html(terms: List[Tuple[str, str]]) -> str:
    rows = "".join(
        f"<div class='vl-term'><dt>{_rich(term)}</dt><dd>{_rich(meaning)}</dd></div>"
        for term, meaning in terms
    )
    return f"<dl class='vl-terms'>{rows}</dl>"


def _legend_html() -> str:
    """One row per colour, listing the statuses that use it."""
    rows = []
    for tone, meaning in TONE_LEGEND:
        statuses = [_status_label(status) for status in GUIDE_STATUSES if _status_tone(status) == tone]
        rows.append(
            "<div class='vl-guide-legend-row'>"
            f"<span class='vl-badge tone-{tone}'>{html.escape(meaning)}</span>"
            f"<span>{html.escape(', '.join(statuses))}</span>"
            "</div>"
        )
    return "<div class='vl-guide-legend'>" + "".join(rows) + "</div>"


def _guide_topic() -> str:
    if st.session_state.app_mode == "Data crawler":
        return "crawler"
    if st.session_state.app_mode == "Alias manager":
        return "alias"
    return STAGE_TOPICS.get(st.session_state.stage, "setup")


def _page_guide_html(topic: str) -> str:
    guide = PAGE_GUIDES[topic]
    return (
        "<div class='vl-guide'>"
        f"<div class='vl-guide-title'>{_rich(guide['title'])}</div>"
        f"<p class='vl-guide-lead'>{_rich(guide['lead'])}</p>"
        f"{_steps_html(guide['steps'])}"
        f"<div class='vl-callout tone-info'><span class='vl-callout-icon'>i</span><div>{_rich(guide['tip'])}</div></div>"
        "</div>"
    )


def _workflow_html() -> str:
    paths = "".join(
        "<div class='vl-guide-path'>"
        f"<div class='vl-guide-path-name'>{_rich(name)}</div>"
        f"<div class='vl-guide-path-when'>{_rich(when)}</div>"
        f"<div class='vl-guide-step-body'>{_rich(body)}</div>"
        "</div>"
        for name, when, body in METHOD_GUIDE
    )
    flow = _steps_html([
        (_t("step_setup"), "Upload the reference and the query records."),
        (_t("step_review"), "Only when the virus or some gene names are unknown."),
        (_t("step_results"), "Inspect every gene and export TSV or FASTA."),
    ])
    return (
        "<div class='vl-guide'>"
        "<p class='vl-guide-lead'>ViraLift gives every gene in a set of viral genomes the same standard "
        "name, using one annotated reference. Each query record takes one of two paths:</p>"
        f"<div class='vl-guide-paths'>{paths}</div>"
        "<div class='vl-guide-subtitle'>The three steps of a run</div>"
        f"{flow}"
        "<div class='vl-guide-subtitle'>Where the names come from</div>"
        "<p class='vl-guide-lead'>"
        + _rich(
            "Each virus has an alias config in `app/config/`: canonical names plus their aliases. "
            "Review names adds to it as you go; Alias manager edits it directly."
        )
        + "</p></div>"
    )


def _counts_as(status: str) -> str:
    if status == NOT_IN_SEQUENCE:
        return "Not counted"
    return "Passed" if STATUS_META[status].get("is_pass") else "Review"


def _status_reference_html() -> str:
    rows = "".join(
        "<tr>"
        f"<td>{_status_badge(status)}</td>"
        f"<td>{_rich(STATUS_GUIDE.get(status, ''))}</td>"
        f"<td class='vl-guide-group'>{_counts_as(status)}</td>"
        "</tr>"
        for status in GUIDE_STATUSES
    )
    return (
        "<div class='vl-guide'>"
        "<div class='vl-guide-subtitle'>Statuses</div>"
        "<div class='vl-guide-table-wrap'><table class='vl-guide-table'>"
        "<thead><tr><th>Status</th><th>Meaning</th><th>Counts as</th></tr></thead>"
        f"<tbody>{rows}</tbody></table></div>"
        "<div class='vl-guide-subtitle'>Terms</div>"
        f"{_terms_html(TERMS)}"
        "</div>"
    )


@st.dialog("ViraLift guide", width="large", icon=":material/help:")
def _open_guide() -> None:
    page, workflow, reference = st.tabs([_t("guide_this_page"), _t("guide_workflow"), _t("guide_reference")])
    with page:
        st.html(_page_guide_html(_guide_topic()))
    with workflow:
        st.html(_workflow_html())
    with reference:
        st.html(_status_reference_html())


