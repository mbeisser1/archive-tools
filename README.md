# archive-tools

Standalone Python and Bash scripts for converting and organizing media for archival purposes. Other repos (e.g. message-vault) call these tools via PATH or the `ARCHIVE_TOOLS` environment variable.

## Setup

```bash
export PATH="$HOME/repo/archive-tools/scripts:$PATH"
# or
export ARCHIVE_TOOLS="$HOME/repo/archive-tools/scripts"
```

## System dependencies

| Tool | Used by |
|------|---------|
| [exiftool](https://exiftool.org/) | rename-exif, images-to-jpg |
| ffmpeg / ffprobe | images-to-jpg, videos-to-mp4 |
| ImageMagick (`magick`/`convert`) | images-to-jpg |
| heif-convert | images-to-jpg (HEIC) |
| cwebp / gif2webp | images-to-webp.sh |
| GNU parallel | images-to-webp.sh |
| rar | rar-archive.sh |

Debian/Ubuntu example:

```bash
sudo apt install libimage-exiftool-perl ffmpeg imagemagick webp parallel rar
```

Python scripts use **stdlib only** — no venv or pip packages.

## Core tools

All three share `-i` / `-o` / `-n` / `--force` / `--log` and write a TSV log (`archive-tools.log` by default).

| Script | Purpose |
|--------|---------|
| `rename-exif.py` | Rename (in place) or copy with EXIF-based names |
| `images-to-jpg.py` | Convert images → JPEG with metadata |
| `videos-to-mp4.py` | Convert/compress videos → H.265 MP4 |

### Unified I/O

| `-i` | `-o` | Behavior |
|------|------|----------|
| file | omitted | Output beside source (rename / convert in place) |
| file | file | Single output path |
| file | dir | Output inside directory |
| dir | omitted | In-place / beside-source for all matches |
| dir | dir | Mirror tree under output root |

### Examples

```bash
# Rename in place (default)
rename-exif.py -i ./photos --label cancun_trip

# Copy renamed files to output tree
rename-exif.py -i ./photos -o ./renamed --label cancun_trip

# Convert images to JPEG beside sources
images-to-jpg.py -i ./takeout --all-images

# Mirror converted JPEGs to output tree
images-to-jpg.py -i ./takeout -o ./takeout-jpg --takeout-sidecars

# Compress videos to MP4 in output tree
videos-to-mp4.py -i ./clips -o ./clips-mp4 --min-size 20M --remux-if-skip

# Dry run
images-to-jpg.py -i ./photos -n
```

### TSV log format

Each run writes tab-separated rows with header `timestamp_utc`, `operation`, `status`, `source_path`, `dest_path`, `action`, `message`, `bytes_in`, `bytes_out`. Lines starting with `#` are comments. Parse with `csv.DictReader(..., delimiter='\t')` after skipping `#` lines.

## Other scripts

| Script | Description |
|--------|-------------|
| `lowercase-filenames.sh` | Recursively lowercase file basenames |
| `embed-immich-xmp.sh` | Embed Immich `.xmp` sidecars into library media |
| `images-to-webp.sh` | Batch resize + convert to WebP (run from target directory) |
| `rar-archive.sh` | Split RAR5 archive with recovery record |

## Library modules

Importable logic lives in `scripts/lib/` (underscore names). Hyphenated CLI scripts are not Python-importable.

| Module | Purpose |
|--------|---------|
| `lib/exif_rename.py` | EXIF read, collision-safe naming |
| `lib/image_convert.py` | Image iteration, JPEG conversion, Takeout sidecars |
| `lib/video_convert.py` | Probe, encode, remux, filters |
| `lib/media_convert.py` | Pixel/format conversion core |
| `lib/media_metadata.py` | exiftool metadata copy |
| `lib/io_paths.py` | `-i` / `-o` resolution |
| `lib/tsv_log.py` | TSV operation log |
| `lib/cli_common.py` | Shared argparse flags |

## Consumers

- **message-vault** — `process_media_folder.py` imports `lib.image_convert` and `lib.video_convert`.
