"""сохраняет расходы LLM и состояния фоновых процессов"""

from datetime import UTC, datetime

from sqlalchemy import func, select, text, update
from sqlalchemy.dialects.postgresql import insert

from app.infrastructure.database.models.analytics import LLMUsage
from app.infrastructure.database.models.runtime import ProcessingState


class RuntimeRepository:
    """паттерн Repository: работает с учётом вызовов и состояниями в сессии UnitOfWork"""

    def __init__(self, session):
        """принимает сессию текущей транзакции"""
        self._session = session

    def get(self, key):
        """возвращает сохранённое состояние или None"""
        row = self._session.get(ProcessingState, key)
        return {"value": dict(row.value), "updated_at": row.updated_at} if row else None

    def save(self, key, value):
        """заменяет состояние и время последнего обновления"""
        statement = insert(ProcessingState).values(key=key, value=value)
        self._session.execute(
            statement.on_conflict_do_update(
                index_elements=[ProcessingState.key],
                set_={"value": value, "updated_at": func.now()},
            )
        )

    def reserve_market_refresh(self):
        """разрешает один запрос котировок в минуту для всех пользователей и воркера"""
        self._session.execute(text("SELECT pg_advisory_xact_lock(684720264)"))
        state = self.get("market_refresh")
        if state and (datetime.now(UTC) - state["updated_at"]).total_seconds() < 60:
            return False
        self.save("market_refresh", {"status": "requested"})
        return True

    def reserve_call(self, task, model, daily_limit):
        """проверяет общий лимит запросов этой БД и резервирует вызов до обращения к модели"""
        self._session.execute(text("SELECT pg_advisory_xact_lock(684720262)"))
        start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        count = self._session.scalar(
            select(func.count())
            .select_from(LLMUsage)
            .where(LLMUsage.created_at >= start)
        )
        if count >= daily_limit:
            raise RuntimeError("Local daily LLM request limit reached")
        row = LLMUsage(task_type=task, model_id=model, status="reserved")
        self._session.add(row)
        self._session.flush()
        return row.id

    def finish_call(self, call_id, status, usage):
        """сохраняет число токенов, стоимость без подтверждённой валюты не записывает"""
        values = {"status": status}
        for target, source in (
            ("input_tokens", "prompt_tokens"),
            ("output_tokens", "completion_tokens"),
        ):
            value = usage.get(source)
            if isinstance(value, int) and value >= 0:
                values[target] = value
        self._session.execute(
            update(LLMUsage).where(LLMUsage.id == call_id).values(**values)
        )

    def reserve_question(self, user_id):
        """защищает пользователя от одновременных запросов уточнения между процессами API"""
        self._session.execute(text("SELECT pg_advisory_xact_lock(684720263)"))
        key = "question:" + str(user_id)
        state = self.get(key)
        if state:
            age = (datetime.now(UTC) - state["updated_at"]).total_seconds()
            if age < 10 or (state["value"].get("status") == "running" and age < 300):
                raise ValueError("A question is already running or was just submitted")
        self.save(key, {"status": "running"})
