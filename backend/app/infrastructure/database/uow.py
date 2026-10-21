"""одна транзакция для связанных записей через несколько репозиториев"""

from sqlalchemy import Engine

from app.infrastructure.database.repositories.analytics import (
    AnalysisRepository,
    ReportRepository,
)
from app.infrastructure.database.repositories.feed import FeedRepository
from app.infrastructure.database.repositories.feedback import FeedbackRepository
from app.infrastructure.database.repositories.news import NewsRepository
from app.infrastructure.database.repositories.profiles import (
    CompanyRepository,
    UserRepository,
)
from app.infrastructure.database.session import get_engine, make_session_factory


class UnitOfWork:
    """паттерн Unit of Work: объединяет операции репозиториев в одну транзакцию

    для сохранения изменений нужен явный commit
    при выходе из with откатывает несохранённые изменения и закрывает сессию
    """

    def __init__(self, engine: Engine | None = None):
        """принимает движок БД или использует настройки подключения при входе в with"""
        self.engine = engine

    def __enter__(self):
        """создаёт сессию и репозитории, использующие её, затем возвращает UnitOfWork"""
        engine = self.engine if self.engine is not None else get_engine()
        self._session = make_session_factory(engine)()
        self.companies = CompanyRepository(self._session)
        self.users = UserRepository(self._session)
        self.news = NewsRepository(self._session)
        self.feeds = FeedRepository(self._session)
        self.feedback = FeedbackRepository(self._session)
        self.analyses = AnalysisRepository(self._session)
        self.reports = ReportRepository(self._session)
        return self

    def commit(self):
        """фиксирует изменения всех репозиториев в текущей транзакции"""
        self._session.commit()

    def rollback(self):
        """отменяет незавершённые изменения общей сессии"""
        self._session.rollback()

    def __exit__(self, exc_type, exc_value, traceback):
        """откатывает оставшуюся транзакцию и закрывает сессию, не подавляя исключение"""
        try:
            self._session.rollback()
        finally:
            self._session.close()
