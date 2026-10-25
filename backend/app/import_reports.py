"""загружает подготовленные PDF-фрагменты в PostgreSQL через Run в PyCharm"""

import argparse
import sys
from pathlib import Path

if __name__ == "__main__" and not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.reports import ReportService


def main():
    """принимает каталог результатов распознавания и печатает итог загрузки"""
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--directory",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "data/reports_processed",
    )
    args = parser.parse_args()
    if not args.directory.is_dir():
        parser.error("Prepared reports directory not found")
    result = ReportService().import_directory(args.directory)
    print(result)
    return int(bool(result["errors"]))


if __name__ == "__main__":
    raise SystemExit(main())
