#!/usr/bin/env python3
"""Convert and compress videos to MP4 (H.265)."""

from __future__ import annotations

import argparse
import os
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from lib.cli_common import add_io_args  # noqa: E402
from lib.io_paths import resolve_io, run_log_path  # noqa: E402
from lib.tsv_log import LogEntry, TsvLog  # noqa: E402
from lib.video_convert import (  # noqa: E402
    CANONICAL_VIDEO_EXT,
    ScanCriteria,
    build_scan_criteria_from_args,
    convert_one,
    criteria_summary,
    format_bytes,
    is_video_file,
    iter_matching_videos,
    matches_criteria,
    parse_size,
    print_thread_budget,
    probe_summary,
    probe_video,
    resolve_thread_budget,
    result_action,
    result_log_status,
    scan_needs_probe,
)

OPERATION = "video"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Convert and compress videos to MP4 (libx265).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    add_io_args(parser)
    filters = parser.add_argument_group("filters (AND)")
    filters.add_argument("--min-size", type=parse_size, default=0, metavar="SIZE")
    filters.add_argument("--above-720p", action="store_true")
    filters.add_argument("--above-1080p", action="store_true")
    filters.add_argument("--4k", dest="four_k", action="store_true")
    filters.add_argument("--min-long-edge", type=int, default=None, metavar="PX")
    filters.add_argument("--fps-above", type=float, default=None, metavar="FPS")
    parser.add_argument("--jobs", "-j", type=int, default=1, metavar="N")
    parser.add_argument("--ffmpeg-threads", type=int, default=None, metavar="N")
    parser.add_argument("--max-dimension", type=int, default=1920, metavar="PX")
    parser.add_argument("--max-fps", type=float, default=30.0, metavar="FPS")
    parser.add_argument("--crf", type=int, default=22)
    parser.add_argument("--preset", default="slow")
    parser.add_argument("--audio-bitrate", default="128k")
    parser.add_argument("--x265-frame-threads", type=int, default=4)
    parser.add_argument("--skip-efficient", action="store_true")
    parser.add_argument("--min-savings-pct", type=float, default=0.0, metavar="PCT")
    parser.add_argument(
        "--remux-if-skip",
        action="store_true",
        help="Stream-copy to MP4 when re-encode is skipped or not worthwhile",
    )
    return parser


def collect_videos(plan, criteria: ScanCriteria) -> list[Path]:
    if plan.single_file:
        if not is_video_file(plan.input_path):
            print(f"ERROR: not a video file: {plan.input_path}", file=sys.stderr)
            sys.exit(1)
        probe = probe_video(plan.input_path) if scan_needs_probe(criteria) else None
        if not matches_criteria(plan.input_path, probe, criteria):
            return []
        return [plan.input_path]
    videos, _ = iter_matching_videos(plan.input_root, criteria)
    return videos


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    plan = resolve_io(args.input, args.output)
    criteria = build_scan_criteria_from_args(args)
    max_fps = args.max_fps if args.max_fps > 0 else None
    dry_run = not args.execute
    log = TsvLog(
        tool="videos-to-mp4.py",
        input_path=plan.input_path,
        output_path=plan.output_root or plan.output_path,
        dry_run=dry_run,
        log_path=run_log_path("videos-to-mp4", plan, args.log),
    )

    candidates = collect_videos(plan, criteria)

    if args.list_only:
        print(f"# filters: {criteria_summary(criteria)}", file=sys.stderr)
        for path in candidates:
            try:
                size_label = format_bytes(path.stat().st_size)
            except OSError:
                size_label = "?"
            probe = probe_video(path)
            info = probe_summary(probe, args.max_dimension, max_fps=max_fps)
            line = f"{path}\t{size_label}"
            if info:
                line = f"{line}\t{info}"
            print(line)
        print(f"# {len(candidates)} file(s)", file=sys.stderr)
        return 0

    if not candidates:
        print("No matching video files found.")
        return 0

    if plan.mirror and plan.output_root and not dry_run:
        plan.output_root.mkdir(parents=True, exist_ok=True)

    jobs = 1 if plan.single_file else max(1, args.jobs)
    ffmpeg_threads = args.ffmpeg_threads
    if plan.single_file and ffmpeg_threads is None:
        env_val = os.environ.get("COMPRESS_FFMPEG_THREADS")
        if env_val:
            try:
                ffmpeg_threads = int(env_val)
            except ValueError:
                pass

    ff_threads, frame_threads = resolve_thread_budget(
        jobs,
        ffmpeg_threads=ffmpeg_threads,
        x265_frame_threads=args.x265_frame_threads,
    )
    print_thread_budget(jobs, ff_threads, frame_threads)

    encode_kw = {
        "max_dimension": args.max_dimension,
        "max_fps": max_fps,
        "crf": args.crf,
        "preset": args.preset,
        "audio_bitrate": args.audio_bitrate,
        "ffmpeg_threads": ff_threads,
        "x265_frame_threads": frame_threads,
        "dry_run": dry_run,
        "force": args.force,
        "skip_efficient": args.skip_efficient,
        "min_savings_pct": args.min_savings_pct,
        "reencode": False,
        "output_suffix": CANONICAL_VIDEO_EXT,
        "remux_if_skip": args.remux_if_skip,
        "in_place": plan.in_place,
    }

    def run_one(path: Path) -> None:
        result = convert_one(
            path,
            plan.input_root,
            plan.output_root,
            **encode_kw,
        )
        log.write(LogEntry(
            operation=OPERATION,
            status=result_log_status(result),
            source=result.source,
            dest=result.output,
            action=result_action(result),
            message=result.message,
            bytes_in=result.orig_bytes or None,
            bytes_out=result.out_bytes or None,
        ))

    if jobs == 1:
        for path in candidates:
            run_one(path)
    else:
        with ProcessPoolExecutor(max_workers=jobs) as pool:
            futures = [pool.submit(run_one, path) for path in candidates]
            for future in as_completed(futures):
                future.result()

    return log.close()


if __name__ == "__main__":
    sys.exit(main())
