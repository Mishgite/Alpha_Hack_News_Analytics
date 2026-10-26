"""подготавливает окружение контейнера и запускает выбранный процесс"""

import json
import os
import sys
import time
from datetime import UTC, datetime
from urllib.parse import urlsplit
from urllib.request import urlopen

from sqlalchemy import URL, text


def configure_environment():
    """собирает строку подключения без потери специальных символов в пароле"""
    os.environ["DATABASE_URL"] = URL.create(
        "postgresql+psycopg",
        username=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"],
        host="database",
        port=5432,
        database=os.environ["POSTGRES_DB"],
    ).render_as_string(hide_password=False)
    origin = os.environ["FRONTEND_ORIGIN"].rstrip("/")
    parsed = urlsplit(origin)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.path
        or parsed.query
        or parsed.fragment
        or parsed.username
        or parsed.password
    ):
        raise ValueError("FRONTEND_ORIGIN must be an origin without a path")
    os.environ["API_CORS_ORIGINS"] = json.dumps([origin])


def check_ready():
    """проверяет подключение и отметку об успешной подготовке данных"""
    from app.infrastructure.database.session import get_engine
    from app.services.runtime import RuntimeService

    with get_engine().connect() as connection:
        connection.execute(text("SELECT 1"))
    state = RuntimeService().get("server_bootstrap_v1")
    if not state or state["value"].get("status") != "ready":
        raise RuntimeError("Bootstrap has not completed")


def healthcheck(command):
    """проверяет готовность API или свежесть отметки работающего воркера"""
    check_ready()
    if command == "health-api":
        with urlopen("http://127.0.0.1:8000/health", timeout=5) as response:
            if response.status != 200:
                raise RuntimeError("API is unavailable")
    else:
        from app.services.runtime import RuntimeService

        state = RuntimeService().get("worker")
        if (
            not state
            or state["value"].get("status") != "running"
            or (datetime.now(UTC) - state["updated_at"]).total_seconds() > 60
        ):
            raise RuntimeError("Worker heartbeat is missing")


def main():
    """ожидает базу после перезапуска сервера и передаёт сигналы основному процессу"""
    command, *arguments = sys.argv[1:]
    try:
        configure_environment()
        if command.startswith("health-"):
            healthcheck(command)
            return 0
        if command in {"api", "worker"}:
            for attempt in range(60):
                try:
                    check_ready()
                    break
                except Exception:
                    if attempt == 59:
                        raise
                    time.sleep(2)
        commands = {
            "bootstrap": ["-m", "app.bootstrap"],
            "evaluate": ["-m", "app.evaluate", "--output", "/workspace/runtime/evaluation"],
            "monitor": ["-m", "app.monitor"],
            "refresh-context": ["-m", "app.refresh_company_context"],
            "api": [
                "-m",
                "uvicorn",
                "app.api.application:app",
                "--host",
                "0.0.0.0",
                "--port",
                "8000",
            ],
            "worker": ["-m", "app.worker", "--config", "/workspace/worker.json"],
            "parser": ["-m", "app.newspaper_parser.newspaper_parser", "--keep-files"],
        }
        os.execv(sys.executable, [sys.executable, *commands[command], *arguments])
    except Exception as error:  # noqa: BLE001
        print(f"Container {command} failed: {type(error).__name__}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
