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
| cwebp / gif2webp | images-to-webp |
| rar | rar-archive.py |

Debian/Ubuntu example:

```bash
sudo apt install libimage-exiftool-perl ffmpeg imagemagick webp rar
```

Python media scripts use **stdlib only** — no venv or pip packages. VCF tools need `phonenumbers` and `vobject` (see [VCF tools](#vcf-tools)).

## Core tools

`rename-exif`, `images-to-jpg`, `images-to-webp`, `rename-lowercase`, and `videos-to-mp4` default to **dry-run**: planned changes print to stdout, no log file. Pass **`-x` / `--execute`** to apply changes; execute mode writes a TSV log only (no per-line stdout), defaulting to `{tool}_YYYY-mm-DD__HH_MM_SS.log` beside the output or input.

The three directory tools share `-i` / `-o` / `-x` / `--force` / `--log`.

| Script | Purpose |
|--------|---------|
| `rename-exif.py` | Rename (in place) or copy with EXIF-based names |
| `images-to-jpg.py` | Convert images → JPEG with metadata |
| `images-to-webp.py` | Resize + convert images → WebP |
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

# Apply changes (writes TSV log)
images-to-jpg.py -i ./photos -x --all-images

# Preview only (default)
images-to-webp.py -i ./photos
```

### TSV log format

When executing with `-x`, each run writes tab-separated rows with header `timestamp_utc`, `operation`, `status`, `source_path`, `dest_path`, `action`, `message`, `bytes_in`, `bytes_out`. Lines starting with `#` are comments. Default log name: `{tool}_YYYY-mm-DD__HH_MM_SS.log`. Parse with `csv.DictReader(..., delimiter='\t')` after skipping `#` lines.

## VCF tools

Validate, merge, dedupe, and subtract vCard contact files by E.164 phone number. Intended for preparing a **good** canonical contacts file before ingest in message-vault or other archives.

First run creates `archive-tools/.venv` and installs `requirements-vcf.txt` when `phonenumbers` / `vobject` are not already importable (message-vault's `.venv` also satisfies this when wrappers delegate).

| Script | Purpose |
|--------|---------|
| `vcf-validate.py` | Report or fix E.164 normalization (`--fix` creates `.vcf.bak`) |
| `vcf-merge.py` | Merge base + secondary VCFs; base wins on overlap |
| `vcf-dedupe.py` | One named contact per phone; drop unknown/group labels |
| `vcf-subtract.py` | Remove base entries whose phones appear in an exclude VCF |

```bash
# Normalize iPhone export
vcf-validate.py -c US --fix config/contacts.vcf

# Merge Android source VCFs into iPhone base
vcf-merge.py config/contacts.vcf staging/contacts_gosms.vcf -o config/contacts.merged.vcf

# Preview merge without writing
vcf-merge.py config/contacts.vcf staging/contacts_gosms.vcf -n

# Dedupe a messy export
vcf-dedupe.py staging/contacts_raw.vcf -o staging/contacts_clean.vcf

# Remove phones already covered by iPhone export
vcf-subtract.py staging/combined.vcf config/contacts.vcf -n
```

Common flags: `-c US` (default region), `-n` (dry-run), `-o PATH` (output), `--no-sms-tag`, `--allow-duplicate-names`.

## Other scripts

| Script | Description |
|--------|-------------|
| `rename-lowercase.py` | Recursively lowercase file basenames (`-d` dir; `-x` to apply) |
| `rename-jpeg.py` | Rename `.jpeg` → `.jpg` with collision-safe suffixes (`-d`, `-x`) |
| `embed-immich-xmp.sh` | Embed Immich `.xmp` sidecars into library media |
| `rar-archive.py` | Split RAR5 archive (`--rr` recovery %, optional `--md` dictionary) |

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
| `lib/webp_convert.py` | WebP resize/convert (cwebp, gif2webp, ImageMagick) |
| `lib/cli_common.py` | Shared argparse flags |
| `lib/phone.py` | E.164 normalization and contact-name heuristics |
| `lib/vcf.py` | vCard load/write, validate, merge, dedupe, subtract |

## Consumers

- **message-vault** — `convert-media.py` / `sync-media.py` import `lib.media_convert`; `vcf.sh` and `images-to-jpg.sh` delegate to CLIs. One-off folder jobs use `images-to-jpg.py` and `videos-to-mp4.py` here directly.
