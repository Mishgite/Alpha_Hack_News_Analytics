"""запускает фоновые операции через сервисы, независимо от обработки HTTP-запросов"""

import asyncio
import logging
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic
from uuid import uuid4

from sqlalchemy.exc import SQLAlchemyError

from app.parser.article import enrich_news_items
from app.parser.rss import fetch_rss_feed
from app.schemas.services import AnalysisVersions
from app.schemas.worker import WorkerSettings
from app.services.ai_agents._common import settings, validate_configuration
from app.services.ai_agents.analysis import AnalysisAgent
from app.services.insights import InsightService
from app.services.market import MarketService
from app.services.news_pipeline import NewsPipeline
from app.services.profile_pipeline import TAGGING_VERSION, ProfilePipeline
from app.services.reports import ReportService
from app.services.runtime import RuntimeService

logger = logging.getLogger(__name__)


class BackgroundWorker:
    """выполняет загрузку, разметку и AI-задания в отдельных асинхронных циклах"""

    def __init__(
        self,
        *,
        settings=None,
        news_pipeline=None,
        insights=None,
        agent=None,
        profiles=None,
        reports=None,
        market=None,
        runtime=None,
        quality=None,
        fetcher=fetch_rss_feed,
        enricher=enrich_news_items,
    ):
        """внедрение зависимостей: принимает готовые сервисы и заменяемые внешние обработчики"""
        self.settings = settings if settings is not None else WorkerSettings()
        self.news = news_pipeline if news_pipeline is not None else NewsPipeline()
        self.insights = insights if insights is not None else InsightService()
        self.reports = reports if reports is not None else ReportService()
        self.agent = (
            agent
            if agent is not None
            else AnalysisAgent(insights=self.insights, reports=self.reports)
        )
        self.profiles = profiles if profiles is not None else ProfilePipeline()
        self.market = market if market is not None else MarketService()
        self.runtime = runtime if runtime is not None else RuntimeService()
        from app.services.quality import QualityService

        self.quality = (
            quality
            if quality is not None
            else QualityService(uow_factory=self.runtime._uow)
        )
        self.analysis_enabled = True
        self.tagging_enabled = True
        self.profiles_enabled = True
        self.fetcher = fetcher
        self.enricher = enricher
        self.worker_id = f"worker-{uuid4()}"
        self.stop_event = asyncio.Event()

    def stop(self):
        """останавливает новые итерации, текущие операции завершаются перед выходом"""
        self.stop_event.set()

    async def fetch_source(self, source):
        """загружает ограниченную порцию RSS и сохраняет её через сервис новостей"""
        items = await asyncio.to_thread(
            self.fetcher,
            str(source.url),
            source=source.code,
            timeout=20,
            fetch_full_text=False,
        )
        if source.categories:
            allowed = {name.casefold() for name in source.categories}
            items = [
                item
                for item in items
                if allowed.intersection(
                    str(tag.get("term", "")).casefold()
                    for tag in (item.raw or {}).get("tags", [])
                    if isinstance(tag, dict)
                )
            ]
        items = items[: source.limit]
        if source.full_text:
            items = await asyncio.to_thread(
                self.enricher, items, timeout=8, max_workers=2
            )
        result = await asyncio.to_thread(
            self.news.save_parsed_news, items, source_kind="rss"
        )
        logger.info(
            "RSS source=%s saved=%s errors=%s",
            source.code,
            len(result.news_ids),
            len(result.errors),
        )
        return result

    async def tag_news(self):
        """передаёт разметчику небольшую порцию pending-новостей, готовые повторно не размечает"""
        # синхронные сервисы работают в потоке, поэтому запрос LLM не останавливает остальные циклы
        result = await asyncio.to_thread(
            self.news.tag_pending_news, limit=self.settings.tagging_batch
        )
        logger.info(
            "Tagging saved=%s errors=%s", len(result.news_ids), len(result.errors)
        )
        return result

    async def process_analysis(self):
        """забирает одно задание, получает разбор от агента и сохраняет результат либо код ошибки"""
        if not self.analysis_enabled:
            return None
        versions = (
            await self.agent.get_versions()
            if hasattr(self.agent, "get_versions")
            else AnalysisVersions.model_validate(self.agent.versions)
        )
        job = await asyncio.to_thread(
            self.insights.claim_job,
            self.worker_id,
            lease_seconds=self.settings.analysis_timeout + 60,
            max_attempts=3,
        )
        if job is None:
            return None
        try:
            work = await asyncio.to_thread(
                self.insights.prepare_job,
                job.id,
                self.worker_id,
                job.attempts,
                versions=versions,
            )
            cached = await asyncio.to_thread(self.insights.get_cached_result, work)
            if cached is not None:
                result = cached.result
                status, trace = cached.status, cached.trace + [{"step": "cache_hit"}]
            else:
                # оставляем время на сохранение до истечения права на обработку задания
                remaining = (job.lease_until - datetime.now(UTC)).total_seconds() - 10
                if remaining <= 0:
                    raise TimeoutError("Job lease is about to expire")
                result = await asyncio.wait_for(
                    self.agent.analyze(work),
                    timeout=min(self.settings.analysis_timeout, remaining),
                )
                from app.schemas.agent import AnalysisOutput

                if isinstance(result, AnalysisOutput):
                    status, trace = result.status, result.trace
                    result = result.result
                else:
                    status, trace = "ready", []
            saved = await asyncio.to_thread(
                self.insights.complete_job, work, result, status=status, trace=trace
            )
            logger.info("Analysis job=%s ready=%s", job.id, saved.id)
            return saved
        except Exception as error:
            # исходный текст исключения может содержать ответ провайдера или данные подключения
            code = (
                "analysis_timeout"
                if isinstance(error, TimeoutError)
                else type(error).__name__
            )
            logger.error("Analysis job=%s error=%s", job.id, code)
            try:
                await asyncio.to_thread(
                    self.insights.fail_job,
                    job.id,
                    self.worker_id,
                    job.attempts,
                    error_code=code,
                )
            except Exception as save_error:  # noqa: BLE001
                # истёкшее задание сервис не даст перезаписать, следующая попытка заберёт его после lease
                logger.error(
                    "Analysis failure not saved: job=%s error=%s",
                    job.id,
                    type(save_error).__name__,
                )
            raise

    async def process_profiles(self):
        """размечает только изменённые компании пользователей, ошибки повторяет не чаще раза в час"""
        config = settings()
        validate_configuration(config, "LLM_MODEL_CONTEXT")
        version = TAGGING_VERSION + config["LLM_MODEL_CONTEXT"]
        companies = await asyncio.to_thread(
            self.profiles.profiles.pending_tagging, version, self.settings.profile_batch
        )
        errors = []
        for company in companies:
            try:
                await asyncio.to_thread(
                    self.profiles.prepare_company, company.id, version
                )
            except Exception as error:  # noqa: BLE001
                # ошибка одного профиля не должна останавливать остальные циклы воркера
                errors.append(type(error).__name__)
                logger.error("Company tagging failed: %s", type(error).__name__)
        return {"processed": len(companies) - len(errors), "errors": errors}

    async def import_reports(self):
        """загружает новые версии подготовленных отчётов при запуске воркера"""
        directory = (
            Path(self.settings.reports_directory)
            if self.settings.reports_directory
            else Path(__file__).resolve().parents[2] / "data/reports_processed"
        )
        if directory.is_dir():
            result = await asyncio.to_thread(self.reports.import_directory, directory)
            logger.info(
                "Reports imported=%s skipped=%s errors=%s",
                result["imported"],
                result["skipped"],
                len(result["errors"]),
            )
            return result
        else:
            logger.info(
                "No report directory; using documents already stored in database"
            )

    async def refresh_market(self):
        """обновляет котировки, при ошибке оставляет предыдущий снимок с признаком устаревания"""
        try:
            count = await asyncio.to_thread(self.market.refresh)
            logger.info("Market quotes saved=%s", count)
        except Exception:
            await asyncio.to_thread(self.runtime.save, "market", {"status": "failed"})
            raise

    async def heartbeat(self):
        """сообщает API, что worker жив и может обрабатывать задания"""
        await asyncio.to_thread(
            self.runtime.save,
            "worker",
            {
                "worker_id": self.worker_id,
                "analysis_enabled": self.analysis_enabled,
                "status": "running",
            },
        )

    async def _call(self, name, operation, *args):
        """изолирует ошибку одной операции, чтобы остальные фоновые задачи продолжили работу"""
        started, success, idle = monotonic(), False, False
        try:
            result = await operation(*args)
            errors = (
                result.get("errors", [])
                if isinstance(result, dict)
                else getattr(result, "errors", [])
            )
            success = not bool(errors)
            idle = isinstance(result, dict) and result.get("skipped") is True
            idle = (
                idle
                or (name == "analysis" and result is None)
                or (
                    name == "profiles"
                    and isinstance(result, dict)
                    and result.get("processed") == 0
                    and not errors
                )
            )
            return success
        except Exception as error:  # noqa: BLE001
            logger.error("Worker task=%s error=%s", name, type(error).__name__)
            return False
        finally:
            if name not in {"heartbeat", "monitoring"} and not idle:
                try:
                    await asyncio.to_thread(
                        self.runtime.record_operation,
                        name,
                        monotonic() - started,
                        success,
                    )
                except Exception:  # noqa: BLE001
                    logger.error("Worker operation metrics could not be saved")

    async def monitor(self):
        """обновляет агрегаты и пишет предупреждение только при изменении набора проблем"""
        previous = await asyncio.to_thread(self.runtime.get, "monitoring")
        result = await asyncio.to_thread(self.quality.snapshot, persist=True)
        if result["alerts"] and result["alerts"] != (previous or {}).get(
            "value", {}
        ).get("alerts"):
            logger.warning("Monitoring alerts: %s", ", ".join(result["alerts"]))
        return result

    async def check_quality(self):
        """проверяет раз в сутки и после изменения кода, повторяет сбой на следующем часовом проходе"""
        from app.evaluate import source_version

        previous = await asyncio.to_thread(self.runtime.get, "quality_check")
        if (
            previous
            and previous["value"].get("passed")
            and previous["value"].get("source_hash")
            == await asyncio.to_thread(source_version)
            and (datetime.now(UTC) - previous["updated_at"]).total_seconds() < 86400
        ):
            return {"skipped": True}
        return await asyncio.to_thread(self.quality.evaluate)

    async def _repeat(self, name, interval, operation, *args):
        """ждёт интервал после завершения операции и не запускает её повторно параллельно самой себе"""
        while not self.stop_event.is_set():
            await self._call(name, operation, *args)
            try:
                await asyncio.wait_for(self.stop_event.wait(), timeout=interval)
            except TimeoutError:
                pass

    async def run(self, *, once=False):
        """обновляет состояние worker, при недоступной БД сохраняет исходную причину остановки"""
        try:
            success = await self._run(once=once)
        finally:
            try:
                await asyncio.to_thread(
                    self.runtime.save,
                    "worker",
                    {
                        "worker_id": self.worker_id,
                        "analysis_enabled": False,
                        "status": "stopped",
                    },
                )
            except (SQLAlchemyError, OSError) as error:
                logger.error("Worker stop state not saved: %s", type(error).__name__)
                success = False
        return success

    async def _run(self, *, once=False):
        """синхронизирует теги и запускает один проход либо постоянные фоновые циклы"""
        await asyncio.to_thread(self.news.news.sync_tag_catalog)
        try:
            config = settings()
            config["LLM_MODEL_ANALYSIS"] = config.get(
                "LLM_MODEL_ANALYSIS"
            ) or config.get("LLM_MODEL_CONTEXT", "")
            validate_configuration(config, "LLM_MODEL_ANALYSIS")
        except ValueError:
            self.analysis_enabled = False
            logger.warning("LLM analysis is not configured")
        for field, model in (
            ("tagging_enabled", "LLM_MODEL_TAGGING"),
            ("profiles_enabled", "LLM_MODEL_CONTEXT"),
        ):
            try:
                validate_configuration(config, model)
            except ValueError:
                setattr(self, field, False)
                logger.warning(
                    "%s is not configured; saved features remain available", model
                )
        reports_ok = await self._call("reports", self.import_reports)
        await self.heartbeat()
        if once:
            success = reports_ok
            if self.profiles_enabled:
                success = (
                    await self._call("profiles", self.process_profiles) and success
                )
            if self.settings.market_enabled:
                success = await self._call("market", self.refresh_market) and success
            for source in self.settings.sources:
                if self.stop_event.is_set():
                    return success
                success = (
                    await self._call(source.code, self.fetch_source, source) and success
                )
            if not self.stop_event.is_set() and self.tagging_enabled:
                success = await self._call("tagging", self.tag_news) and success
            if not self.stop_event.is_set():
                success = (
                    await self._call("analysis", self.process_analysis) and success
                )
            return success
        # TaskGroup завершает все циклы вместе, отдельный сервис не держит общую сессию БД
        async with asyncio.TaskGroup() as tasks:
            tasks.create_task(self._repeat("heartbeat", 15, self.heartbeat))
            tasks.create_task(self._repeat("monitoring", 60, self.monitor))
            tasks.create_task(self._repeat("quality", 3600, self.check_quality))
            if self.profiles_enabled:
                tasks.create_task(
                    self._repeat(
                        "profiles",
                        self.settings.profile_interval,
                        self.process_profiles,
                    )
                )
            if self.settings.market_enabled:
                tasks.create_task(
                    self._repeat(
                        "market", self.settings.market_interval, self.refresh_market
                    )
                )
            for source in self.settings.sources:
                tasks.create_task(
                    self._repeat(
                        source.code,
                        self.settings.fetch_interval,
                        self.fetch_source,
                        source,
                    )
                )
            if self.tagging_enabled:
                tasks.create_task(
                    self._repeat(
                        "tagging", self.settings.tagging_interval, self.tag_news
                    )
                )
            if self.analysis_enabled:
                tasks.create_task(
                    self._repeat(
                        "analysis",
                        self.settings.analysis_interval,
                        self.process_analysis,
                    )
                )
        return True
