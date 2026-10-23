"""Persistent FIFO of the last 20 incorrect tag assignments (Linux backend)."""
import fcntl
import json
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path

from ._common import APP_ROOT, load_catalog, object_input, validate_tags

DEFAULT_PATH = APP_ROOT / 'bad_news.json'


@contextmanager
def _locked(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_suffix(path.suffix + '.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def _read(path):
    if not path.exists():
        return []
    raw = path.read_text(encoding='utf-8')
    data = json.loads(raw) if raw.strip() else []
    if not isinstance(data, list) or len(data) > 20:
        raise ValueError('bad_news must be a JSON list with at most 20 records')
    for row in data:
        if not isinstance(row, dict) or set(row) != {'title', 'text', 'tags'}:
            raise ValueError('Invalid bad_news record')
        object_input({k: row[k] for k in ('title', 'text')}, {'title': 1000, 'text': 30000})
        if not isinstance(row['tags'], list) or len(row['tags']) > 50 or any(not isinstance(t, str) for t in row['tags']):
            raise ValueError('Invalid bad_news tags')
    return data


def load_bad_news(*, path=None):
    """Return a snapshot; invalid JSON is reported, never silently discarded."""
    target = Path(path or DEFAULT_PATH)
    with _locked(target):
        return _read(target)


def add_bad_news(title, text, tags, *, path=None, catalog_path=None):
    """Append wrong tags, evict oldest at 21; return the current JSON-compatible list."""
    record = object_input({'title': title, 'text': text}, {'title': 1000, 'text': 30000})
    record['tags'] = validate_tags(tags, load_catalog(catalog_path))
    target = Path(path or DEFAULT_PATH)
    with _locked(target):
        records = (_read(target) + [record])[-20:]
        fd, temporary = tempfile.mkstemp(prefix=target.name + '.', dir=target.parent)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as file:
                json.dump(records, file, ensure_ascii=False, indent=2)
                file.write('\n')
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary, target)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    return records
