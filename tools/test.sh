#!/usr/bin/env bash
set -euo pipefail
docker build -f Dockerfile.test -t lawn-growth-test .
docker run --rm lawn-growth-test python -m pytest "$@"
