"""печатает технические показатели и предупреждения без обращения к модели"""

import argparse
import json
import sys
from pathlib import Path

if __name__ == "__main__" and not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.quality import QualityService


def main():
    parser = argparse.ArgumentParser(description="Show processing metrics without LLM calls")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    report = QualityService().snapshot()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return int(args.check and bool(report["alerts"]))


if __name__ == "__main__":
    raise SystemExit(main())
