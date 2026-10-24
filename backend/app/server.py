"""запускает API через Run в PyCharm или python -m app.server"""

import sys
from pathlib import Path

if __name__ == "__main__" and not __package__:
    # при запуске файла напрямую пакет app ищется от папки backend
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import uvicorn

from app.api.application import app

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)
