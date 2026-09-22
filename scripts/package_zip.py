"""اسکریپت ساخت بستهٔ زیپ نهایی پروژه جهت جایگزینی در گیت‌هاب."""

import os
import zipfile
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
OUTPUT_ZIP = ROOT_DIR / "mas_v2_release.zip"

EXCLUDED_ROOT_DIRS = {
    "uploads",
    "storage",
}

EXCLUDED_ANYWHERE_DIRS = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".vite",
}

EXCLUDED_EXTENSIONS = {
    ".pyc",
    ".pyo",
    ".db",
    ".sqlite3",
    ".db-wal",
    ".db-shm",
    ".log",
}

EXCLUDED_FILES = {
    "mas_v2_release.zip",
    ".DS_Store",
    "Thumbs.db",
}


def should_include(rel_path: Path) -> bool:
    if rel_path.parts[0] in EXCLUDED_ROOT_DIRS:
        return False

    for part in rel_path.parts:
        if part in EXCLUDED_ANYWHERE_DIRS:
            return False

    if rel_path.name in EXCLUDED_FILES:
        return False

    return rel_path.suffix not in EXCLUDED_EXTENSIONS


def create_release_zip():
    print(f"در حال ساخت بستهٔ زیپ در {OUTPUT_ZIP}...")
    file_count = 0

    with zipfile.ZipFile(OUTPUT_ZIP, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(ROOT_DIR):
            dirs[:] = [
                d
                for d in dirs
                if d not in EXCLUDED_ANYWHERE_DIRS
                and not (Path(root) == ROOT_DIR and d in EXCLUDED_ROOT_DIRS)
            ]

            for file in files:
                abs_path = Path(root) / file
                rel_path = abs_path.relative_to(ROOT_DIR)

                if should_include(rel_path):
                    zf.write(abs_path, arcname=str(rel_path))
                    file_count += 1

    size_mb = OUTPUT_ZIP.stat().st_size / (1024 * 1024)
    print(f"بسته با موفقیت ساخته شد: {file_count} فایل، حجم: {size_mb:.2f} مگابایت.")


if __name__ == "__main__":
    create_release_zip()
