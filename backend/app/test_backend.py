"""проверяет сквозной сценарий в отдельной схеме PostgreSQL без внешних LLM-запросов"""

import asyncio
import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from app.api import dependencies
from app.api.application import ApiSettings, create_app
from app.api.insights import (
    get_question_service,
    get_report_service,
    get_runtime_service,
)
from app.api.market import get_market_service
from app.demo_data import create_demo_data
from app.import_news import DEFAULT_FILE, import_bundle, read_bundle
from app.infrastructure.database.base import Base
from app.infrastructure.database.session import get_engine
from app.infrastructure.database.uow import UnitOfWork
from app.parser.models import MarketQuote
from app.schemas.agent import (
    AnalysisDraft,
    DraftStatement,
    FollowupAnswer,
    Review,
    SearchPlan,
)
from app.schemas.database import CompanyData
from app.schemas.insights import EvidenceStatement, SourceReference
from app.schemas.news import Geography, NewsFeatures, NewsTag, StoredNews
from app.schemas.reports import ReportInput, ReportPart
from app.schemas.services import Registration
from app.schemas.worker import WorkerSettings
from app.services.ai_agents._common import check_gateway_budget
from app.services.ai_agents.analysis import (
    AnalysisAgent,
    prepare_evidence,
    resolve_statements,
    validate_public_text,
    validate_statements,
)
from app.services.ai_agents.client import JsonClient
from app.services.feed import FeedService
from app.services.feedback import FeedbackService
from app.services.insights import InsightService
from app.services.market import MarketService
from app.services.news import NewsService
from app.services.news_pipeline import NewsPipeline
from app.services.profiles import ProfileService
from app.services.questions import QuestionService
from app.services.ranking import rank_news
from app.services.reports import ReportService
from app.services.runtime import RuntimeService
from app.services.worker import BackgroundWorker


@pytest.fixture(scope="module")
def database():
    """создаёт и удаляет только уникальную тестовую схему в настроенной БД"""
    if os.environ.get("RUN_DATABASE_TESTS") != "1":
        pytest.skip("Set RUN_DATABASE_TESTS=1 to use an isolated PostgreSQL schema")
    parent = get_engine()
    schema = "backend_test_" + uuid4().hex
    with parent.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(
        parent.url,
        hide_parameters=True,
        connect_args={"options": f"-c search_path={schema} -c timezone=UTC"},
    )
    try:
        Base.metadata.create_all(engine, checkfirst=False)
        sql = (Path(__file__).parent / "infrastructure/database/schema.sql").read_text(
            encoding="utf-8"
        )
        function = sql[
            sql.index("CREATE FUNCTION public.sync_reaction_totals") : sql.index(
                "SET default_tablespace"
            )
        ]
        trigger = re.search(
            r"CREATE TRIGGER trg_reaction_totals.*?;", sql, re.DOTALL
        ).group()
        with engine.begin() as connection:
            with connection.connection.driver_connection.cursor() as cursor:
                cursor.execute(
                    (function + trigger).replace("public.", schema + "."), prepare=False
                )
        yield engine
    finally:
        engine.dispose()
        with parent.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))


@pytest.fixture
def services(database):
    """подключает все сервисы к одной изолированной схеме"""

    def uow():
        return UnitOfWork(database)

    return {
        "uow": uow,
        "profiles": ProfileService(uow_factory=uow),
        "news": NewsService(uow_factory=uow),
        "insights": InsightService(uow_factory=uow),
        "reports": ReportService(uow_factory=uow),
        "runtime": RuntimeService(uow_factory=uow),
        "feedback": FeedbackService(uow_factory=uow),
        "feed": FeedService(ranker=rank_news, uow_factory=uow),
        "market": MarketService(uow_factory=uow),
    }


def test_news_bundle_restore_and_validation(services, tmp_path):
    """проверяет повторный импорт без LLM и отказ от разметки, сохранённой для другого текста"""
    bundle = json.loads(DEFAULT_FILE.read_text(encoding="utf-8"))
    bundle["items"] = bundle["items"][:2]
    for row in bundle["items"]:
        for key in (
            "features",
            "tagging_version",
            "content_hash",
            "features_published_at",
        ):
            row.pop(key, None)
    path = tmp_path / "examples.json"
    path.write_text(json.dumps(bundle, ensure_ascii=False), encoding="utf-8")
    news = services["news"]
    news.sync_tag_catalog()
    tag_id = news.list_tags()[0].id

    def classify(article):
        return NewsFeatures(
            news_id=article.news_id,
            tags=[NewsTag(id=tag_id, confidence=0.8)],
            geography=Geography(country_code="RU"),
        )

    tagger = SimpleNamespace(version="test-bundle-v1", tag=Mock(side_effect=classify))
    first = import_bundle(path, limit=1, tag=True, news_service=news, tagger=tagger)
    assert len(first) == 1 and tagger.tag.call_count == 1
    repeat = import_bundle(path, limit=1, tag=True, news_service=news, tagger=tagger)
    assert repeat == first and tagger.tag.call_count == 1
    assert news.get_news(first[0]).tagging_status == "ready"

    saved_bundle = read_bundle(path)
    saved_bundle["items"][0]["article"]["url"] += "?restore-test=1"
    path.write_text(json.dumps(saved_bundle), encoding="utf-8")
    restored = import_bundle(path, limit=1, news_service=news)
    assert restored != first
    assert news.get_news(restored[0]).features.news_id == restored[0]
    assert news.get_news(restored[0]).tagging_status == "ready"

    saved_bundle["items"][0]["features"]["business_scope"] = "general"
    saved_bundle["items"][0]["features"]["business_relevance"] = 0.9
    saved_bundle["items"][0]["tagging_version"] = "updated-context"
    path.write_text(json.dumps(saved_bundle), encoding="utf-8")
    import_bundle(
        path, limit=1, refresh_features=True, news_service=news, tagger=tagger
    )
    assert news.get_news(restored[0]).features.business_relevance == 0.9
    assert news.get_news(restored[0]).tagging_version == "updated-context"
    assert tagger.tag.call_count == 1
    saved_bundle["items"][0]["article"]["body"] += " changed"
    path.write_text(json.dumps(saved_bundle), encoding="utf-8")
    with pytest.raises(ValueError, match="do not match"):
        import_bundle(path, news_service=news)
    assert "changed" not in news.get_news(restored[0]).text
    with pytest.raises(ValueError, match="positive"):
        import_bundle(path, limit=0, news_service=news)


def test_evidence_validation():
    """поддельная цитата и неизвестный признак не проходят проверку"""
    statement = EvidenceStatement(
        text="Вывод",
        source_refs=["news"],
        evidence_quotes={"news": "Ставка осталась прежней"},
    )
    sources = {"news": {"text": "Ставка осталась прежней после заседания"}}
    validate_statements([statement], sources, {})
    with pytest.raises(ValueError):
        validate_statements(
            [statement.model_copy(update={"company_feature_refs": ["invented"]})],
            sources,
            {},
        )
    with pytest.raises(ValueError):
        validate_statements(
            [
                statement.model_copy(
                    update={
                        "evidence_quotes": {"news": "Выручка выросла на сто процентов"}
                    }
                )
            ],
            sources,
            {},
        )


def test_evidence_selection():
    """несколько цитат одного источника сохраняют исходный текст, чужие ID отклоняются"""
    first = "Ключевая ставка снижена до шестнадцати процентов. " * 10
    last = "Прогноз инфляции на следующий год составляет четыре процента. " * 10
    source_text = first + "\n\n" + last
    sources = {
        "news": {
            "reference": SourceReference(id="news", title="Решение по ставке"),
            "text": source_text,
        }
    }
    payload, passages = prepare_evidence(sources)
    keys = [payload[0]["passages"][0]["id"], payload[0]["passages"][-1]["id"]]
    draft = DraftStatement(
        text="Ставка и прогноз инфляции изменились", evidence_ids={"news": keys}
    )
    result = resolve_statements([draft], passages, sources)[0]
    assert result.evidence_quotes["news"] in source_text
    assert all(passages[key][1] in result.evidence_quotes["news"] for key in keys)
    validate_statements([result], sources, {})
    for selection in ({"news": ["missing"]}, {"other": [keys[0]]}):
        with pytest.raises(ValueError):
            resolve_statements(
                [draft.model_copy(update={"evidence_ids": selection})],
                passages,
                sources,
            )
    with pytest.raises(ValueError):
        DraftStatement(text="Пустой выбор", evidence_ids={"news": []})


def test_provider_failure_preserves_news_queue():
    """сбой провайдера оставляет текущую новость в очереди и не запускает остальные"""
    article = StoredNews(
        news_id=uuid4(),
        title="Новость",
        text="Текст новости",
        published_at=datetime.now(UTC),
        content_hash="test",
        tagging_status="pending_tagging",
    )
    news = Mock()
    news.list_pending_news.return_value = [
        article,
        article.model_copy(update={"news_id": uuid4()}),
    ]
    tagger = Mock()
    tagger.tag.side_effect = RuntimeError("provider unavailable")
    result = NewsPipeline(news_service=news, tagger=tagger).tag_pending_news(limit=2)
    assert len(result.errors) == 1
    assert tagger.tag.call_count == 1
    news.mark_tagging_failed.assert_not_called()
    news.save_features.assert_not_called()


def test_gateway_budget_reserve():
    """низкий остаток блокирует платный вызов, в БД сохраняются только поля бюджета"""
    runtime = Mock()
    response = Mock()
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    response.read.return_value = json.dumps(
        {"key": "secret", "info": {"spend": 460, "max_budget": 500}}
    ).encode()
    config = {"LLM_BASE_URL": "https://example.test/v1", "LLM_API_KEY": "test"}
    with patch("app.services.ai_agents._common.build_opener") as opener:
        opener.return_value.open.return_value = response
        with pytest.raises(RuntimeError, match="reserve"):
            check_gateway_budget(config, runtime)
    value = runtime.save.call_args.args[1]
    assert value["remaining"] == 40 and "key" not in value
    runtime.reserve_call.assert_not_called()


def test_truncated_response_is_not_retried():
    """обрезанный ответ не вызывает платную коррекцию, запрос GLM использует low"""
    runtime = Mock()
    client = JsonClient(runtime=runtime)
    client.config = {
        "LLM_BASE_URL": "https://example.test/v1",
        "LLM_API_KEY": "unit-test",
        "LLM_MODEL_ANALYSIS": "z-ai/glm-5.3-flash",
    }
    calls = []

    def respond(request):
        calls.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "usage": {"completion_tokens": 8192},
                "choices": [{"finish_reason": "length", "message": {"content": "{"}}],
            },
        )

    original_client = httpx.AsyncClient
    with (
        patch("app.services.ai_agents.client.check_gateway_budget"),
        patch(
            "app.services.ai_agents.client.httpx.AsyncClient",
            side_effect=lambda **kwargs: original_client(
                transport=httpx.MockTransport(respond), **kwargs
            ),
        ),
        pytest.raises(RuntimeError, match="finish"),
    ):
        asyncio.run(client.ask("План", {}, SearchPlan))
    assert len(calls) == 1 and calls[0]["reasoning_effort"] == "low"
    assert runtime.finish_call.call_args.args[1] == "failed"


def test_worker_stops_and_reports_import_errors():
    """однопроходный запуск отражает ошибку импорта и оставляет heartbeat остановленным"""
    runtime = Mock()
    worker = BackgroundWorker(
        runtime=runtime, settings=WorkerSettings(sources=[], market_enabled=False)
    )
    worker.news = Mock()
    worker.import_reports = AsyncMock(return_value={"errors": [{"document": "broken"}]})
    worker.process_profiles = AsyncMock()
    worker.tag_news = AsyncMock()
    worker.process_analysis = AsyncMock()
    with patch("app.services.worker.validate_configuration"):
        assert asyncio.run(worker.run(once=True)) is False
    assert runtime.save.call_args.args[1]["status"] == "stopped"


class FixtureTransport:
    """имитирует ответы разных шагов модели, поиск и сохранение остаются настоящими"""

    calls = 0

    async def __call__(self, messages, schema):
        self.calls += 1
        data = json.loads(messages[-1]["content"])
        if schema is SearchPlan:
            return SearchPlan(
                queries=["перевозки"], feature_keys=["industry"]
            ).model_dump_json()
        if schema is Review:
            draft = data.get("result", data.get("answer"))
            assert draft is not None
            assert "evidence_quotes" not in json.dumps(draft)
            passages = {
                source["id"]: {p["id"] for p in source["passages"]}
                for source in data["sources"]
            }
            groups = (
                [draft["statements"]]
                if "statements" in draft
                else [
                    draft[name]
                    for name in (
                        "facts",
                        "why_important",
                        "risks",
                        "opportunities",
                        "recommendations",
                    )
                ]
            )
            for group in groups:
                for statement in group:
                    for ref, keys in statement["evidence_ids"].items():
                        assert set(keys) <= passages[ref]
            return Review(supported=True).model_dump_json()
        if schema is FollowupAnswer:
            source = data["sources"][0]
            return FollowupAnswer(
                statements=[
                    DraftStatement(
                        text="Уточнение по исходному материалу",
                        evidence_ids={source["id"]: [source["passages"][0]["id"]]},
                    )
                ]
            ).model_dump_json()
        source = data["sources"][0]
        evidence = DraftStatement(
            text="Событие касается перевозок",
            evidence_ids={source["id"]: [source["passages"][0]["id"]]},
        )
        return AnalysisDraft(
            facts=[evidence],
            why_important=[
                {**evidence.model_dump(), "company_feature_refs": ["industry"]}
            ],
            risks=[],
            opportunities=[],
            recommendations=[],
            bank_position=None,
            limitations=[],
        ).model_dump_json()


@pytest.mark.parametrize("corrected", [False, True])
def test_review_with_passage_ids_still_controls_publication(corrected):
    """неподтверждённые выводы проходят коррекцию и публикуются только после одобрения"""
    fixture = FixtureTransport()
    reviews = []

    async def transport(messages, schema):
        result = await fixture(messages, schema)
        if schema is Review:
            reviews.append(json.loads(messages[-1]["content"]))
            if len(reviews) == 1 or not corrected:
                return Review(
                    supported=False, issues=["Вывод не подтверждён"]
                ).model_dump_json()
        return result

    agent = AnalysisAgent(
        client=JsonClient(transport=transport),
        insights=Mock(search_reports=Mock(return_value=[])),
        reports=Mock(),
    )
    work = SimpleNamespace(
        news=SimpleNamespace(
            news_id=uuid4(),
            title="Стоимость перевозок выросла",
            text="Перевозки дорожают, поэтому необходимо проверять транспортные расходы компании",
            source_url="https://example.org/news",
            published_at=datetime(2026, 10, 22, 21, tzinfo=UTC),
        ),
        context=SimpleNamespace(
            id=uuid4(), company_id="test", payload_json={"industry": "Перевозки"}
        ),
    )
    if corrected:
        result = asyncio.run(agent.analyze(work))
        assert result.result.facts[0].evidence_quotes
        assert [step["supported"] for step in result.trace if "supported" in step] == [
            False,
            True,
        ]
    else:
        with pytest.raises(ValueError, match="verification failed"):
            asyncio.run(agent.analyze(work))
    assert len(reviews) == 2 and fixture.calls == 5
    assert reviews[0]["sources"][0]["published_on"] == "2026-10-23"
    assert reviews[1]["previous_draft"] == reviews[0]["result"]


def test_analysis_schema_rejects_unlinked_company_claims_and_unconditional_risks():
    """схема для модели требует признаки компании и условия сценариев до проверки цитат"""
    statement = {"text": "Подтверждённый факт", "evidence_ids": {"news:one": ["e1"]}}
    for section in ("why_important", "risks", "opportunities"):
        with pytest.raises(ValueError):
            AnalysisDraft.model_validate({"facts": [statement], section: [statement]})
    assert AnalysisDraft.model_validate({"facts": [statement]}).why_important == []


@pytest.mark.parametrize("field", ["text", "condition", "limitations"])
def test_analysis_rejects_internal_fields_in_public_text(field):
    """отклоняет внутренние имена в тексте для пользователя, сохраняя дословность цитат"""
    statement = SimpleNamespace(
        text="Позиция банка не подтверждена",
        condition=None,
        evidence_quotes={"news:one": "bank_position из текста источника"},
    )
    validate_public_text([statement], ["Нет сведений о маршрутах компании"])
    limitations = []
    if field == "limitations":
        limitations = ["bank_position не сформирована"]
    else:
        setattr(statement, field, "Проверить CL_PRODUCT_LOA_MARK")
    with pytest.raises(ValueError, match="служебные имена"):
        validate_public_text([statement], limitations)


def test_followup_receives_saved_company_values():
    """передаёт в уточнение значения снимка компании, а не только названия полей"""
    captured = []
    fixture = FixtureTransport()

    async def transport(messages, schema):
        captured.append(json.loads(messages[-1]["content"]))
        return await fixture(messages, schema)

    agent = AnalysisAgent(client=JsonClient(transport=transport))
    from app.schemas.insights import InsightResult

    analysis = SimpleNamespace(
        result=InsightResult(
            company_id="test",
            news_id=uuid4(),
            facts=[],
            why_important=[],
            risks=[],
            opportunities=[],
            recommendations=[],
            bank_position=None,
            limitations=[],
            source_refs=[
                SourceReference(
                    id="news:one",
                    kind="news",
                    title="Новость",
                    excerpt="Подтверждённый текст исходной новости для уточнения",
                )
            ],
        )
    )
    context = SimpleNamespace(
        company_id="test",
        payload_json={
            "industry": "Перевозки на момент разбора",
            "revenue": "12000",
            "profile_json": {"CL_PRODUCT_LOA_MARK": "0.0"},
        },
    )
    asyncio.run(agent.answer(analysis, [], "Какая выручка?", context=context))
    for payload in captured:
        assert payload["company_features"] == {
            "industry": "Перевозки на момент разбора",
            "revenue": "12000",
            "CL_PRODUCT_LOA_MARK": "0.0",
        }


def test_api_and_worker_cycle(services):
    """проходит вход, ленту, реакции, разбор, кеш, вопрос и смену компании через реальную БД"""
    s = services
    create_demo_data(s["profiles"], s["news"])
    report = ReportInput(
        filename="fixture.pdf",
        title="Перевозки",
        file_hash="a" * 64,
        parts=[
            ReportPart(
                page_num=1,
                chunk_no=0,
                text="Перевозки дорожают, поэтому необходимо проверять транспортные расходы компании",
            )
        ],
    )
    report_id = s["reports"].save_report(report)
    assert s["reports"].save_report(report) == report_id
    chunks = s["insights"].search_reports("перевозки")
    assert chunks and s["reports"].get_chunk(chunks[0].id).page_num == 1
    transport = FixtureTransport()
    agent = AnalysisAgent(
        client=JsonClient(transport=transport),
        insights=s["insights"],
        reports=s["reports"],
    )
    questions = QuestionService(
        insights=s["insights"], agent=agent, uow_factory=s["uow"]
    )
    app = create_app(ApiSettings(_env_file=None))
    for dependency, service in [
        (dependencies.get_profile_service, s["profiles"]),
        (dependencies.get_news_service, s["news"]),
        (dependencies.get_feed_service, s["feed"]),
        (dependencies.get_feedback_service, s["feedback"]),
        (dependencies.get_insight_service, s["insights"]),
        (get_report_service, s["reports"]),
        (get_runtime_service, s["runtime"]),
        (get_market_service, s["market"]),
        (get_question_service, questions),
    ]:
        app.dependency_overrides[dependency] = lambda service=service: service
    with TestClient(app) as client:
        assert client.get("/api/profile").status_code == 401
        session = client.post(
            "/api/auth/demo",
            json={
                "company_id": "demo-api-company",
                "job_role": "cfo",
            },
        )
        assert session.status_code == 201, session.text
        client.headers["Authorization"] = "Bearer " + session.json()["access_token"]
        assert (
            client.get("/api/companies", params={"query": "demo-api"}).json()[0]["id"]
            == "demo-api-company"
        )
        assert session.json()["user"]["city"] == ""
        updated = client.put("/api/profile/settings", json={"job_role": "cfo"})
        assert updated.status_code == 200
        assert updated.json()["city"] == ""
        updated = client.put(
            "/api/profile/settings", json={"city": "Казань", "job_role": "cfo"}
        )
        assert updated.status_code == 200
        updated = client.put("/api/profile/settings", json={"job_role": "cfo"})
        assert updated.status_code == 200
        assert updated.json()["city"] == "Казань"
        page = client.post("/api/feed", json={"page_size": 1}).json()
        assert page["generated_at"] and page["expires_at"] and page["has_more"]
        news_id = page["items"][0]["ranking"]["news_id"]
        snapshot = page["snapshot_id"]
        assert (
            client.put(
                f"/api/news/{news_id}/reaction",
                json={"snapshot_id": snapshot, "reaction": "like"},
            ).json()["my_reaction"]
            == "like"
        )
        assert (
            client.get(f"/api/feed/{snapshot}").json()["items"][0]["my_reaction"]
            == "like"
        )
        event = {
            "event_id": str(uuid4()),
            "snapshot_id": snapshot,
            "news_id": news_id,
            "occurred_at": datetime.now(UTC).isoformat(),
        }
        assert (
            client.post("/api/impressions", json=event).json()
            == client.post("/api/impressions", json=event).json()
        )
        repeated = {**event, "event_id": str(uuid4())}
        assert (
            client.post("/api/impressions", json=repeated).json()["event_id"]
            == event["event_id"]
        )
        opened = {k: v for k, v in event.items() if k != "news_id"}
        assert client.post(f"/api/news/{news_id}/open", json=opened).status_code == 400
        opened["event_id"] = str(uuid4())
        first_open = client.post(f"/api/news/{news_id}/open", json=opened)
        assert first_open.status_code == 200, first_open.text
        assert first_open.json()["event_type"] == "open"
        opened["event_id"] = str(uuid4())
        assert (
            client.post(f"/api/news/{news_id}/open", json=opened).json()
            == first_open.json()
        )
        assert (
            client.post(
                f"/api/news/{news_id}/open", json={**opened, "browser": "unnecessary"}
            ).status_code
            == 422
        )
        complaint = {"snapshot_id": snapshot, "wrong_tag_ids": ["demo-api-logistics"]}
        first = client.post(f"/api/news/{news_id}/tag-feedback", json=complaint)
        assert first.status_code == 201, first.text
        assert (
            first.json()
            == client.post(f"/api/news/{news_id}/tag-feedback", json=complaint).json()
        )
        assert (
            client.post(
                f"/api/news/{news_id}/analysis", json={"idempotency_key": "first"}
            ).status_code
            == 503
        )
        s["runtime"].save("worker", {"status": "running", "analysis_enabled": True})
        job = client.post(
            f"/api/news/{news_id}/analysis", json={"idempotency_key": "first"}
        )
        assert job.status_code == 202, job.text
        assert (
            job.json()["id"]
            == client.post(
                f"/api/news/{news_id}/analysis", json={"idempotency_key": "first"}
            ).json()["id"]
        )
        worker = BackgroundWorker(
            insights=s["insights"],
            reports=s["reports"],
            agent=agent,
            runtime=s["runtime"],
        )
        analysis = asyncio.run(worker.process_analysis())
        assert analysis.result.facts and analysis.trace
        assert (
            client.get(f"/api/analysis-jobs/{job.json()['id']}").json()["status"]
            == "ready"
        )
        assert client.get(f"/api/analyses/{analysis.id}/trace").status_code == 200
        context = client.get(f"/api/analyses/{analysis.id}/context")
        assert context.status_code == 200, context.text
        assert context.json()["company_id"] == "demo-api-company"
        saved_payload = context.json()["payload_json"]
        assert saved_payload["industry"] == "Синтетическая транспортная компания"
        calls = transport.calls
        client.post(f"/api/news/{news_id}/analysis", json={"idempotency_key": "cached"})
        assert asyncio.run(worker.process_analysis()).id == analysis.id
        assert transport.calls == calls
        response = client.post(
            f"/api/analyses/{analysis.id}/questions",
            json={
                "conversation_id": str(uuid4()),
                "question": "Какие данные использованы?",
            },
        )
        assert response.status_code == 200, response.text
        assert response.json()["sources_json"]
        no_data = s["insights"].save_answer(
            UUID(session.json()["user"]["id"]),
            analysis.id,
            uuid4(),
            question="Каковы точные потери?",
            answer="Недостаточно данных для расчёта",
            sources=[],
        )
        assert no_data.sources_json == []
        assert (
            client.get(f"/api/report-chunks/{chunks[0].id}").json()["text"]
            == chunks[0].text
        )
        company = s["profiles"].get_company("demo-api-company")
        s["profiles"].save_company(
            company.model_copy(
                update={"industry": "Новый профиль", "profile_version": "changed"}
            )
        )
        assert (
            client.get(f"/api/analyses/{analysis.id}/context").json()["payload_json"]
            == saved_payload
        )
        s["profiles"].save_company(CompanyData(id="other", profile_version="1"))
        assert (
            client.put("/api/profile/company", json={"company_id": "other"}).status_code
            == 200
        )
        assert client.get(f"/api/feed/{snapshot}").status_code == 403
        assert client.get(f"/api/analyses/{analysis.id}").status_code == 403
        assert client.get(f"/api/analyses/{analysis.id}/context").status_code == 403
        assert client.post("/api/auth/logout").status_code == 204
        assert client.get("/api/profile").status_code == 401


def test_market_snapshot(services):
    """проверяет оборот, проценты, кеш и устаревание без запроса к MOEX"""
    timestamp = datetime.now(UTC).isoformat()
    quote = MarketQuote(
        ticker="TEST",
        name="Тест",
        raw={
            "security": {"PREVPRICE": 100},
            "marketdata": {
                "SYSTIME": timestamp,
                "LAST": 110,
                "VALTODAY": 5000,
                "VOLTODAY": 45,
            },
        },
    )
    service = MarketService(
        uow_factory=services["uow"], fetcher=lambda **kwargs: [quote]
    )
    assert service.refresh() == 1
    result = service.get_overview()
    assert result.status == "ready" and result.top_movers[0].change_percent == 10
    assert result.heatmap[0].size_metric == 5000
    assert result.heatmap[0].volume == 45
    services["runtime"].save("market", {"status": "failed"})
    assert service.get_overview().status == "stale"


def test_budget_and_profile_queue(services):
    """проверяет лимит модели и отсутствие повторной обработки неизменного профиля"""
    runtime = services["runtime"]
    runtime.reserve_call("analyst", "fixture", 1)
    with pytest.raises(RuntimeError):
        runtime.reserve_call("analyst", "fixture", 1)
    services["profiles"].save_company(CompanyData(id="pending", profile_version="one"))
    services["profiles"].register_demo(
        Registration(company_id="pending", city="Москва")
    )
    with services["uow"]() as db:
        assert "pending" in [
            c.id for c in db.companies.pending_tagging("test", limit=100)
        ]
    runtime.save("profile:pending", {"version": "one|test", "status": "ready"})
    with services["uow"]() as db:
        assert "pending" not in [
            c.id for c in db.companies.pending_tagging("test", limit=100)
        ]


def test_training_signals_use_snapshot_and_do_not_duplicate_content(services):
    """показы и открытия ссылаются на снимок, а признаки не меняются после новой разметки"""
    s = services
    create_demo_data(s["profiles"], s["news"])
    first = s["profiles"].register_demo(
        Registration(company_id="demo-api-company", city="Москва")
    )
    second = s["profiles"].register_demo(
        Registration(company_id="demo-api-company", city="Москва")
    )
    page = s["feed"].create_feed(first.user.id)
    news_id = page.items[0].ranking.news_id
    event = dict(
        event_id=uuid4(),
        user_id=first.user.id,
        snapshot_id=page.snapshot_id,
        news_id=news_id,
        occurred_at=datetime.now(UTC),
    )
    with pytest.raises(PermissionError):
        s["feedback"].record_open(**{**event, "user_id": second.user.id})
    with pytest.raises(PermissionError):
        s["feedback"].record_open(**{**event, "news_id": uuid4()})
    with s["uow"]() as db:
        details = db._session.execute(
            text(
                "SELECT ranking_details FROM feed_snapshot_items WHERE snapshot_id=:id AND position=0"
            ),
            {"id": page.snapshot_id},
        ).scalar_one()
        features = details["training_features"]
        assert set(features) == {
            "schema_version",
            "business_scope",
            "business_relevance",
            "geography",
            "content_hash",
            "tagging_version",
            "synthetic",
            "tags",
        }
        assert features["synthetic"] is True
        assert features["tags"][0] == {
            "id": "demo-api-logistics",
            "confidence": 1,
            "quality_weight": 1,
        }
        db._session.execute(
            text("UPDATE news_tags SET quality_weight=0.25 WHERE news_id=:id"),
            {"id": news_id},
        )
        db.commit()
    saved = s["feedback"].record_open(**event)
    assert s["feedback"].record_open(**{**event, "event_id": uuid4()}) == saved
    with s["uow"]() as db:
        stored = db._session.execute(
            text(
                "SELECT ranking_details FROM feed_snapshot_items WHERE snapshot_id=:id AND position=0"
            ),
            {"id": page.snapshot_id},
        ).scalar_one()
        assert stored["training_features"] == features
        payload = db._session.execute(
            text("SELECT payload_json FROM interaction_events WHERE event_id=:id"),
            {"id": saved.event_id},
        ).scalar_one()
        assert payload == {}


def test_feed_preserves_geography_and_reads_old_snapshots(services):
    """сохраняет географический бонус и читает снимки без новых полей"""
    from app.schemas.services import IncomingNews, Interests

    s = services
    s["news"].sync_tag_catalog()
    s["profiles"].save_company(
        CompanyData(id="geo-company", profile_version="one", city="г. Сочи")
    )
    session = s["profiles"].register_demo(
        Registration(company_id="geo-company", city="Москва")
    )
    s["profiles"].set_interests(
        session.user.id, Interests(personal=["biz_agr"], disabled=[])
    )
    s["news"].register_source("geo-test", kind="test")
    article = s["news"].save_news(
        IncomingNews(
            source="geo-test",
            url="https://example.com/geo-test",
            title="Сельское хозяйство края",
            body="Новость о сельском хозяйстве Краснодарского края",
            published_at=datetime.now(UTC),
        )
    )
    s["news"].save_features(
        NewsFeatures(
            news_id=article.news_id,
            tags=[NewsTag(id="biz_agr", confidence=1)],
            geography=Geography(region_codes=["reg_23"]),
        ),
        version="test-geo",
        expected_content_hash=article.content_hash,
        expected_published_at=article.published_at,
    )
    with s["uow"]() as db:
        db._session.execute(
            text(
                "UPDATE news SET extracted_features = extracted_features #- '{geography,city_codes}' WHERE id=:id"
            ),
            {"id": article.news_id},
        )
        db.commit()
    page = s["feed"].create_feed(session.user.id, page_size=100)
    item = next(row for row in page.items if row.ranking.news_id == article.news_id)
    assert item.ranking.geography_score == 0.5
    assert item.ranking.geography_bonus > 0
    assert "Краснодарский край" in item.ranking.geography_reason
    assert item.ranking.ranking_version == "formula-v3-business-context"
    with s["uow"]() as db:
        snapshot = db._session.execute(
            text("SELECT preference_context_json FROM feed_snapshots WHERE id=:id"),
            {"id": page.snapshot_id},
        ).scalar_one()
        assert snapshot["registered_region_code"] == "reg_23"
        assert snapshot["operating_region_codes"] is None
        db._session.execute(
            text(
                "UPDATE feed_snapshot_items SET ranking_details = ranking_details - 'geography_score' - 'geography_bonus' - 'geography_reason' - 'ranking_version' WHERE snapshot_id=:id"
            ),
            {"id": page.snapshot_id},
        )
        db.commit()
    old_page = s["feed"].get_page(session.user.id, page.snapshot_id, limit=100)
    old_item = next(
        row for row in old_page.items if row.ranking.news_id == article.news_id
    )
    assert old_item.ranking.geography_score is None
    assert old_item.ranking.ranking_version is None


def test_failed_analysis_does_not_publish_result(services):
    """таймаут агента завершает задание ошибкой без сохранённого AI-разбора"""
    s = services
    create_demo_data(s["profiles"], s["news"])
    session = s["profiles"].register_demo(
        Registration(company_id="demo-api-company", city="Москва")
    )
    page = s["feed"].create_feed(session.user.id)
    job = s["insights"].request_analysis(
        session.user.id, page.items[0].ranking.news_id, idempotency_key="timeout"
    )
    agent = AnalysisAgent(
        client=JsonClient(transport=FixtureTransport()),
        insights=s["insights"],
        reports=s["reports"],
    )
    agent.analyze = AsyncMock(side_effect=TimeoutError())
    worker = BackgroundWorker(insights=s["insights"], agent=agent, runtime=s["runtime"])
    with pytest.raises(TimeoutError):
        asyncio.run(worker.process_analysis())
    saved = s["insights"].get_job(session.user.id, job.id)
    assert saved.status == "failed" and saved.error_code == "analysis_timeout"
    assert saved.analysis_id is None


def test_demo_company_selection_and_search(services):
    """проверяет поиск внутри выбранных 50 компаний и сохранность полного каталога"""
    from app.services.profiles import demo_company_ids

    ids = demo_company_ids()
    assert len(ids) == len(set(ids)) == 50
    profile = services["profiles"]
    create_demo_data(profile, services["news"])
    assert [company.id for company in profile.list_companies(demo_selection=True)] == [
        "demo-api-company"
    ]
    assert profile.list_companies(demo_selection=True, query="несуществующая") == []
    for index, company_id in enumerate(ids):
        profile.save_company(
            CompanyData(
                id=company_id,
                profile_version="catalog-test",
                industry="Перевозки" if index == 0 else "Торговля",
                city="Казань",
                region="Татарстан",
                okved_code="49.41",
            )
        )
    profile.save_company(
        CompanyData(
            id="outside-catalog",
            profile_version="catalog-test",
            industry="Перевозки",
        )
    )
    app = create_app(ApiSettings(_env_file=None))
    app.dependency_overrides[dependencies.get_profile_service] = lambda: profile
    with TestClient(app) as client:
        response = client.get("/api/companies", params={"demo_selection": True})
        assert response.status_code == 200
        assert {c["id"] for c in response.json()} == set(ids)
        for query in ["перевозки", ids[0].lower()]:
            rows = client.get(
                "/api/companies",
                params={
                    "demo_selection": True,
                    "query": query,
                },
            ).json()
            assert ids[0] in {c["id"] for c in rows}
            assert "outside-catalog" not in {c["id"] for c in rows}
        for query in ["КАЗАНЬ", "Татарстан", "49.41"]:
            assert (
                len(
                    client.get(
                        "/api/companies",
                        params={
                            "demo_selection": True,
                            "query": query,
                        },
                    ).json()
                )
                == 50
            )
        assert (
            client.get(
                "/api/companies",
                params={
                    "demo_selection": True,
                    "query": "%",
                },
            ).json()
            == []
        )
        assert (
            client.get(
                "/api/companies",
                params={
                    "query": "outside-catalog",
                },
            ).json()[0]["id"]
            == "outside-catalog"
        )


def test_company_topics_are_initialized_without_llm(services):
    """вход и смена компании заполняют пустые темы, повторный вызов сохраняет ручные настройки"""
    from app.schemas.database import CompanyTagInput

    services["news"].sync_tag_catalog()
    profiles = services["profiles"]
    companies = [
        CompanyData(id="topics-it", profile_version="1", okved_code="62.01"),
        CompanyData(id="topics-freight", profile_version="1", okved_code="49.4"),
    ]
    for company in companies:
        profiles.save_company(company)
    session = profiles.register_demo(
        Registration(company_id=companies[0].id, job_role="ceo")
    )
    first = profiles.get_profile(session.user.id)
    assert {t.tag_id for t in first.company_tags} == {"biz_it", "biz_software"}
    second = profiles.switch_company(session.user.id, companies[1].id)
    assert {t.tag_id for t in second.company_tags} == {"biz_logistic", "biz_freight"}
    assert not profiles.ensure_company_topics(companies[1].id)
    manual = CompanyTagInput(tag_id="biz_tax", origin="manual", base_weight=1.8)
    profiles.set_company_tags(companies[0].id, [manual])
    assert not profiles.ensure_company_topics(companies[0].id)
    assert profiles.switch_company(session.user.id, companies[0].id).company_tags == [
        manual
    ]
    imported = CompanyData(id="topics-import", profile_version="1", okved_code="55.10")
    assert profiles.create_companies([imported]) == [imported.id]
    assert not profiles.ensure_company_topics(imported.id)


def test_real_company_feed_excludes_demo_sources(services):
    """одинаковые темы не переносят демонстрационные публикации в обычную ленту"""
    from app.schemas.database import CompanyTagInput
    from app.schemas.services import IncomingNews

    s = services
    create_demo_data(s["profiles"], s["news"])
    company = CompanyData(id="real-feed-check", profile_version="one")
    s["profiles"].save_company(company)
    s["profiles"].set_company_tags(
        company.id,
        [
            CompanyTagInput(
                tag_id="demo-api-logistics",
                origin="manual",
                base_weight=1,
            )
        ],
    )
    session = s["profiles"].register_demo(Registration(company_id=company.id))
    s["news"].register_source("real-feed-check", kind="test")
    article = s["news"].save_news(
        IncomingNews(
            source="real-feed-check",
            url="https://example.org/real-feed-check",
            title="Проверка источника",
            body="Публикация другого источника",
            published_at=datetime.now(UTC),
        )
    )
    s["news"].save_features(
        NewsFeatures(
            news_id=article.news_id,
            tags=[NewsTag(id="demo-api-logistics", confidence=1)],
            geography=Geography(),
        ),
        version="test",
        expected_content_hash=article.content_hash,
    )
    feed = s["feed"].create_feed(session.user.id)
    assert [item.ranking.news_id for item in feed.items] == [article.news_id]
