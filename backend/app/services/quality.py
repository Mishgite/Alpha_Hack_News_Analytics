"""оценка полезности и техническое состояние без платных запросов"""

import json
from datetime import UTC, datetime
from math import ceil
from pathlib import Path

from app.infrastructure.database.uow import UnitOfWork


class QualityService:
    """паттерн Service Layer: проверяет доступ к оценкам и рассчитывает показатели мониторинга"""

    def __init__(self, *, uow_factory=UnitOfWork):
        self._uow = uow_factory

    def feedback(self, user_id, analysis_id, useful=None, *, write=False):
        """читает или обновляет личную оценку только для доступного пользователю разбора"""
        if write and not isinstance(useful, bool):
            raise ValueError("A boolean usefulness rating is required")
        with self._uow() as db:
            db.analyses.get_for_user(user_id, analysis_id)
            result = db.quality.feedback(user_id, analysis_id, useful, write=write)
            if write:
                db.commit()
            return {"useful": result}

    def snapshot(self, *, persist=False):
        """собирает показатели, пороговые предупреждения и при необходимости сохраняет снимок"""
        from app.services.ai_agents._common import settings

        with self._uow() as db:
            result = db.quality.snapshot()
            heartbeat = db.runtime.get("worker")
            result["budget"] = (db.runtime.get("llm_budget") or {}).get("value")
            result["worker_alive"] = bool(
                heartbeat
                and heartbeat["value"].get("status") == "running"
                and (datetime.now(UTC) - heartbeat["updated_at"]).total_seconds() < 60
            )
            alerts = []
            result["llm_request_limit"] = int(
                settings().get("LLM_DAILY_REQUEST_LIMIT", "100")
            )
            if sum(result["llm_calls_today"].values()) >= result["llm_request_limit"]:
                alerts.append("llm_daily_request_limit")
            if result["budget"] and result["budget"].get(
                "remaining", float("inf")
            ) <= result["budget"].get("reserve", 0):
                alerts.append("llm_budget_reserve")
            if not result["worker_alive"]:
                alerts.append("worker_unavailable")
            if (
                not result["newest_ready_news"]
                or (
                    datetime.now(UTC)
                    - datetime.fromisoformat(result["newest_ready_news"])
                ).total_seconds()
                > 72 * 3600
            ):
                alerts.append("news_older_than_72h")
            for name, operation in result["operations"].items():
                samples = operation.get("samples", [])
                durations = sorted(sample["seconds"] for sample in samples)
                operation["p95_seconds"] = (
                    durations[ceil(len(durations) * 0.95) - 1] if durations else None
                )
                operation["sample_count"] = len(samples)
                operation["error_rate"] = (
                    sum(not s["success"] for s in samples) / len(samples)
                    if samples
                    else None
                )
                if len(samples) >= 3 and all(not s["success"] for s in samples[-3:]):
                    alerts.append(name + ":three_failures")
                operation.pop("samples", None)
            result["alerts"] = alerts
            quality = db.runtime.get("quality_check")
            result["quality"] = quality["value"] if quality else None
            if (
                not quality
                or (datetime.now(UTC) - quality["updated_at"]).total_seconds()
                > 26 * 3600
            ):
                alerts.append("quality_check_overdue")
            if quality and not quality["value"].get("passed", False):
                alerts.append("quality_check_failed")
            if persist:
                db.runtime.save("monitoring", result)
                db.commit()
            return result

    def evaluate(self):
        """проверяет случаи и корпус, сохраняет историю и сбои без текстов документов"""
        from app.evaluate import (
            database_checks,
            failed_checks,
            fingerprint,
            offline,
            source_version,
        )

        result = {
            "checked_at": datetime.now(UTC).isoformat(),
            "passed": False,
            "errors": [],
        }
        try:
            result["source_hash"] = source_version()
            cases = json.loads(
                (
                    Path(__file__).resolve().parents[1] / "evaluation_cases.json"
                ).read_text(encoding="utf-8")
            )
            result["cases_hash"] = fingerprint(cases)
            corpus, actual, _ = database_checks(cases, uow_factory=self._uow)
            regression = offline(cases)
            result.update(
                corpus=corpus,
                errors=failed_checks(regression, actual),
                metrics={
                    k: v
                    for k, v in actual.items()
                    if k not in {"analyses", "retrieval"}
                },
                synthetic={
                    k: v
                    for k, v in regression.items()
                    if k not in {"cases", "duplicate_cases"}
                },
            )
            result["passed"] = not result["errors"]
        except Exception as error:  # noqa: BLE001
            # сообщение исключения может содержать SQL или данные источника, сохраняется только тип
            result["errors"] = ["evaluation_error:" + type(error).__name__]
        with self._uow() as db:
            db.runtime.record_quality_check(result)
            db.commit()
        return result
