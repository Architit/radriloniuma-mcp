#!/usr/bin/env bash
set -euo pipefail

# DevKit tool: fix literal backslash-n and escaped triple-quotes in Python files.
# Usage: devkit/fix_python_escapes.sh <path_to_python_file> [--in-place]

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCRIPT="$ROOT_DIR/devkit/fix_python_escapes.py"

if [[ $# -eq 0 ]]; then
  echo "Usage: $0 <file.py> [--in-place]"
  exit 2
fi

exec python3 "$SCRIPT" "$@"
