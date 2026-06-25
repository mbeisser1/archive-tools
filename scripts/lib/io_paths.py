"""Resolve -i / -o input and output paths for file or directory inputs."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class IoPlan:
    """Resolved input/output layout for a batch operation."""

    input_path: Path
    input_root: Path
    output_path: Path | None
    output_root: Path | None
    single_file: bool

    @property
    def in_place(self) -> bool:
        return self.output_root is None and self.output_path is None

    @property
    def mirror(self) -> bool:
        return self.output_root is not None


def resolve_io(input_path: Path, output_path: Path | None) -> IoPlan:
    input_path = input_path.resolve()
    if not input_path.exists():
        print(f"ERROR: input not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    if input_path.is_file():
        if output_path is None:
            return IoPlan(
                input_path=input_path,
                input_root=input_path.parent,
                output_path=None,
                output_root=None,
                single_file=True,
            )
        output_path = output_path.resolve()
        if output_path.is_dir():
            return IoPlan(
                input_path=input_path,
                input_root=input_path.parent,
                output_path=output_path / f"{input_path.stem}",
                output_root=output_path,
                single_file=True,
            )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        return IoPlan(
            input_path=input_path,
            input_root=input_path.parent,
            output_path=output_path,
            output_root=None,
            single_file=True,
        )

    if not input_path.is_dir():
        print(f"ERROR: input is not a file or directory: {input_path}", file=sys.stderr)
        sys.exit(1)

    if output_path is None:
        return IoPlan(
            input_path=input_path,
            input_root=input_path,
            output_path=None,
            output_root=None,
            single_file=False,
        )

    output_path = output_path.resolve()
    if output_path.is_file():
        print(
            "ERROR: when input is a directory, output must be a directory or omitted",
            file=sys.stderr,
        )
        sys.exit(1)
    return IoPlan(
        input_path=input_path,
        input_root=input_path,
        output_path=None,
        output_root=output_path,
        single_file=False,
    )


def relative_to_root(path: Path, root: Path) -> Path:
    try:
        return path.resolve().relative_to(root.resolve())
    except ValueError:
        return Path(path.name)


def dest_with_suffix(
    source: Path,
    plan: IoPlan,
    *,
    suffix: str,
    new_name: str | None = None,
) -> Path:
    """Map source to destination using IoPlan and a new extension or basename."""
    if plan.single_file:
        if plan.output_path is not None:
            if new_name:
                return plan.output_path.parent / new_name
            if suffix.startswith("."):
                return plan.output_path.with_suffix(suffix)
            return plan.output_path
        if new_name:
            return source.parent / new_name
        if suffix.startswith("."):
            return source.with_suffix(suffix)
        return source.parent / f"{source.stem}{suffix}"

    rel = relative_to_root(source, plan.input_root)
    if plan.mirror and plan.output_root is not None:
        base = new_name if new_name else f"{source.stem}{suffix}"
        return plan.output_root / rel.parent / base

    if new_name:
        return source.parent / new_name
    if suffix.startswith("."):
        return source.with_suffix(suffix)
    return source.parent / f"{source.stem}{suffix}"


def default_log_path(plan: IoPlan, explicit: Path | None) -> Path:
    if explicit is not None:
        return explicit.resolve()
    if plan.output_root is not None:
        return plan.output_root / "archive-tools.log"
    if plan.output_path is not None:
        return plan.output_path.parent / "archive-tools.log"
    if plan.input_path.is_file():
        return plan.input_path.parent / "archive-tools.log"
    return plan.input_root / "archive-tools.log"
