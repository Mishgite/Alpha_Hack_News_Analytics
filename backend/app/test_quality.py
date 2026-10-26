"""проверяет метрики, контроль версий отчётов и мониторинг на изолированной БД"""

import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import Mock
from uuid import uuid4

import pytest
from sqlalchemy import text

from app.evaluate import (
    apply_reviews,
    audit_quotes,
    failed_checks,
    ndcg,
    offline,
    regressions,
)
from app.prepare_submission import code_files, private_files
from app.schemas.news import Geography, NewsFeatures, NewsTag
from app.schemas.ranking import NewsCandidate, RankingProfile, RankingRequest
from app.schemas.reports import ReportInput, ReportPart
from app.services.quality import QualityService
from app.services.ranking import rank_news
from app.services.reports import ReportService
from app.test_backend import database, services  # noqa: F401


def test_regression_metrics_and_incompatible_baseline():
    cases = json.loads(
        Path(__file__).with_name("evaluation_cases.json").read_text(encoding="utf-8")
    )
    actual = offline(cases)
    assert actual["precision_at_5"] == 1
    assert ndcg([0, 3], [3, 0]) < 1
    report = {
        "cases_hash": "one",
        "corpus": "one",
        "database_enabled": True,
        "offline": actual,
    }
    assert regressions(report, report) == []
    worse = {**report, "offline": {**actual, "precision_at_5": 0.5}}
    assert regressions(worse, report) == ["offline.precision_at_5"]
    with pytest.raises(ValueError, match="another dataset"):
        regressions({**report, "corpus": "changed"}, report)


def test_quote_presence_is_separate_from_semantic_review():
    result = {
        "source_refs": [
            {"id": "news", "excerpt": "Текст подтверждённого источника", "kind": "news"}
        ],
        "facts": [
            {
                "text": "Непроверенный вывод",
                "source_refs": ["news"],
                "evidence_quotes": {"news": "Текст подтверждённого источника"},
            }
        ],
    }
    assert audit_quotes(result)["valid_quotes"] == 1
    result["facts"][0]["evidence_quotes"]["news"] = "Цитата отсутствует в оригинале"
    assert audit_quotes(result)["valid_quotes"] == 0
    metrics = {}
    apply_reviews(
        metrics,
        [{"id": "1", "fingerprint": "hash"}],
        [
            {
                "id": "1",
                "fingerprint": "hash",
                "supported": False,
                "reviewer": "test",
                "reason": "вывод не следует из цитаты",
            }
        ],
    )
    assert metrics["semantic_support_rate"] == 0
    with pytest.raises(ValueError, match="outdated"):
        apply_reviews(
            {},
            [{"id": "1", "fingerprint": "new"}],
            [{"id": "1", "fingerprint": "hash"}],
        )


def test_quality_rejects_missing_references_and_negative_reviews():
    regression = {
        "precision_at_5": 1,
        "ndcg_at_10": 1,
        "duplicate_precision": 1,
        "duplicate_recall": 1,
    }
    metrics = {
        "retrieval_recall_at_5": 1,
        "retrieval_negative_accuracy": 1,
        "exact_quote_rate": 1,
        "reference_coverage": 0.5,
        "bank_reference_valid": True,
        "semantic_support_rate": 0,
    }
    assert failed_checks(regression, metrics) == [
        "reference_coverage",
        "semantic_support_rate",
    ]
    metrics.update(
        reference_coverage=None, semantic_support_rate=None, exact_quote_rate=None
    )
    assert failed_checks(regression, metrics) == []


def test_quality_history_keeps_failure_and_is_bounded(services, monkeypatch):  # noqa: F811
    from app import evaluate

    monkeypatch.setattr(
        evaluate, "database_checks", Mock(side_effect=ValueError("private source text"))
    )
    service = QualityService(uow_factory=services["uow"])
    result = service.evaluate()
    assert result["passed"] is False
    assert result["errors"] == ["evaluation_error:ValueError"]
    assert "private source text" not in json.dumps(result)
    assert "quality_check_failed" in service.snapshot()["alerts"]
    with services["uow"]() as db:
        for number in range(35):
            db.runtime.record_quality_check({"passed": True, "number": number})
        db.commit()
    with services["uow"]() as db:
        history = db.runtime.get("quality_history")["value"]["items"]
        assert len(history) == 30
        assert history[0]["number"] == 5
        assert db.runtime.get("quality_check")["value"]["number"] == 34


def test_quality_rechecks_changed_code_and_failed_run():
    from app.evaluate import source_version
    from app.services.worker import BackgroundWorker

    worker = object.__new__(BackgroundWorker)
    state = {
        "updated_at": datetime.now(UTC),
        "value": {"passed": True, "source_hash": source_version()},
    }
    worker.runtime = Mock()
    worker.runtime.get.return_value = state
    worker.quality = Mock()
    worker.quality.evaluate.return_value = {"passed": True}
    assert asyncio.run(worker.check_quality()) == {"skipped": True}
    worker.quality.evaluate.assert_not_called()
    state["value"]["source_hash"] = "old"
    assert asyncio.run(worker.check_quality()) == {"passed": True}
    state["value"].update(source_hash=source_version(), passed=False)
    assert asyncio.run(worker.check_quality()) == {"passed": True}
    assert worker.quality.evaluate.call_count == 2


def test_counterparty_signal_is_bounded_and_does_not_open_local_events():
    now = datetime.now(UTC)
    profile = RankingProfile(
        user_id=uuid4(),
        company_id="test",
        job_role="ceo",
        profile_version="1",
        tag_weights={"own": 1.5},
        company_tag_ids=["own"],
        counterparty_tag_weights={"indirect": 0.25},
    )
    news = [
        NewsCandidate(
            published_at=now,
            features=NewsFeatures(
                news_id=uuid4(),
                tags=[NewsTag(id=tag, confidence=1)],
                business_scope=scope,
                business_relevance=1,
                geography=Geography(),
            ),
        )
        for tag, scope in [
            ("own", "industry"),
            ("indirect", "industry"),
            ("indirect", "local"),
            ("other", "industry"),
        ]
    ]
    result = rank_news(RankingRequest(profile=profile, candidates=news, now=now)).items
    assert [item.news_id for item in result] == [
        news[0].features.news_id,
        news[1].features.news_id,
    ]
    assert result[1].match_score == 0.25 < result[0].match_score


def test_monitoring_records_failures_and_recovers(services, monkeypatch):  # noqa: F811
    service = QualityService(uow_factory=services["uow"])
    runtime = services["runtime"]
    runtime.save("worker", {"status": "running"})
    for _ in range(3):
        runtime.record_operation("test-source", 4, False)
    snapshot = service.snapshot(persist=True)
    assert snapshot["worker_alive"]
    assert "test-source:three_failures" in snapshot["alerts"]
    assert snapshot["operations"]["test-source"]["p95_seconds"] == 4
    runtime.record_operation("test-source", 2, True)
    assert "test-source:three_failures" not in service.snapshot()["alerts"]
    with services["uow"]() as db:
        db._session.execute(
            text("UPDATE processing_states SET updated_at=:old WHERE key='worker'"),
            {"old": datetime.now(UTC) - timedelta(minutes=2)},
        )
        db.commit()
    assert not service.snapshot()["worker_alive"]
    from app.services.ai_agents import _common

    monkeypatch.setattr(_common, "settings", lambda: {"LLM_DAILY_REQUEST_LIMIT": "1"})
    runtime.reserve_call("tagger", "fixture", 100)
    assert "llm_daily_request_limit" in service.snapshot()["alerts"]


def test_latest_report_only_and_old_citation_available(services):  # noqa: F811
    name = uuid4().hex + ".pdf"
    service = services["reports"]
    old = ReportInput(
        filename=name,
        title="test",
        file_hash=uuid4().hex * 2,
        parts=[
            ReportPart(page_num=1, chunk_no=0, text="Проверкауникальная прежняя версия")
        ],
    )
    old_id = service.save_report(old)
    original = services["insights"].search_reports("Проверкауникальная")[0]
    with services["uow"]() as db:
        db._session.execute(
            text("UPDATE alfa_reports SET ingested_at=:old WHERE id=:id"),
            {"old": datetime.now(UTC) - timedelta(days=1), "id": old_id},
        )
        db.commit()
    service.save_report(
        old.model_copy(
            update={
                "file_hash": uuid4().hex * 2,
                "parts": [
                    ReportPart(
                        page_num=1,
                        chunk_no=0,
                        text="Проверкауникальная исправленная версия",
                    )
                ],
            }
        )
    )
    found = services["insights"].search_reports("Проверкауникальная")
    assert len(found) == 1 and "исправленная" in found[0].text
    assert "прежняя" in service.get_chunk(original.id).text
    service.save_report(
        old.model_copy(
            update={
                "filename": "future-" + name,
                "file_hash": uuid4().hex * 2,
                "report_date": datetime.now(UTC).date() + timedelta(days=10),
            }
        )
    )
    assert len(services["insights"].search_reports("Проверкауникальная")) == 1


def test_report_import_prefers_reviewed_text(tmp_path):
    folder = tmp_path / "report"
    folder.mkdir()
    manifest = {
        "complete": True,
        "source_file": "x.pdf",
        "source_sha256": "hash",
        "pages": [{"json": "page.json"}],
    }
    page = {
        "page": 1,
        "blocks": [
            {"number": 1, "status": "text_candidate", "text": "исходная ошибка " * 10}
        ],
        "display_blocks": [
            {
                "number": 2,
                "status": "text_candidate",
                "display_text": "исправленный текст " * 10,
            }
        ],
    }
    (folder / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (folder / "page.json").write_text(json.dumps(page), encoding="utf-8")
    service = ReportService()
    service.save_report = Mock()
    assert not service.import_directory(tmp_path)["errors"]
    assert "исправленный" in service.save_report.call_args.args[0].parts[0].text
    page["manual_transcription"] = "ручная проверенная расшифровка " * 10
    page.pop("blocks")
    page.pop("display_blocks")
    (folder / "page.json").write_text(json.dumps(page), encoding="utf-8")
    service.import_directory(tmp_path)
    part = service.save_report.call_args.args[0].parts[0]
    assert (
        "ручная" in part.text
        and part.source_span_json["method"] == "manual_transcription"
    )


def test_submission_excludes_secrets_and_preserves_news():
    root = Path(__file__).resolve().parents[2]
    files = [p.relative_to(root).as_posix() for p in code_files(root)]
    assert "backend/data/examples/recent-news-2026-10-25.json" in files
    assert "backend/app/main.py" not in files
    assert not any(
        p.endswith("/.env") or ".venv/" in p or "/companies/" in p for p in files
    )


def test_submission_requires_company_selection(tmp_path):
    folder = tmp_path / "companies"
    folder.mkdir()
    (folder / "selection.txt").write_text("same\n" * 50, encoding="utf-8")
    with pytest.raises(ValueError, match="50 distinct"):
        private_files(tmp_path)
