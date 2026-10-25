"""запускает фоновые процессы через Run в PyCharm или python -m app.worker"""

import argparse
import asyncio
import logging
import signal
import sys
from pathlib import Path

from sqlalchemy.exc import SQLAlchemyError

if __name__ == "__main__" and not __package__:
    # при запуске файла напрямую пакет app ищется от папки backend
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.infrastructure.database.worker_lock import worker_lock
from app.schemas.worker import WorkerSettings
from app.services.worker import BackgroundWorker

logger = logging.getLogger(__name__)


async def run_worker(settings, *, once=False):
    """принимает сигналы завершения на Windows и Linux, ожидает сохранения текущих операций"""
    worker = BackgroundWorker(settings=settings)
    loop = asyncio.get_running_loop()
    previous = {}

    def stop(signum, frame):
        logger.info("Stopping worker after current operations")
        loop.call_soon_threadsafe(worker.stop)

    for name in (signal.SIGINT, signal.SIGTERM):
        previous[name] = signal.signal(name, stop)
    try:
        return await worker.run(once=once)
    finally:
        for name, handler in previous.items():
            signal.signal(name, handler)


def main():
    """читает необязательный JSON с настройками и удерживает блокировку на время работы"""
    parser = argparse.ArgumentParser(description="News background worker")
    parser.add_argument("--once", action="store_true", help="run one cycle and exit")
    parser.add_argument("--config", type=Path, help="path to WorkerSettings JSON")
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s"
    )
    try:
        settings = (
            WorkerSettings.model_validate_json(
                args.config.read_text(encoding="utf-8-sig")
            )
            if args.config
            else WorkerSettings()
        )
        with worker_lock():
            success = asyncio.run(run_worker(settings, once=args.once))
            return 0 if success else 1
    except (OSError, ValueError, RuntimeError, SQLAlchemyError) as error:
        logger.error("Worker did not start or stopped: %s", type(error).__name__)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
