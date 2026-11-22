# syntax=docker/dockerfile:1
#
# Image for the PIPELINE only (extract.py -> transform.py -> load.py).
# The API (api/) and dashboard (dashboard/) are not part of this image.
#
# Stages (a "stage" is one FROM block; a build can stop at any named stage):
#   base    shared foundation: Python, dependencies, pipeline code, non-root user
#   test    base + pytest + tests. Built in CI with: docker build --target test .
#   runtime LAST stage, so a plain `docker build .` produces this one. It is the
#           image you would actually run. It contains no pytest and no tests.
#
# SECRETS: none are baked in. Pass them when you RUN the container, for example
#   docker run --rm -e CONTENTFUL_SPACE_ID -e CONTENTFUL_ACCESS_TOKEN -e DATABASE_URL <image>
# Anything written with ENV/ARG/COPY is stored in the image layers and can be read
# by anyone who can pull the image.

# ---------------------------------------------------------------------------
# base
# ---------------------------------------------------------------------------

# Base image: Python 3.13 (same minor version as the GitHub workflows) on Debian "slim"
# (~120 MB instead of ~1 GB; nothing here needs a compiler because psycopg2-binary,
# pandas and numpy all ship prebuilt wheels).
#
# "@sha256:..." pins the exact image. This is the digest of the multi-platform INDEX
# for the tag python:3.13-slim, taken from the official Docker Hub repository
# (library/python) on 2026-11-22. A tag like 3.13-slim moves whenever Python or
# Debian publish a patch; a digest never does, so builds are reproducible and cannot
# be silently swapped. The trade-off: you also stop receiving security patches until
# you update this line by hand. To refresh: look up the new digest of python:3.13-slim
# on Docker Hub, replace it here, and update the date above.
FROM python:3.13-slim@sha256:e48f59cdba69a3cbd9ed2cf0f348d90d45a8d350d98134cf1070bc106ee9ed90 AS base

# PYTHONUNBUFFERED=1       send print/log output straight to stdout so `docker logs`
#                          and the Actions log show it live instead of at exit.
# PYTHONDONTWRITEBYTECODE=1 do not write .pyc files; they are useless in a throwaway
#                          container and the code directory is read-only for the app.
# PYTHONUTF8=1             force UTF-8 text I/O (same as pipeline.yml).
# PIP_NO_CACHE_DIR=1       same as `pip install --no-cache-dir`: pip's download cache
#                          would only make the image layer bigger.
# PIP_DISABLE_PIP_VERSION_CHECK=1  skip pip's "new version available" network call.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUTF8=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# An unprivileged user, so the pipeline does not run as root. If the process were ever
# compromised it would have far fewer rights. The fixed UID (10001) keeps file
# ownership predictable if you mount a folder later. No home directory, no login shell.
RUN useradd --system --uid 10001 --no-create-home --shell /usr/sbin/nologin appuser

# All scripts use paths relative to the current directory (data/raw, data/clean,
# data/reference/groups.json, sql/create_tables.sql), so they only work when run from the
# project root. WORKDIR creates /app and makes it the current directory for every later
# instruction and for the running container.
WORKDIR /app

# Layer ordering: copy ONLY the requirements file first and install, then copy the code.
# Docker caches each layer and rebuilds one only when its inputs change. Code changes
# often, requirements rarely, so an edit to load.py reuses the cached (slow) install.
COPY requirements.txt ./
RUN pip install -r requirements.txt

# Copy exactly what the pipeline needs, not "COPY . .". Together with .dockerignore this
# is defence in depth: a new file in the repo never ends up in the image by accident.
COPY extract.py transform.py load.py ./
COPY sql/create_tables.sql sql/
COPY data/reference/groups.json data/reference/

# The scripts write to data/raw and data/clean. Create those two (empty) folders and give
# ONLY them to appuser. The code stays owned by root, so the app cannot modify it.
RUN mkdir -p data/raw data/clean && chown appuser:appuser data/raw data/clean

# ---------------------------------------------------------------------------
# test: base + pytest + tests (never shipped)
# ---------------------------------------------------------------------------
FROM base AS test

# requirements-dev.txt starts with "-r requirements.txt", which exists from the base stage.
COPY requirements-dev.txt pytest.ini ./
RUN pip install -r requirements-dev.txt

# tests/ for the tests themselves; scripts/ because tests/test_run_summary.py imports
# scripts/run_summary.py.
COPY tests/ tests/
COPY scripts/ scripts/

USER appuser

# -m "not db"          the database tests need a Postgres service this container does not have.
# -p no:cacheprovider  the code directory is not writable by appuser, so pytest cannot
#                      create .pytest_cache; this turns the cache off instead of warning.
# CMD (not ENTRYPOINT) is only a default: `docker run <image> <other command>` replaces it.
CMD ["python", "-m", "pytest", "-m", "not db", "-p", "no:cacheprovider", "-q"]

# ---------------------------------------------------------------------------
# runtime: the image you would run. MUST stay the last stage so that a plain
# `docker build .` builds this one.
# ---------------------------------------------------------------------------
FROM base AS runtime

# Everything above needed root (installing packages). From here on, and when the
# container runs, the process is the unprivileged user.
USER appuser

# Containers are stateless: the filesystem is deleted when the container exits, and
# extract -> transform -> load pass data to each other through files in data/raw and
# data/clean. So all three steps run in ONE container, in order. "&&" stops at the first
# failure, and the container's exit code is that of the failing step.
# "exec" replaces the shell with Python for the last step, so signals (docker stop) reach
# Python and the exit code is Python's own.
# CMD, not ENTRYPOINT: you can still run one step with
#   docker run <image> python load.py --dry-run
CMD ["sh", "-c", "python extract.py && python transform.py && exec python load.py"]
