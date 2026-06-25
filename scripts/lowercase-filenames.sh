#!/usr/bin/env bash
# lowercase-filenames.sh — Recursively rename files to lowercase basenames
#
# Usage:
#   lowercase-filenames.sh -d DIR [-n]

set -euo pipefail

DIR=""
DRY_RUN=false

RENAMED=0
SKIPPED=0
CONFLICTS=0

usage() {
	cat <<EOF
Usage: $(basename "$0") -d DIR [options]

Rename every file under DIR so the basename uses only lowercase letters.
Directory names are left unchanged. Processes deepest paths first.

Options:
  -d DIR    Root directory (required)
  -n        Dry-run — print renames only
  -h        Show this help

Examples:
  $(basename "$0") -d ./takeout -n
  $(basename "$0") -d /pool/archive/cloud_backups/immich/upload
EOF
}

die() {
	echo "error: $*" >&2
	exit 1
}

rename_file() {
	local src="$1"
	local dir base lower dest tmp

	dir=$(dirname "$src")
	base=$(basename "$src")
	lower="${base,,}"
	dest="$dir/$lower"

	[[ "$base" == "$lower" ]] && return 0

	if $DRY_RUN; then
		echo "rename: $src -> $dest"
		RENAMED=$((RENAMED + 1))
		return 0
	fi

	if [[ -e "$dest" ]]; then
		if [[ "$src" -ef "$dest" ]]; then
			tmp=$(mktemp)
			mv "$src" "$tmp"
			mv "$tmp" "$dest"
			RENAMED=$((RENAMED + 1))
		else
			echo "skip (conflict): $src -> $dest" >&2
			CONFLICTS=$((CONFLICTS + 1))
			return 1
		fi
	else
		mv "$src" "$dest"
		RENAMED=$((RENAMED + 1))
	fi
}

while getopts ":d:nh" opt; do
	case "$opt" in
	d) DIR="$OPTARG" ;;
	n) DRY_RUN=true ;;
	h)
		usage
		exit 0
		;;
	\?)
		die "unknown option: -$OPTARG"
		;;
	esac
done

[[ -n "$DIR" ]] || die "missing -d DIR"

DIR="${DIR%/}"
[[ -d "$DIR" ]] || die "directory not found: $DIR"

echo "Directory: $DIR"
$DRY_RUN && echo "Mode:      dry-run"

while IFS= read -r -d '' file; do
	rename_file "$file" || SKIPPED=$((SKIPPED + 1))
done < <(find "$DIR" -depth -type f -print0)

echo "Renamed:   $RENAMED"
if [[ "$CONFLICTS" -gt 0 ]]; then
	echo "Conflicts: $CONFLICTS" >&2
fi
if [[ "$SKIPPED" -gt 0 ]]; then
	echo "Skipped:   $SKIPPED" >&2
fi

if [[ "$CONFLICTS" -gt 0 ]]; then
	exit 1
fi

echo "Done."
