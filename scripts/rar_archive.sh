#!/usr/bin/env bash
# rar_archive.sh — Create a RAR5 archive with recovery record from a folder
#
# RAR options used:
#   -ma5    → RAR5 archive format
#   -m4     → Compression method “Good”
#   -md128m → 128 MB dictionary size
#   -v10g   → Split into 10 GB volumes
#   -rr10%  → 10% recovery record
#   -htb    → Use BLAKE2 checksums for file names (RAR5 feature)
#   -r      → Recurse subdirectories

set -euo pipefail

usage() {
	cat <<EOF
Usage: $(basename "$0") <folder-to-archive>

Create a split RAR5 archive with recovery record from a folder.

Requires: rar
EOF
}

if [[ $# -lt 1 || "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
	usage
	exit 0
fi

command -v rar >/dev/null 2>&1 || {
	echo "error: rar not found on PATH" >&2
	exit 1
}

INPUT_DIR="$1"
BASENAME=$(basename "${INPUT_DIR%/}")
ARCHIVE_NAME="${BASENAME}.rar"

rar a -ma5 -m4 -md128m -v10g -rr10% -htb -r "${ARCHIVE_NAME}" "${INPUT_DIR}"

echo "Testing archive integrity..."
rar t "${ARCHIVE_NAME}"

echo "Archive created and tested: ${ARCHIVE_NAME}"
