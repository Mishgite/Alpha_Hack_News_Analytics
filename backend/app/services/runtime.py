"""учёт фоновых процессов и ограничение обращений к модели"""

from app.infrastructure.database.uow import UnitOfWork


class RuntimeService:
    """открывает короткие транзакции для технических состояний"""

    def __init__(self, *, uow_factory=UnitOfWork):
        """принимает фабрику транзакций без подключения при создании сервиса"""
        self._uow = uow_factory

    def get(self, key):
        """читает состояние по ключу"""
        with self._uow() as db:
            return db.runtime.get(key)

    def save(self, key, value):
        """сохраняет состояние одной транзакцией"""
        with self._uow() as db:
            db.runtime.save(key, value)
            db.commit()

    def reserve_call(self, task, model, daily_limit):
        """учитывает попытку до сетевого запроса, включая неудачные вызовы"""
        with self._uow() as db:
            result = db.runtime.reserve_call(task, model, daily_limit)
            db.commit()
            return result

    def finish_call(self, call_id, status, usage):
        """дополняет зарезервированный вызов результатом провайдера"""
        with self._uow() as db:
            db.runtime.finish_call(call_id, status, usage)
            db.commit()
