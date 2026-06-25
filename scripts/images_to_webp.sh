#!/usr/bin/env bash
# images_to_webp.sh — Batch resize and convert images to WebP in the current directory
#
# Run from the directory containing source images. Uses GNU parallel.
#
# Environment variables:
#   QUALITY   WebP quality 0-100 (default: 80)
#   MAX       Max dimension in pixels (default: 1024)
#   JOBS      Parallel jobs (default: nproc or 4)
#   DRY_RUN   Set to 1 for dry-run (default: 0)
#   VERBOSE   Set to 0 for quiet (default: 1)

set -euo pipefail

: "${QUALITY:=80}"
: "${MAX:=1024}"
: "${JOBS:=$(nproc 2>/dev/null || echo 4)}"
: "${DRY_RUN:=0}"
: "${VERBOSE:=1}"

export MAX QUALITY JOBS DRY_RUN VERBOSE

have_cmd() { command -v "$1" >/dev/null 2>&1; }

if ! have_cmd identify && have_cmd convert; then
	echo "Note: using ImageMagick v6 'identify'/'convert' — ensure they're in PATH."
fi

process_file() {
	local file="$1"
	local ext="${file##*.}"
	local ext_l="${ext,,}"
	local out="${file%.*}.webp"

	if [[ -f "$out" ]]; then
		local base="${file%.*}"
		local suffix=1
		while [[ -f "${base}_${suffix}.webp" ]]; do suffix=$((suffix + 1)); done
		out="${base}_${suffix}.webp"
	fi

	local dims=""
	if have_cmd identify; then
		dims=$(identify -format "%w %h" -- "$file" 2>/dev/null || true)
	fi

	local width height need_resize=0
	if [[ -n "$dims" ]]; then
		read -r width height <<<"$dims"
		if [[ "$width" =~ ^[0-9]+$ && "$height" =~ ^[0-9]+$ ]]; then
			if (( width > MAX || height > MAX )); then
				need_resize=1
			fi
		else
			width="?"
			height="?"
		fi
	else
		width="?"
		height="?"
	fi

	[[ "$VERBOSE" -eq 1 ]] && printf 'PROCESS: %s -> %s (w=%s h=%s resize=%s)\n' "$file" "$out" "$width" "$height" "$need_resize"

	if [[ "$DRY_RUN" -eq 1 ]]; then
		return 0
	fi

	local tmp="${out}.tmp.$$"

	case "$ext_l" in
	gif)
		if have_cmd gif2webp; then
			if (( need_resize )); then
				gif2webp -q "$QUALITY" -resize "$MAX" 0 "$file" -o "$tmp" >/dev/null 2>&1 \
					|| { echo "WARN: gif2webp failed for $file; falling back to convert."; convert "$file" -coalesce -resize "${MAX}x${MAX}>" -quality "$QUALITY" "$tmp"; }
			else
				gif2webp -q "$QUALITY" "$file" -o "$tmp" >/dev/null 2>&1 \
					|| { echo "WARN: gif2webp failed for $file; falling back to convert."; convert "$file" -coalesce -resize "${MAX}x${MAX}>" -quality "$QUALITY" "$tmp"; }
			fi
		else
			convert "$file" -coalesce -resize "${MAX}x${MAX}>" -quality "$QUALITY" "$tmp"
		fi
		;;
	*)
		if have_cmd cwebp; then
			if (( need_resize )); then
				local resized_tmp="${file%.*}.resized.$$.$ext_l"
				convert "$file" -resize "${MAX}x${MAX}>" "$resized_tmp" >/dev/null 2>&1 \
					|| { echo "WARN: convert resize failed for $file; trying cwebp directly."; cwebp -q "$QUALITY" "$file" -o "$tmp" >/dev/null 2>&1 || true; }
				if [[ -f "$resized_tmp" ]]; then
					cwebp -q "$QUALITY" "$resized_tmp" -o "$tmp" >/dev/null 2>&1 \
						|| convert "$resized_tmp" -quality "$QUALITY" "$tmp"
					rm -f "$resized_tmp"
				fi
			else
				cwebp -q "$QUALITY" "$file" -o "$tmp" >/dev/null 2>&1 \
					|| convert "$file" -quality "$QUALITY" "$tmp"
			fi
		else
			if (( need_resize )); then
				convert "$file" -resize "${MAX}x${MAX}>" -quality "$QUALITY" "$tmp"
			else
				convert "$file" -quality "$QUALITY" "$tmp"
			fi
		fi
		;;
	esac

	if [[ -f "$tmp" ]]; then
		mv -f "$tmp" "$out"
		[[ "$VERBOSE" -eq 1 ]] && printf 'OK: %s\n' "$out"
	else
		if [[ ! -f "$out" && -f "$file" && "$(basename "$file")" != *.webp ]]; then
			if have_cmd cwebp; then
				cwebp -q "$QUALITY" "$file" -o "$tmp" >/dev/null 2>&1 || true
				if [[ -f "$tmp" ]]; then
					mv -f "$tmp" "$out"
					[[ "$VERBOSE" -eq 1 ]] && printf 'OK-fallback: %s\n' "$out"
					return 0
				fi
			fi
		fi

		echo "FAILED: conversion failed for $file"
		rm -f "$tmp"
	fi
}

export -f process_file have_cmd

find . -type f \( -iname '*.jpg' -o -iname '*.jpeg' -o -iname '*.png' -o -iname '*.gif' -o -iname '*.bmp' -o -iname '*.tif' -o -iname '*.tiff' \) -print0 \
	| parallel --will-cite -0 -j "$JOBS" process_file {}
