# 🧬 ViraLift

> Standardise viral gene names and assign annotation from a reference — and handle the NCBI data-collection step too.

ViraLift is a tool in a primer-design pipeline. It solves two classic problems with GenBank data: records that are **already annotated but have inconsistent gene names** (each lab names them differently), and records that are **not annotated at all**. The output is a set of genes with standardised names + coordinates, ready for downstream steps (e.g. extracting the ORF5 CDS for the whole input).

## Three modes

ViraLift is a Streamlit app with three modes, each with its own guide:

| Mode (UI) | Role | Guide |
|---|---|---|
| **Data crawler** | Collect data: fetch records from NCBI, split by species, dedup | [DATA_CRAWLER_GUIDE.md](DATA_CRAWLER_GUIDE.md) |
| **Run pipeline** | Core processing: standardise names + assign annotation, export TSV/FASTA | [PIPELINE_RUNNER_GUIDE.md](PIPELINE_RUNNER_GUIDE.md) |
| **Alias manager** | Manage the gene-name dictionary (canonical/alias) per virus | [ALIAS_MANAGER_GUIDE.md](ALIAS_MANAGER_GUIDE.md) |

Deep technical docs about the code: [CODEBASE_GUIDE.md](CODEBASE_GUIDE.md). The Data crawler engine: [gbcrawler/README.md](gbcrawler/README.md). Internal validation & paper notes (Vietnamese): [docs/](docs/README.md).

## The problem

GenBank records for the same gene are often labelled very differently, across many qualifier fields (`/gene`, `/product`, `/note`...):

| Virus | Same gene, many naming styles |
|---|---|
| PRRSV | `GP5` · `gp5` · `glycoprotein 5` · `major envelope glycoprotein` · `ORF5` |
| FMDV | `3Cpro` · `3C` · `protease 3C` · `3C protease` |

Depending on the record, this creates two situations:

```text
Case 1 — Query already annotated, but names non-standard
  -> Standardise names via alias lookup (fast, no alignment)

Case 2 — Query not annotated
  -> Lift coordinates from the reference via tblastn, then name
```

Run pipeline handles **both** automatically in a single run.

## Pipeline overview

The three modes form one seamless flow:

```text
        ┌──────────────┐
        │ Data crawler │   fetch from NCBI, split by species
        └──────┬───────┘
               │  <species>.gb files (full feature-bearing GenBank)
               v
        ┌──────────────┐      ┌───────────────┐
        │ Run pipeline │◄─────│ Alias manager │  gene-name dictionary
        └──────┬───────┘      └───────────────┘  (canonical/alias)
               │  TSV + FASTA (standardised names + coordinates)
               v
        downstream primer-pipeline steps (e.g. extract ORF5)
```

- **Data crawler** prepares clean input (correct format, split by species).
- **Run pipeline** is the core processing, using a reference + alias config.
- **Alias manager** maintains the gene-name dictionary that Run pipeline looks up; all three share one virus registry (`app/config/virus_alias_registry.json`).

## Install & run

### Option 1 — Docker (recommended)

```bash
git clone https://github.com/cookingminh/viralift
cd viralift
docker compose pull      # download the published image, no build needed
docker compose up -d
```

Open **http://localhost:8501**. The sidebar shows which version you are running. No `.env` is needed to run; add one only to enable the optional LLM alias review (see below).

- **Update to the newest release:** `git pull && docker compose pull && docker compose up -d`
- **Run a specific version**, e.g. to reproduce a published result: `VIRALIFT_IMAGE_TAG=0.2.0 docker compose up -d` (or put `VIRALIFT_IMAGE_TAG=0.2.0` in `.env`)
- **Build from this checkout instead** (when changing the code): `docker compose up -d --build`

Alias configs, outputs and logs stay in `app/config`, `output` and `logs` on your machine, so they survive image updates.

### Option 2 — Run locally

```bash
cd viralift
python -m venv .venv && source .venv/bin/activate
pip install -r ui/requirements.txt
# BLAST+ (tblastn, makeblastdb) must be installed via the OS package manager, not pip
streamlit run ui/streamlit_app.py
```

> **BLAST+** is only needed for tblastn: assigning annotation to records that lack it, and lifting the genes an annotated record does not name. Name standardisation alone does not need BLAST+.

### Command line

The same pipeline runs without the UI:

```bash
python -m app.src.main --reference ref.gb --query genomes.gb --output output/run
```

An annotated record keeps its own coordinates and, by default, returns only the genes it names. Add `--lift-missing` to also lift, with tblastn, the reference genes it does not name: a genome annotated only as P1/P2/P3 precursors, or with short peptides such as 2A and 3B left out. The annotated rows are not changed, and genes that lie outside a partial record are not searched. The flag is off on the command line so the output matches earlier validated runs; the app turns it on (Setup → *Lift genes the annotation is missing*).

Add `--check-annotations` to check every annotated gene against the reference protein of the same name: the annotated sequence is translated and aligned to it, so its coverage and identity are measured rather than assumed (a 69 nt "VP1" fragment gets 11%, not 100%), and the same Min coverage / Min identity thresholds apply. A gene that fails (partial, too divergent, or clearly longer than the gene, e.g. a 1,032 nt "VP1" that also holds VP3's tail and 2A) is searched with tblastn, whose row replaces it when it places the gene differently. The TSV then gains `annotation_check`, `best_match`, `annotation_start` and `annotation_end` columns. Off on the command line, on in the app (Setup → *Check annotations against the reference*). `python -m app.src.main --help` lists every option.

### Optional LLM alias review

ViraLift can automatically review low-confidence bootstrap alias suggestions with an LLM. The core pipeline still works without this.

```bash
cp .env.example .env
# edit .env:
#   VIRALIFT_LLM_ENABLED=1
#   OPENAI_API_KEY=...
docker compose up -d
```

Only uncertain alias rows are sent for review; sequence data and full GenBank records are not included.

## Releases and versions

GitHub Actions (`.github/workflows/ci.yml`) tests every pull request and push, then publishes the image to GHCR:

| Event | Image tags (`ghcr.io/cookingminh/viralift:<tag>`) |
|---|---|
| push to `main` | `main`, `sha-<commit>` |
| tag `vX.Y.Z` | `X.Y.Z`, `X.Y`, `latest` |

Each image pins everything that can change a result: the Python base image by digest, BLAST+ by its Debian version (`BLAST_DEB_VERSION` in the `Dockerfile`) and the Python packages by `ui/requirements.lock`. A given version therefore always runs the same software, on amd64 PCs and arm64 (Apple Silicon) Macs alike.

**Citing a version.** Report the image tag and its digest, which never changes even if a tag is re-pushed:

```bash
docker inspect --format '{{index .RepoDigests 0}}' ghcr.io/cookingminh/viralift:0.2.0
```

Alias configs live outside the image (`app/config`) and change as people use the app, so report the alias config's fingerprint as well; the validation run manifest records it.

**Making a release.**
1. Set `version` in `pyproject.toml` to `X.Y.Z` and merge to `main`.
2. `git tag vX.Y.Z && git push origin vX.Y.Z`. CI runs the tests, builds and publishes; it refuses a tag that does not match `pyproject.toml`.

Tests that need the sample genomes in `app/data` (git-ignored) are skipped in CI, so run `pytest` locally before tagging.

**Updating dependencies.** Edit `ui/requirements.txt`, run `tools/update_requirements_lock.sh`, run the tests and commit the lock on its own. Bump the base image digest (`PYTHON_IMAGE`) or `BLAST_DEB_VERSION` the same way. Do this now and then to pick up security fixes, and re-run the validation before releasing: a new BLAST+ can change lifting results.

## Output

| File | Meaning |
|---|---|
| `extracted_cds.tsv` | Result table: standardised gene names + coordinates + mapping status |
| `extracted_cds.fasta` | Extracted gene sequences, filtered by coverage/status |
| `manifest.csv` (Data crawler) | Table of fetched records: accession, organism, status |

## Directory structure

```text
viralift/
├── app/                # pipeline engine (parse, lift, alias, io)
│   └── config/         # registry + per-virus alias config
├── gbcrawler/          # Data crawler engine (NCBI fetch + split)
├── ui/                 # Streamlit app (3 modes)
├── docs/               # internal validation & paper notes (Vietnamese)
├── README.md           # this file
├── DATA_CRAWLER_GUIDE.md
├── PIPELINE_RUNNER_GUIDE.md
├── ALIAS_MANAGER_GUIDE.md
└── CODEBASE_GUIDE.md
```
