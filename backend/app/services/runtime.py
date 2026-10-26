"""учёт фоновых процессов и ограничение обращений к модели"""

from datetime import UTC, datetime

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

    def record_operation(self, name, seconds, success):
        """записывает длительность и результат завершённой фоновой операции"""
        with self._uow() as db:
            db.runtime.record_operation(name, seconds, success)
            db.commit()

    def finish_call(self, call_id, status, usage):
        """дополняет зарезервированный вызов результатом провайдера"""
        with self._uow() as db:
            db.runtime.finish_call(call_id, status, usage)
            db.commit()

    def generation_available(self):
        """проверяет известные ограничения до постановки задания, без запроса к провайдеру"""
        from app.services.ai_agents._common import settings

        limit = int(settings().get("LLM_DAILY_REQUEST_LIMIT", "30"))
        with self._uow() as db:
            if db.runtime.calls_today() >= limit:
                return False
            budget = db.runtime.get("llm_budget")
        if budget:
            value = budget["value"]
            reset = value.get("reset_at")
            try:
                reset_at = datetime.fromisoformat(reset) if reset else None
                expired = reset_at is not None and reset_at.astimezone(
                    UTC
                ) <= datetime.now(UTC)
            except (TypeError, ValueError):
                expired = False
            if not expired and value.get("remaining", float("inf")) <= value.get(
                "reserve", 0
            ):
                return False
        return True
