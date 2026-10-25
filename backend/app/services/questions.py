"""готовит уточняющие ответы без открытой транзакции во время обращения к модели"""

import asyncio
import logging

from sqlalchemy.exc import SQLAlchemyError

from app.infrastructure.database.uow import UnitOfWork
from app.services.ai_agents.analysis import AnalysisAgent
from app.services.insights import InsightService

logger = logging.getLogger(__name__)


class QuestionService:
    """паттерн Service Layer: проверяет доступ, собирает историю и сохраняет проверенный ответ"""

    def __init__(self, *, insights=None, agent=None, uow_factory=UnitOfWork):
        """принимает сервис разборов, агента и фабрику транзакций"""
        self.insights = (
            insights
            if insights is not None
            else InsightService(uow_factory=uow_factory)
        )
        self.agent = (
            agent if agent is not None else AnalysisAgent(insights=self.insights)
        )
        self._uow = uow_factory

    def reserve(self, user_id):
        """не позволяет одному пользователю одновременно запустить несколько дорогих уточнений"""
        with self._uow() as db:
            db.runtime.reserve_question(user_id)
            db.commit()

    def release(self, user_id):
        """освобождает слот после ответа, ошибки или отмены запроса"""
        with self._uow() as db:
            db.runtime.save("question:" + str(user_id), {"status": "finished"})
            db.commit()

    async def ask(self, user_id, analysis_id, conversation_id, question):
        """проверяет исходный анализ и сохраняет ответ только при сохранённом доступе к компании"""
        question = question.strip()
        if not question or len(question) > 1000:
            raise ValueError("Question length must be between 1 and 1000")
        analysis = await asyncio.to_thread(
            self.insights.get_analysis, user_id, analysis_id
        )
        history = await asyncio.to_thread(
            self.insights.get_history, user_id, analysis_id, conversation_id, limit=5
        )
        await asyncio.to_thread(self.reserve, user_id)
        try:
            try:
                answer, sources = await asyncio.wait_for(
                    self.agent.answer(analysis, history, question), timeout=250
                )
            except ValueError:
                raise RuntimeError("Model answer could not be verified") from None
            return await asyncio.to_thread(
                self.insights.save_answer,
                user_id,
                analysis_id,
                conversation_id,
                question=question,
                answer=answer,
                sources=sources,
            )
        finally:
            try:
                await asyncio.to_thread(self.release, user_id)
            except (SQLAlchemyError, OSError) as error:
                # при сбое БД слот истечёт сам, сохранённый ответ или исходная ошибка остаются прежними
                logger.error("Question slot release failed: %s", type(error).__name__)
