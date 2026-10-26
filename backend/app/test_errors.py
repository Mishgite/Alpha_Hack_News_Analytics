"""проверяет отказы без внешней сети, платных запросов и изменений рабочей схемы БД"""

import asyncio
import json
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.exc import TimeoutError as PoolTimeout

from app import test_backend as backend_checks
from app.api.application import ApiSettings, create_app
from app.api.dependencies import get_profile_service
from app.demo_data import create_demo_data
from app.schemas.agent import Review
from app.schemas.services import Registration
from app.services.ai_agents._common import check_gateway_budget
from app.services.ai_agents.client import JsonClient
from app.services.questions import QuestionService
from app.services.reports import ReportService
from app.services.worker import BackgroundWorker


@pytest.fixture(scope="module")
def database():
    """использует отдельную временную схему из общей проверки бэкенда"""
    yield from backend_checks.database.__wrapped__()


@pytest.fixture
def services(database):
    """создаёт сервисы с подключением только к тестовой схеме"""
    return backend_checks.services.__wrapped__(database)


@pytest.mark.parametrize(
    "error,status",
    [
        (ValueError("Invalid pagination"), 400),
        (LookupError("Company not found"), 404),
        (PermissionError("Access denied"), 403),
        (KeyError("private-key"), 500),
        (IndexError("private-key"), 500),
        (TypeError("private-key"), 500),
        (RuntimeError("private-key"), 503),
        (TimeoutError("private-key"), 504),
        (PoolTimeout("private-key"), 503),
        (OperationalError("SELECT private-key", {}, Exception("private-key")), 503),
        (IntegrityError("INSERT private-key", {}, Exception("private-key")), 409),
    ],
)
def test_http_errors(error, status):
    """ошибка возвращается как JSON с CORS, внутренние данные не попадают в ответ"""
    app = create_app(ApiSettings(_env_file=None))
    service = Mock()
    service.list_companies.side_effect = error
    app.dependency_overrides[get_profile_service] = lambda: service
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get(
            "/api/companies", headers={"Origin": "http://localhost:5173"}
        )
        assert response.status_code == status
        assert "detail" in response.json()
        assert "private-key" not in response.text
        assert (
            response.headers["access-control-allow-origin"] == "http://localhost:5173"
        )
        assert client.get("/health").status_code == 200


@pytest.mark.parametrize(
    "body",
    [
        {"company_id": "demo", "city": "secret\u0000city"},
        {"company_id": "demo", "city": "x" * 201},
        {"company_id": "demo", "city": "Москва", "job_role": "invalid"},
    ],
)
def test_bad_input_does_not_reach_service(body):
    """непригодный для PostgreSQL текст и неверная роль отклоняются до записи"""
    app = create_app(ApiSettings(_env_file=None))
    service = Mock()
    app.dependency_overrides[get_profile_service] = lambda: service
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post("/api/auth/demo", json=body)
        assert response.status_code == 422
        assert "secret" not in response.text
    service.register_demo.assert_not_called()


def test_paused_generation_blocks_new_jobs_but_preserves_existing_requests():
    from types import SimpleNamespace

    from fastapi import HTTPException

    from app.api.insights import get_processing_status, request_analysis

    user = SimpleNamespace(id=uuid4())
    runtime = Mock()
    runtime.get.side_effect = lambda key: (
        {
            "value": {"status": "running", "analysis_enabled": True},
            "updated_at": datetime.now(UTC),
        }
        if key == "worker"
        else None
    )
    runtime.generation_available.return_value = False
    service = Mock()
    service.find_requested_job.return_value = None
    assert get_processing_status(user, runtime)["analysis_available"] is False
    with pytest.raises(HTTPException) as error:
        request_analysis(
            uuid4(), SimpleNamespace(idempotency_key="test"), user, service, runtime
        )
    assert error.value.detail == "Analysis generation paused"
    service.request_analysis.assert_not_called()
    existing = object()
    service.find_requested_job.return_value = existing
    assert (
        request_analysis(
            uuid4(), SimpleNamespace(idempotency_key="test"), user, service, runtime
        )
        is existing
    )


def test_generation_limits_reset_and_keep_budget_reserve(services, monkeypatch):
    from app.services.ai_agents import _common

    monkeypatch.setattr(_common, "settings", lambda: {"LLM_DAILY_REQUEST_LIMIT": "1"})
    runtime = services["runtime"]
    assert runtime.generation_available()
    runtime.reserve_call("analyst", "fixture", 1)
    assert not runtime.generation_available()
    with services["uow"]() as db:
        db._session.execute(
            text("UPDATE llm_usage SET created_at=:old"),
            {"old": datetime.now(UTC) - timedelta(days=1)},
        )
        db.commit()
    assert runtime.generation_available()
    runtime.save(
        "llm_budget",
        {
            "remaining": 5,
            "reserve": 10,
            "reset_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
        },
    )
    assert not runtime.generation_available()
    runtime.save(
        "llm_budget",
        {
            "remaining": 5,
            "reserve": 10,
            "reset_at": (datetime.now(UTC) - timedelta(hours=1)).isoformat(),
        },
    )
    assert runtime.generation_available()


@pytest.mark.parametrize(
    "payload",
    [
        [],
        None,
        {"info": []},
        {"info": {"spend": "NaN", "max_budget": 500}},
        {"info": {"spend": 1, "max_budget": 500, "blocked": True}},
    ],
)
def test_invalid_budget_blocks_requests(payload):
    """неверный ответ о бюджете не разрешает платный вызов"""
    runtime = Mock()
    response = Mock()
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    response.read.return_value = json.dumps(payload).encode()
    with patch("app.services.ai_agents._common.build_opener") as opener:
        opener.return_value.open.return_value = response
        with pytest.raises(RuntimeError):
            check_gateway_budget(
                {"LLM_BASE_URL": "https://example.test/v1", "LLM_API_KEY": "test"},
                runtime,
            )
    runtime.reserve_call.assert_not_called()


@pytest.mark.parametrize(
    "payload",
    [
        [],
        None,
        {"choices": []},
        {"choices": [None]},
        {"choices": [{"finish_reason": "stop", "message": {"content": "not json"}}]},
    ],
)
def test_invalid_model_envelope(payload):
    """повреждённый ответ шлюза не повторяется и остаётся неудачной учтённой попыткой"""
    runtime = Mock()
    client = JsonClient(runtime=runtime)
    client.config = {
        "LLM_BASE_URL": "https://example.test/v1",
        "LLM_API_KEY": "test",
        "LLM_MODEL_ANALYSIS": "z-ai/glm-5.3-flash",
    }
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(
            200,
            content=json.dumps(payload),
            headers={"content-type": "application/json"},
        )

    original = httpx.AsyncClient
    with (
        patch("app.services.ai_agents.client.check_gateway_budget"),
        patch(
            "app.services.ai_agents.client.httpx.AsyncClient",
            side_effect=lambda **kwargs: original(
                transport=httpx.MockTransport(respond), **kwargs
            ),
        ),
    ):
        with pytest.raises((RuntimeError, ValueError)):
            asyncio.run(client.ask("Проверка", {}, Review))
    assert len(requests) == 1
    assert runtime.finish_call.call_args.args[1] == "failed"


@pytest.mark.parametrize(
    "failure,expected",
    [
        (401, RuntimeError),
        (429, RuntimeError),
        (500, RuntimeError),
        (httpx.ConnectError("private-key"), RuntimeError),
        (httpx.ReadTimeout("private-key"), TimeoutError),
    ],
)
def test_model_network_failure_has_bounded_retry(failure, expected):
    """повторяет временный отказ один раз, учитывает попытки и не раскрывает текст провайдера"""
    runtime = Mock()
    client = JsonClient(runtime=runtime)
    client.config = {
        "LLM_BASE_URL": "https://example.test/v1",
        "LLM_API_KEY": "test",
        "LLM_MODEL_ANALYSIS": "z-ai/glm-5.3-flash",
    }
    requests = []

    def respond(request):
        requests.append(request)
        if isinstance(failure, Exception):
            raise failure
        return httpx.Response(failure, text="private-key")

    original = httpx.AsyncClient
    with (
        patch("app.services.ai_agents.client.check_gateway_budget"),
        patch(
            "app.services.ai_agents.client.httpx.AsyncClient",
            side_effect=lambda **kwargs: original(
                transport=httpx.MockTransport(respond), **kwargs
            ),
        ),
    ):
        with pytest.raises(expected) as caught:
            asyncio.run(client.ask("Проверка", {}, Review))
    assert "private-key" not in str(caught.value)
    attempts = 2 if failure == 429 or isinstance(failure, httpx.ConnectError) else 1
    assert len(requests) == attempts
    assert runtime.reserve_call.call_count == attempts
    assert runtime.finish_call.call_count == attempts
    assert runtime.finish_call.call_args.args[1] == "failed"


def test_response_validation_is_internal_error():
    """ошибка схемы ответа является ошибкой сервера, а не неверным запросом пользователя"""
    app = create_app(ApiSettings(_env_file=None))
    service = Mock()
    service.list_companies.return_value = [{"id": None, "private": "private-key"}]
    app.dependency_overrides[get_profile_service] = lambda: service
    with TestClient(app) as client:
        response = client.get("/api/companies")
    assert response.status_code == 500
    assert response.json() == {"detail": "Internal server error"}


def test_worker_stop_keeps_original_error():
    """ошибка записи состояния остановки не скрывает причину завершения воркера"""
    runtime = Mock()
    runtime.save.side_effect = OperationalError("sql", {}, Exception("offline"))
    worker = BackgroundWorker(runtime=runtime)
    worker._run = AsyncMock(side_effect=TimeoutError("original"))
    with pytest.raises(TimeoutError, match="original"):
        asyncio.run(worker.run(once=True))
    worker._run = AsyncMock(return_value=True)
    assert asyncio.run(worker.run(once=True)) is False


def test_worker_loop_recovers_after_failure():
    """ошибка одной итерации не мешает следующей попытке после паузы"""
    worker = BackgroundWorker(runtime=Mock())
    calls = []

    async def operation():
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("source unavailable")
        worker.stop()

    asyncio.run(worker._repeat("fixture", 0.001, operation))
    assert len(calls) == 2


def test_question_cancellation_releases_slot():
    """отменённый вопрос не сохраняет ответ и освобождает слот пользователя"""
    insights = Mock()
    insights.get_history.return_value = []
    agent = Mock()
    agent.answer = AsyncMock(side_effect=asyncio.CancelledError())
    service = QuestionService(insights=insights, agent=agent)
    service.reserve, service.release = Mock(), Mock()
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(service.ask(uuid4(), uuid4(), uuid4(), "Вопрос"))
    service.release.assert_called_once()
    insights.save_answer.assert_not_called()


def test_malformed_report_does_not_stop_import(tmp_path):
    """повреждённый manifest не мешает обработке следующего документа"""
    for name, payload in (("a", []), ("b", {"complete": False})):
        folder = tmp_path / name
        folder.mkdir()
        (folder / "manifest.json").write_text(json.dumps(payload), encoding="utf-8")
    result = ReportService().import_directory(tmp_path)
    assert len(result["errors"]) == 1
    assert result["skipped"] == 1


def test_question_cleanup_keeps_original_error():
    """сбой освобождения слота не подменяет таймаут модели и не сохраняет ответ"""
    insights = Mock()
    insights.get_history.return_value = []
    agent = Mock()
    agent.answer = AsyncMock(side_effect=TimeoutError("model timeout"))
    service = QuestionService(insights=insights, agent=agent)
    service.reserve = Mock()
    service.release = Mock(
        side_effect=OperationalError("sql", {}, Exception("offline"))
    )
    with pytest.raises(TimeoutError, match="model timeout"):
        asyncio.run(service.ask(uuid4(), uuid4(), uuid4(), "Что изменилось?"))
    insights.save_answer.assert_not_called()
    service.release.assert_called_once()


def test_database_rollback_and_recovery(services):
    """ошибка транзакции откатывает данные, следующая операция работает через новую сессию"""
    runtime = services["runtime"]
    with pytest.raises(IntegrityError):
        with services["uow"]() as db:
            db.runtime.save("rollback-check", {"status": "temporary"})
            db._session.execute(
                text(
                    "INSERT INTO processing_states (key, value) VALUES (NULL, '{}'::jsonb)"
                )
            )
            db.commit()
    assert runtime.get("rollback-check") is None
    runtime.save("rollback-check", {"status": "ready"})
    assert runtime.get("rollback-check")["value"]["status"] == "ready"


def test_expired_lease_cannot_finish_new_attempt(services):
    """после повторной выдачи задания прежний worker не может записать результат"""
    s = services
    create_demo_data(s["profiles"], s["news"])
    user = (
        s["profiles"]
        .register_demo(Registration(company_id="demo-api-company", city="Москва"))
        .user
    )
    news_id = s["feed"].create_feed(user.id).items[0].ranking.news_id
    job = s["insights"].request_analysis(user.id, news_id, idempotency_key="lease-test")
    first = s["insights"].claim_job("first")
    assert first.id == job.id
    with s["uow"]() as db:
        db._session.execute(
            text("UPDATE analysis_jobs SET lease_until=:expired WHERE id=:id"),
            {"expired": datetime.now(UTC) - timedelta(seconds=1), "id": job.id},
        )
        db.commit()
    second = s["insights"].claim_job("second")
    assert second.attempts == first.attempts + 1
    with pytest.raises(ValueError):
        s["insights"].fail_job(job.id, "first", first.attempts, error_code="late")
    assert s["insights"].get_job(user.id, job.id).worker_id == "second"
    s["insights"].fail_job(
        job.id, "second", second.attempts, error_code="test_complete"
    )
