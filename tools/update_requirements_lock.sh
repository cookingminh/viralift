#!/bin/sh
# Re-resolve ui/requirements.txt inside the Dockerfile's pinned base image and
# write the exact versions to ui/requirements.lock, which the image installs.
#
#   tools/update_requirements_lock.sh
#
# Run it after editing ui/requirements.txt or bumping PYTHON_IMAGE, then run
# the tests and commit the lock on its own.
set -eu
cd "$(dirname "$0")/.."

base=$(sed -n 's/^ARG PYTHON_IMAGE=//p' Dockerfile)
[ -n "$base" ] || { echo "PYTHON_IMAGE not found in Dockerfile" >&2; exit 1; }

docker run --rm -e PIP_DISABLE_PIP_VERSION_CHECK=1 -v "$PWD/ui:/ui" "$base" sh -c '
    pip install --quiet --no-cache-dir --root-user-action=ignore -r /ui/requirements.txt &&
    {
        echo "# Exact versions installed in the Docker image. Generated from"
        echo "# ui/requirements.txt by tools/update_requirements_lock.sh; do not edit."
        pip freeze --all --exclude pip --exclude setuptools --exclude wheel
    } > /ui/requirements.lock
'
echo "wrote ui/requirements.lock ($(grep -vc '^#' ui/requirements.lock) packages)"
