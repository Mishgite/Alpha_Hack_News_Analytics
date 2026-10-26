"""хранит последние 20 ошибок разметки с блокировкой записи на Windows и Linux"""

import json
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path

from filelock import FileLock

from app.services.tag_catalog import APP_ROOT, load_catalog

from ._common import object_input, validate_tags

DEFAULT_PATH = Path(os.environ.get("BAD_NEWS_PATH", str(APP_ROOT / "bad_news.json")))


@contextmanager
def _locked(path):
    """не допускает одновременную запись файла несколькими процессами"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with FileLock(str(path.with_suffix(path.suffix + ".lock")), timeout=10):
        yield


def _read(path):
    if not path.exists():
        return []
    raw = path.read_text(encoding="utf-8")
    data = json.loads(raw) if raw.strip() else []
    if not isinstance(data, list) or len(data) > 20:
        raise ValueError("bad_news must be a JSON list with at most 20 records")
    for row in data:
        if not isinstance(row, dict) or set(row) != {"title", "text", "tags"}:
            raise ValueError("Invalid bad_news record")
        object_input(
            {k: row[k] for k in ("title", "text")}, {"title": 1000, "text": 30000}
        )
        if (
            not isinstance(row["tags"], list)
            or len(row["tags"]) > 50
            or any(not isinstance(t, str) for t in row["tags"])
        ):
            raise ValueError("Invalid bad_news tags")
    return data


def load_bad_news(*, path=None):
    """читает примеры под блокировкой, повреждённый JSON вызывает ошибку"""
    target = Path(path or DEFAULT_PATH)
    with _locked(target):
        return _read(target)


def add_bad_news(title, text, tags, *, path=None, catalog_path=None):
    """добавляет ошибочную разметку и оставляет последние 20 записей"""
    record = object_input(
        {"title": title, "text": text}, {"title": 1000, "text": 30000}
    )
    record["tags"] = validate_tags(tags, load_catalog(catalog_path))
    target = Path(path or DEFAULT_PATH)
    with _locked(target):
        records = (_read(target) + [record])[-20:]
        fd, temporary = tempfile.mkstemp(prefix=target.name + ".", dir=target.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as file:
                json.dump(records, file, ensure_ascii=False, indent=2)
                file.write("\n")
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary, target)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    return records
