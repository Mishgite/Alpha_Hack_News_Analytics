"""не допускает два процесса с одним и тем же циклом разметки новостей"""

import logging
from contextlib import contextmanager

from sqlalchemy import text

from .session import get_engine

LOCK_KEY = 684720261
logger = logging.getLogger(__name__)


@contextmanager
def worker_lock():
    """удерживает блокировку PostgreSQL на отдельном соединении до остановки процесса"""
    # session advisory lock не требует открытой транзакции и освобождается при разрыве соединения
    with (
        get_engine()
        .connect()
        .execution_options(isolation_level="AUTOCOMMIT") as connection
    ):
        acquired = connection.scalar(
            text("SELECT pg_try_advisory_lock(:key)"), {"key": LOCK_KEY}
        )
        if not acquired:
            logger.error("A worker is already running for this database")
            raise RuntimeError("A worker is already running for this database")
        try:
            yield
        finally:
            # соединение не возвращается в пул с оставшейся блокировкой, даже если сервер недоступен
            try:
                connection.execute(
                    text("SELECT pg_advisory_unlock(:key)"), {"key": LOCK_KEY}
                )
            finally:
                connection.invalidate()
