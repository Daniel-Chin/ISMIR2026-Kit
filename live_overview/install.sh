#!/usr/bin/env bash
# The static build uses only the Python standard library (3.9+ for zoneinfo).
set -euo pipefail
PYTHON="${PYTHON:-python3}"
"$PYTHON" -c 'import sys, zoneinfo; assert sys.version_info >= (3, 9); zoneinfo.ZoneInfo("Asia/Dubai")' \
  || { echo "Live Overview needs Python 3.9+ with time zone data (install tzdata)." >&2; exit 1; }
echo "Live Overview: no extra dependencies required."
