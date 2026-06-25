"""Bootstrap archive-tools .venv for VCF scripts when deps are missing."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def _in_venv(venv_dir: Path) -> bool:
    try:
        return Path(sys.prefix).resolve() == venv_dir.resolve()
    except OSError:
        return False


def _install_requirements(venv_python: Path, requirements: Path) -> None:
    subprocess.run(
        [str(venv_python), "-m", "pip", "install", "--quiet", "--upgrade", "pip"],
        check=True,
    )
    subprocess.run(
        [str(venv_python), "-m", "pip", "install", "--quiet", "-r", str(requirements)],
        check=True,
    )


def bootstrap_vcf_venv() -> None:
    """Use archive-tools .venv when phonenumbers/vobject are not importable."""
    try:
        import phonenumbers  # noqa: F401
        import vobject  # noqa: F401
        return
    except ImportError:
        pass

    repo_root = Path(__file__).resolve().parents[2]
    venv_dir = repo_root / ".venv"
    venv_python = venv_dir / "bin" / "python3"
    requirements = repo_root / "requirements-vcf.txt"

    if not venv_dir.is_dir():
        print(f"Setting up Python environment at: {venv_dir}")
        subprocess.run([sys.executable, "-m", "venv", str(venv_dir)], check=True)
        _install_requirements(venv_python, requirements)

    if not venv_python.is_file():
        print(f"ERROR: venv Python not found: {venv_python}", file=sys.stderr)
        sys.exit(1)

    if not _in_venv(venv_dir):
        os.execv(str(venv_python), [str(venv_python), *sys.argv])

    try:
        import phonenumbers  # noqa: F401
        import vobject  # noqa: F401
    except ImportError:
        print(f"Installing Python dependencies from: {requirements}")
        _install_requirements(venv_python, requirements)
