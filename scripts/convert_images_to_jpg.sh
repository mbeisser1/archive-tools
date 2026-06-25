#!/usr/bin/env bash
# convert_images_to_jpg.sh — Recursively convert non-JPEG images to JPEG
#
# Preserves date, GPS, and other metadata via exiftool after pixel conversion.
# Copies Google Takeout sidecars: photo.HEIC.supplemental-metadata.json →
# photo.JPG.supplemental-metadata.json (extension casing preserved)
#
# Usage:
#   convert_images_to_jpg.sh -i INPUT_DIR -o OUTPUT_DIR [-n] [-j N] [-q QUALITY]

set -euo pipefail

INPUT_DIR=""
OUTPUT_DIR=""
DRY_RUN=false
JOBS=4
QUALITY=92

# Matched case-insensitively (.HEIC, .heic, etc.)
CONVERT_EXTS=(heic heif png webp tiff tif gif bmp avif)
SKIP_EXTS=(jpg jpeg)

usage() {
	cat <<EOF
Usage: $(basename "$0") -i INPUT_DIR -o OUTPUT_DIR [options]

Convert non-JPEG images under INPUT_DIR to JPEG under OUTPUT_DIR, preserving
relative paths. Metadata (date, GPS, etc.) is copied from the source file.
Google Takeout sidecars are renamed to match the new JPEG name (same extension
capitalization as the source, e.g. .HEIC → .JPG, .heic → .jpg).
Input extensions are matched case-insensitively (.HEIC, .heic, .PNG, etc.).

Options:
  -i DIR    Input directory (required)
  -o DIR    Output directory (required)
  -n        Dry-run — list conversions only, no writes
  -j N      Parallel jobs (default: $JOBS)
  -q N      JPEG quality 1–100 (default: $QUALITY)
  -h        Show this help

Requires: exiftool (libimage-exiftool-perl), and ffmpeg or ImageMagick (magick/convert).

Examples:
  $(basename "$0") -i ./takeout -o ./takeout-jpg -n
  $(basename "$0") -i ./takeout -o ./takeout-jpg -j 8
EOF
}

die() {
	echo "error: $*" >&2
	exit 1
}

have_cmd() {
	command -v "$1" >/dev/null 2>&1
}

file_ext() {
	local base="${1##*/}"
	local ext="${base##*.}"
	[[ "$base" == "$ext" ]] && return 1
	printf '%s\n' "${ext,,}"
}

jpeg_ext_for() {
	local base="${1##*/}"
	local src_ext="${base##*.}"
	[[ "$base" == "$src_ext" ]] && {
		printf 'jpg\n'
		return
	}

	if [[ "$src_ext" == "${src_ext^^}" ]]; then
		printf 'JPG\n'
	elif [[ "$src_ext" == "${src_ext,,}" ]]; then
		printf 'jpg\n'
	else
		printf 'Jpg\n'
	fi
}

ext_in_list() {
	local ext="$1"
	shift
	local item
	for item in "$@"; do
		[[ "$ext" == "${item,,}" ]] && return 0
	done
	return 1
}

is_jpeg() {
	local ext
	ext=$(file_ext "$1") || return 1
	ext_in_list "$ext" "${SKIP_EXTS[@]}"
}

is_convertible() {
	local ext
	ext=$(file_ext "$1") || return 1
	ext_in_list "$ext" "${CONVERT_EXTS[@]}"
}

find_sidecar() {
	local src="$1"
	local dir name match

	if [[ -f "${src}.supplemental-metadata.json" ]]; then
		printf '%s\n' "${src}.supplemental-metadata.json"
		return 0
	fi

	dir=$(dirname "$src")
	name=$(basename "$src")
	match=$(find "$dir" -maxdepth 1 -type f -iname "${name}.supplemental-metadata.json" -print -quit 2>/dev/null || true)
	[[ -n "$match" ]] && printf '%s\n' "$match"
}

require_tools() {
	have_cmd exiftool || die "exiftool not found; install libimage-exiftool-perl"
	have_cmd ffmpeg || have_cmd magick || have_cmd convert ||
		die "need ffmpeg or ImageMagick (magick/convert) for pixel conversion"
}

output_path() {
	local src="$1"
	local rel="${src#"$INPUT_DIR"/}"
	local rel_dir
	rel_dir=$(dirname "$rel")
	local base stem jpg_ext
	base=$(basename "$rel")
	stem="${base%.*}"
	jpg_ext=$(jpeg_ext_for "$base")

	if [[ "$rel_dir" == "." ]]; then
		printf '%s/%s.%s\n' "$OUTPUT_DIR" "$stem" "$jpg_ext"
	else
		printf '%s/%s/%s.%s\n' "$OUTPUT_DIR" "$rel_dir" "$stem" "$jpg_ext"
	fi
}

ffmpeg_qscale() {
	# ffmpeg -q:v is 1 (best) … 31 (worst); map script quality 100 … 1
	local q=$((31 - (QUALITY * 30) / 100))
	(( q < 1 )) && q=1
	(( q > 31 )) && q=31
	printf '%s\n' "$q"
}

convert_pixels() {
	local src="$1"
	local dest="$2"
	local fq
	fq=$(ffmpeg_qscale)

	if have_cmd ffmpeg; then
		if ffmpeg -hide_banner -loglevel error -y -i "$src" -q:v "$fq" "$dest"; then
			return 0
		fi
	fi

	if have_cmd magick; then
		magick "$src" -auto-orient -quality "$QUALITY" "$dest"
		return 0
	fi

	if have_cmd convert; then
		convert "$src" -auto-orient -quality "$QUALITY" "$dest"
		return 0
	fi

	return 1
}

copy_metadata() {
	local src="$1"
	local dest="$2"

	exiftool -q -q -tagsfromfile "$src" -all:all -overwrite_original "$dest"
	# Pixels were auto-oriented; avoid double-rotation in viewers
	exiftool -q -q -Orientation=1 -overwrite_original "$dest" 2>/dev/null || true
}

copy_sidecar() {
	local src="$1"
	local dest_jpg="$2"
	local src_sidecar dest_sidecar

	src_sidecar=$(find_sidecar "$src") || true
	[[ -n "${src_sidecar:-}" ]] || return 0

	dest_sidecar="${dest_jpg}.supplemental-metadata.json"

	if $DRY_RUN; then
		echo "  sidecar: $src_sidecar -> $dest_sidecar"
		return 0
	fi

	mkdir -p "$(dirname "$dest_sidecar")"
	cp -a "$src_sidecar" "$dest_sidecar"
}

process_file() {
	local src="$1"
	local dest
	dest=$(output_path "$src")

	is_jpeg "$src" && return 0
	is_convertible "$src" || return 0

	if [[ -f "$dest" ]]; then
		echo "skip (exists): $dest"
		return 0
	fi

	if $DRY_RUN; then
		echo "convert: $src -> $dest"
		copy_sidecar "$src" "$dest"
		return 0
	fi

	mkdir -p "$(dirname "$dest")"

	if ! convert_pixels "$src" "$dest"; then
		echo "FAIL convert: $src" >&2
		rm -f "$dest"
		return 1
	fi

	if ! copy_metadata "$src" "$dest"; then
		echo "FAIL metadata: $src" >&2
		rm -f "$dest"
		return 1
	fi

	copy_sidecar "$src" "$dest"
	echo "ok: $dest"
}

run_parallel() {
	local -a files=("$@")
	local running=0
	local failed=0
	local f pid

	for f in "${files[@]}"; do
		while (( running >= JOBS )); do
			if ! wait -n; then
				failed=$((failed + 1))
			fi
			running=$((running - 1))
		done
		process_file "$f" &
		running=$((running + 1))
	done

	while (( running > 0 )); do
		if ! wait -n; then
			failed=$((failed + 1))
		fi
		running=$((running - 1))
	done

	return "$failed"
}

while getopts ":i:o:nj:q:h" opt; do
	case "$opt" in
	i) INPUT_DIR="$OPTARG" ;;
	o) OUTPUT_DIR="$OPTARG" ;;
	n) DRY_RUN=true ;;
	j) JOBS="$OPTARG" ;;
	q) QUALITY="$OPTARG" ;;
	h)
		usage
		exit 0
		;;
	\?)
		die "unknown option: -$OPTARG"
		;;
	esac
done

[[ -n "$INPUT_DIR" ]] || die "missing -i INPUT_DIR"
[[ -n "$OUTPUT_DIR" ]] || die "missing -o OUTPUT_DIR"
(( JOBS >= 1 )) || die "jobs must be >= 1"
(( QUALITY >= 1 && QUALITY <= 100 )) || die "quality must be 1–100"

INPUT_DIR="${INPUT_DIR%/}"
OUTPUT_DIR="${OUTPUT_DIR%/}"
[[ -d "$INPUT_DIR" ]] || die "input directory not found: $INPUT_DIR"

if ! $DRY_RUN; then
	require_tools
	mkdir -p "$OUTPUT_DIR"
fi

find_args=()
for ext in "${CONVERT_EXTS[@]}"; do
	if [[ ${#find_args[@]} -eq 0 ]]; then
		find_args+=(-iname "*.${ext}")
	else
		find_args+=(-o -iname "*.${ext}")
	fi
done

mapfile -d '' -t FILES < <(
	find "$INPUT_DIR" -type f '(' "${find_args[@]}" ')' -print0 |
		while IFS= read -r -d '' f; do
			if is_convertible "$f" && ! is_jpeg "$f"; then
				printf '%s\0' "$f"
			fi
		done
)

if [[ ${#FILES[@]} -eq 0 ]]; then
	echo "No convertible images found under $INPUT_DIR"
	exit 0
fi

echo "Input:  $INPUT_DIR"
echo "Output: $OUTPUT_DIR"
echo "Files:  ${#FILES[@]}"
$DRY_RUN && echo "Mode:   dry-run"

failed=0
if $DRY_RUN || (( JOBS == 1 )); then
	for f in "${FILES[@]}"; do
		process_file "$f" || failed=$((failed + 1))
	done
else
	run_parallel "${FILES[@]}" || failed=$?
fi

if [[ "$failed" -gt 0 ]]; then
	die "$failed file(s) failed"
fi

echo "Done."
