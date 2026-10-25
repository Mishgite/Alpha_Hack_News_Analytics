"""загружает общий справочник тем и географии для БД и разметчиков"""

import json
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1]


def load_catalog(path=None) -> dict[str, dict[str, str]]:
    """читает справочник и проверяет уникальность кодов во всех трёх группах"""
    data = json.loads(
        Path(path or APP_ROOT / "tags.json").read_text(encoding="utf-8-sig")
    )
    result = {}
    codes = []
    for group in ("city", "region", "business"):
        values = data.get(group)
        if not isinstance(values, dict) or not values:
            raise ValueError(f"Invalid catalogue group: {group}")
        if any(
            not isinstance(k, str)
            or not k.strip()
            or not isinstance(v, str)
            or not v.strip()
            for k, v in values.items()
        ):
            raise ValueError("Catalogue names and codes must be non-empty strings")
        codes.extend(values.values())
        result[group] = values
    if len(codes) != len(set(codes)):
        raise ValueError("Duplicate tag codes")
    return result
