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
| [exiftool](https://exiftool.org/) | Most scripts |
| ffmpeg / ffprobe | `compress_large_videos.py`, `convert_images_to_jpg.*` |
| ImageMagick (`magick`/`convert`) | `convert_images_to_jpg.*`, `images_to_webp.sh` |
| heif-convert | `convert_images_to_jpg.py` (HEIC) |
| cwebp / gif2webp | `images_to_webp.sh` |
| GNU parallel | `images_to_webp.sh` |
| rar | `rar_archive.sh` |

Debian/Ubuntu example:

```bash
sudo apt install libimage-exiftool-perl ffmpeg imagemagick webp parallel rar
```

Python scripts use **stdlib only** — no venv or pip packages.

## Scripts

### Image conversion

| Script | Description |
|--------|-------------|
| `convert_images_to_jpg.sh` | Recursive non-JPEG → JPEG with EXIF preserved; handles Google Takeout sidecars; parallel `-j` |
| `convert_images_to_jpg.py` | Python image → JPEG (HEIC/PNG default; `--all-images` for more formats); in-place or mirrored output tree |

Use the `.sh` script for Takeout sidecar handling. Use the `.py` script for programmatic use or in-place conversion.

### Video compression

| Script | Description |
|--------|-------------|
| `compress_large_videos.py` | Scan tree, filter by size/resolution/fps, H.265 MP4 encode with metadata copy |

```bash
compress_large_videos.py -i ./videos --min-size 100M --list-only
compress_large_videos.py -i ./videos -o ./archive --min-size 50M --above-1080p
```

### Filename tools

| Script | Description |
|--------|-------------|
| `rename_by_exif.py` | Rename from EXIF capture time. Default: `YYYY-mm-DD__HH-MM-SS-{suffix}.ext`. With `--prefix`: `{PREFIX}-YYYY-mm-DD__HH-MM-SS.ext` |
| `lowercase_filenames.sh` | Recursively lowercase file basenames |

```bash
rename_by_exif.py cancun_trip ./photos          # dry run
rename_by_exif.py --execute cancun_trip ./photos
rename_by_exif.py --prefix --execute Ava ./photos
```

### Other

| Script | Description |
|--------|-------------|
| `embed_immich_xmp.sh` | Embed Immich `.xmp` sidecars into library media |
| `images_to_webp.sh` | Batch resize + convert to WebP (run from target directory) |
| `rar_archive.sh` | Split RAR5 archive with recovery record |

## Library modules

`lib/media_convert.py` and `lib/media_metadata.py` live under `scripts/lib/` and are shared by the Python CLIs.

## Consumers

- **message-vault** — `process_media_folder.py` orchestrates `convert_images_to_jpg.py` and `compress_large_videos.py` from this repo.
