#!/usr/bin/env bash
# embed_immich_xmp.sh — Embed Immich XMP sidecars into library media files
#
# Immich names sidecars photo.jpg.xmp (not photo.xmp). ExifTool pairs them with
# -tagsfromfile '%d%f.%e.xmp'. Videos are fully rewritten; use free disk space.
#
# Usage:
#   embed_immich_xmp.sh stats
#   embed_immich_xmp.sh embed [-n] [-d DIR]
#   embed_immich_xmp.sh verify [-d DIR] [-s N]
#   embed_immich_xmp.sh delete [-d DIR] [-y]
#   embed_immich_xmp.sh all [-d DIR] [-y]    # embed, verify, optional delete

set -euo pipefail

DEFAULT_DIR="."
PHOTO_EXTS=(jpg jpeg heic png)
VIDEO_EXTS=(mp4 mov)
ALL_EXTS=("${PHOTO_EXTS[@]}" "${VIDEO_EXTS[@]}")

DIR="$DEFAULT_DIR"
DRY_RUN=false
ASSUME_YES=false
SAMPLE_COUNT=3
ACTION=""

usage() {
	cat <<EOF
Usage: $(basename "$0") <command> [options]

Commands:
  stats              Count .xmp sidecars under DIR
  embed              Embed sidecar metadata into media files
  verify             Spot-check embedded metadata vs sidecars
  delete             Remove .xmp sidecars (requires -y)
  all                embed, then verify, then delete if -y

Options:
  -d DIR             Library directory (default: .)
  -n                 Dry-run for embed (show counts and command only)
  -s N               Samples per media type for verify (default: $SAMPLE_COUNT)
  -y                 Skip confirmation for delete / all
  -h                 Show this help

Examples:
  $(basename "$0") stats -d /path/to/library
  $(basename "$0") embed -n -d /path/to/library
  $(basename "$0") embed -d /path/to/library
  $(basename "$0") verify -d /path/to/library
  $(basename "$0") all -d /path/to/library -y
EOF
}

die() {
	echo "error: $*" >&2
	exit 1
}

require_exiftool() {
	command -v exiftool >/dev/null 2>&1 || die "exiftool not found; install libimage-exiftool-perl"
}

require_dir() {
	[[ -d "$DIR" ]] || die "directory not found: $DIR"
}

ext_args() {
	local args=()
	local ext
	for ext in "${ALL_EXTS[@]}"; do
		args+=(-ext "$ext")
	done
	printf '%s\n' "${args[@]}"
}

count_sidecars() {
	find "$DIR" -type f -iname '*.xmp' | wc -l | tr -d ' '
}

media_for_sidecar() {
	local sidecar="$1"
	local base="${sidecar%.xmp}"
	if [[ -f "$base" ]]; then
		printf '%s\n' "$base"
	fi
}

collect_samples() {
	local ext="$1"
	local limit="$2"
	local -a samples=()
	local sidecar media

	while IFS= read -r sidecar; do
		media=$(media_for_sidecar "$sidecar") || true
		[[ -n "${media:-}" ]] || continue
		[[ "${media##*.}" == "$ext" || "${media##*.}" == "${ext^^}" ]] || continue
		samples+=("$media")
		(( ${#samples[@]} >= limit )) && break
	done < <(find "$DIR" -type f -iname "*.${ext}.xmp" 2>/dev/null)

	printf '%s\n' "${samples[@]}"
}

tag_value() {
	local file="$1"
	local tag="$2"
	exiftool -s3 -"$tag" "$file" 2>/dev/null | head -n 1
}

has_value() {
	local value="${1//[[:space:]]/}"
	[[ -n "$value" ]]
}

verify_sample() {
	local media="$1"
	local xmp="${media}.xmp"
	local failures=0
	local tag value_xmp value_media

	[[ -f "$xmp" ]] || {
		echo "  skip (no sidecar): $media"
		return 0
	}

	for tag in GPSLatitude GPSLongitude DateTimeOriginal CreateDate Description; do
		value_xmp=$(tag_value "$xmp" "$tag")
		[[ -n "$value_xmp" ]] || continue

		value_media=$(tag_value "$media" "$tag")
		if ! has_value "$value_media"; then
			echo "  FAIL $media — missing $tag (present in sidecar)"
			((failures++)) || true
		fi
	done

	if [[ $failures -eq 0 ]]; then
		echo "  ok   $media"
	fi

	return "$failures"
}

cmd_stats() {
	require_dir
	local total
	total=$(count_sidecars)
	echo "Directory: $DIR"
	echo "Sidecars:  $total"
	if [[ "$total" -eq 0 ]]; then
		return 0
	fi

	local ext sidecar_count
	for ext in "${ALL_EXTS[@]}"; do
		sidecar_count=$(find "$DIR" -type f -iname "*.${ext}.xmp" 2>/dev/null | wc -l | tr -d ' ')
		[[ "$sidecar_count" -gt 0 ]] && echo "  .${ext}.xmp: $sidecar_count"
	done
}

cmd_embed() {
	require_exiftool
	require_dir

	local sidecar_count
	sidecar_count=$(count_sidecars)
	echo "Directory: $DIR"
	echo "Sidecars:  $sidecar_count"

	if [[ "$sidecar_count" -eq 0 ]]; then
		echo "Nothing to embed."
		return 0
	fi

	local -a ext_flags=()
	while IFS= read -r flag; do
		ext_flags+=("$flag")
	done < <(ext_args)

	local cmd=(
		exiftool -api LargeFileSupport=1 -r
		"${ext_flags[@]}"
		-if '$xmpfile'
		-tagsfromfile '%d%f.%e.xmp' -all:all
		-overwrite_original
		"$DIR"
	)

	if $DRY_RUN; then
		printf 'Dry-run — would run:\n  '
		printf '%q ' "${cmd[@]}"
		printf '\n'
		return 0
	fi

	echo "Embedding metadata (this rewrites matching files)..."
	"${cmd[@]}"
	echo "Embed complete."
}

cmd_verify() {
	require_exiftool
	require_dir

	local failures=0
	local ext media

	echo "Directory: $DIR"
	echo "Verifying up to $SAMPLE_COUNT sample(s) per type..."

	for ext in "${ALL_EXTS[@]}"; do
		mapfile -t samples < <(collect_samples "$ext" "$SAMPLE_COUNT")
		if [[ ${#samples[@]} -eq 0 ]]; then
			echo "${ext}: no samples with sidecars"
			continue
		fi

		echo "${ext}:"
		for media in "${samples[@]}"; do
			verify_sample "$media" || failures=$((failures + 1))
		done
	done

	if [[ $failures -gt 0 ]]; then
		die "verify failed for $failures sample(s); do not delete sidecars"
	fi

	echo "Verify passed."
}

cmd_delete() {
	require_dir

	local sidecar_count
	sidecar_count=$(count_sidecars)
	[[ "$sidecar_count" -gt 0 ]] || {
		echo "No sidecars to delete."
		return 0
	}

	if ! $ASSUME_YES; then
		echo "About to delete $sidecar_count .xmp file(s) under $DIR"
		read -r -p "Type 'delete' to continue: " confirm
		[[ "$confirm" == "delete" ]] || die "aborted"
	fi

	echo "Deleting sidecars..."
	find "$DIR" -type f -iname '*.xmp' -delete
	echo "Deleted $sidecar_count sidecar(s)."
}

cmd_all() {
	cmd_embed
	cmd_verify
	if $ASSUME_YES; then
		cmd_delete
	else
		echo "Skipping delete (pass -y to remove sidecars after verify)."
	fi
}

while getopts ":d:ns:yh" opt; do
	case "$opt" in
	d) DIR="${OPTARG%/}" ;;
	n) DRY_RUN=true ;;
	s) SAMPLE_COUNT="$OPTARG" ;;
	y) ASSUME_YES=true ;;
	h)
		usage
		exit 0
		;;
	\?)
		die "unknown option: -$OPTARG"
		;;
	esac
done
shift $((OPTIND - 1))

ACTION="${1:-embed}"
shift || true

case "$ACTION" in
stats) cmd_stats ;;
embed) cmd_embed ;;
verify) cmd_verify ;;
delete) cmd_delete ;;
all) cmd_all ;;
-h | --help | help)
	usage
	;;
*)
	usage >&2
	die "unknown command: $ACTION"
	;;
esac
