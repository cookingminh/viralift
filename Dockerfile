# ── pinned toolchain ─────────────────────────────────────────────
# Everything that can change a result is pinned, so rebuilding a release
# reproduces it: the base image by digest, BLAST+ by its Debian version and
# the Python packages by ui/requirements.lock. Bump them deliberately, in
# their own commit (see "Releases and versions" in README.md).
ARG PYTHON_IMAGE=python:3.11.18-slim-trixie@sha256:07d4824036af339fa1b6ef769cc99d9c10a141769538b52b3b597c84f7a7b535
FROM ${PYTHON_IMAGE}

# ── system dependencies ──────────────────────────────────────────
# ncbi-blast+ provides tblastn, the only external binary the pipeline needs.
# (minimap2 was removed — the minimap lifting path is no longer part of ViraLift.)
# If Debian ever drops this exact version the build fails loudly instead of
# silently picking up a different BLAST+.
ARG BLAST_DEB_VERSION=2.16.0+ds-7
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ncbi-blast+=${BLAST_DEB_VERSION} \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /viralift

# ── python dependencies ──────────────────────────────────────────
# requirements.txt holds the allowed ranges; requirements.lock the exact
# versions resolved from them (tools/update_requirements_lock.sh).
COPY ui/requirements.lock /viralift/ui/requirements.lock
RUN pip install --no-cache-dir -r ui/requirements.lock

# ── application code ─────────────────────────────────────────────
COPY app  /viralift/app
COPY gbcrawler /viralift/gbcrawler
COPY ui   /viralift/ui
# Streamlit theme (light/dark palettes) and client settings
COPY .streamlit /viralift/.streamlit

# ── version stamp ────────────────────────────────────────────────
# Set by CI from the git tag and commit; shown in the app sidebar so
# everyone can tell which build they are running.
ARG VIRALIFT_VERSION=dev
ARG VIRALIFT_COMMIT=unknown
ENV VIRALIFT_VERSION=${VIRALIFT_VERSION} \
    VIRALIFT_COMMIT=${VIRALIFT_COMMIT}

# ── runtime ──────────────────────────────────────────────────────
ENV PYTHONPATH=/viralift
EXPOSE 8501

HEALTHCHECK CMD curl --fail http://localhost:8501/_stcore/health || exit 1

CMD ["streamlit", "run", "ui/streamlit_app.py", \
     "--server.port=8501", \
     "--server.address=0.0.0.0", \
     "--server.headless=true"]
