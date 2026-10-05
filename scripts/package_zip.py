"""Build a data-safe source ZIP for replacing the project in GitHub."""
from __future__ import annotations

import os
import zipfile
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
OUTPUT_ZIP = ROOT_DIR / "mas_v2_release.zip"

EXCLUDED_ROOT_DIRS = {
    ".git",
    ".venv",
    "venv",
    "uploads",
    "storage",
    "data",
}

EXCLUDED_DIR_NAMES = {
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    ".nox",
    ".tox",
    ".cache",
    ".aws",
    ".ssh",
    ".arena",
    "secrets",
    ".next",
    ".nuxt",
    ".output",
    ".parcel-cache",
    ".svelte-kit",
    ".turbo",
    ".vite",
    "build",
    "coverage",
    "target",
}

EXCLUDED_EXTENSIONS = {
    ".pyc",
    ".pyo",
    ".db",
    ".db-wal",
    ".db-shm",
    ".sqlite",
    ".sqlite3",
    ".sqlite-wal",
    ".sqlite-shm",
    ".log",
    ".pem",
    ".p12",
    ".pfx",
    ".key",
    ".bak",
    ".tmp",
}

EXCLUDED_FILES = {
    "mas_v2_release.zip",
    ".DS_Store",
    ".netrc",
    ".coverage",
    "coverage.xml",
    "Thumbs.db",
    "id_rsa",
    "id_ed25519",
    "BUG_AUDIT.md",
    "AUDIT_REPORT_2026-10-05.md",
}


def is_excluded_directory(relative_path: Path) -> bool:
    if not relative_path.parts:
        return False
    if relative_path.parts[0] in EXCLUDED_ROOT_DIRS:
        return True
    return any(part in EXCLUDED_DIR_NAMES for part in relative_path.parts)


def should_include(relative_path: Path) -> bool:
    if is_excluded_directory(relative_path.parent):
        return False
    if relative_path.name in EXCLUDED_FILES:
        return False
    if relative_path.name == ".env" or (
        relative_path.name.startswith(".env.") and relative_path.name != ".env.example"
    ):
        return False
    return relative_path.suffix.lower() not in EXCLUDED_EXTENSIONS


def create_release_zip() -> Path:
    print(f"Building data-safe project ZIP: {OUTPUT_ZIP}")
    file_count = 0

    with zipfile.ZipFile(OUTPUT_ZIP, "w", zipfile.ZIP_DEFLATED) as archive:
        for root, dirs, files in os.walk(ROOT_DIR, followlinks=False):
            root_path = Path(root)
            relative_root = root_path.relative_to(ROOT_DIR)
            dirs[:] = sorted(
                directory
                for directory in dirs
                if not is_excluded_directory(relative_root / directory)
            )
            for filename in sorted(files):
                path = root_path / filename
                if path.is_symlink():
                    continue
                relative = path.relative_to(ROOT_DIR)
                if not should_include(relative):
                    continue
                archive.write(path, arcname=relative.as_posix())
                file_count += 1

    size_mb = OUTPUT_ZIP.stat().st_size / (1024 * 1024)
    print(f"Created {OUTPUT_ZIP.name}: {file_count} files, {size_mb:.2f} MiB")
    return OUTPUT_ZIP


if __name__ == "__main__":
    create_release_zip()
