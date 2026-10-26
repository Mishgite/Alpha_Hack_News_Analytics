"""проверяет настройки контейнеров и повторную подготовку данных без платных запросов"""

import hashlib
import json
from unittest.mock import MagicMock, Mock
from urllib.error import HTTPError

import pytest
from sqlalchemy.engine import make_url

from app import bootstrap, container


@pytest.fixture(autouse=True)
def preserve_container_environment(monkeypatch):
    import os

    for name in ("DATABASE_URL", "API_CORS_ORIGINS"):
        monkeypatch.setenv(name, os.environ.get(name, ""))


def test_connection_password_roundtrip(monkeypatch):
    password = "@/%:#$ spaces пароль"
    for key, value in {
        "POSTGRES_USER": "postgres",
        "POSTGRES_PASSWORD": password,
        "POSTGRES_DB": "news",
        "FRONTEND_ORIGIN": "https://front.example/",
    }.items():
        monkeypatch.setenv(key, value)
    container.configure_environment()
    import os

    assert make_url(os.environ["DATABASE_URL"]).password == password
    assert json.loads(os.environ["API_CORS_ORIGINS"]) == ["https://front.example"]


@pytest.mark.parametrize(
    "origin",
    [
        "*",
        "https://front.test/repository",
        "https://user:pass@front.test",
        "https://front.test?q=1",
    ],
)
def test_invalid_origin(monkeypatch, origin):
    for key in ("POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB"):
        monkeypatch.setenv(key, "test")
    monkeypatch.setenv("FRONTEND_ORIGIN", origin)
    with pytest.raises(ValueError, match="FRONTEND_ORIGIN"):
        container.configure_environment()


def test_reports_require_matching_pdf_and_pages(tmp_path, monkeypatch):
    monkeypatch.setattr(bootstrap, "DATA_DIR", tmp_path)
    report = tmp_path / "reports" / "example.pdf"
    report.parent.mkdir()
    report.write_bytes(b"original PDF")
    folder = tmp_path / "reports_processed" / "example"
    folder.mkdir(parents=True)
    (folder / "page.json").write_text('{"blocks": []}', encoding="utf-8")
    manifest = {
        "complete": True,
        "source_file": report.name,
        "source_sha256": hashlib.sha256(report.read_bytes()).hexdigest(),
        "pages": [{"json": "page.json"}],
    }
    (folder / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    assert bootstrap.validate_reports(folder.parent) == 1
    report.write_bytes(b"different PDF")
    with pytest.raises(ValueError, match="checksum"):
        bootstrap.validate_reports(folder.parent)


def test_empty_reports_rejected(tmp_path):
    with pytest.raises(ValueError, match="Missing reports"):
        bootstrap.validate_reports(tmp_path)


@pytest.fixture
def bootstrap_dependencies(monkeypatch, tmp_path):
    engine = MagicMock()
    lock = engine.connect.return_value.__enter__.return_value
    lock.scalar.return_value = True
    runtime = Mock()
    runtime.get.return_value = None
    monkeypatch.setattr(bootstrap, "get_engine", lambda: engine)
    monkeypatch.setattr(bootstrap, "RuntimeService", lambda: runtime)
    monkeypatch.setattr(bootstrap, "initialize_database", Mock())
    monkeypatch.setattr(bootstrap, "NewsService", Mock())
    monkeypatch.setattr(bootstrap, "validate_reports", Mock(return_value=9))
    monkeypatch.setattr(
        bootstrap,
        "ReportService",
        Mock(
            return_value=Mock(
                import_directory=Mock(return_value={"imported": 9, "errors": []})
            )
        ),
    )
    monkeypatch.setattr(bootstrap, "read_bundle", Mock())
    monkeypatch.setattr(bootstrap, "import_bundle", Mock(return_value=["news"]))
    monkeypatch.setattr(
        bootstrap, "import_companies", Mock(return_value={"selected": 50})
    )
    monkeypatch.setattr(bootstrap, "prepare_companies", Mock())
    monkeypatch.setattr(bootstrap, "local_data_version", Mock(return_value="data-v1"))
    monkeypatch.setattr(bootstrap, "refresh_local_data", Mock())
    from app.services.ai_agents import _common

    monkeypatch.setattr(_common, "validate_configuration", Mock())
    monkeypatch.delenv("BAD_NEWS_PATH", raising=False)
    selection = tmp_path / "selection.txt"
    selection.write_text("\n".join(f"U_{i}" for i in range(50)), encoding="utf-8")
    monkeypatch.setattr(bootstrap, "SELECTION_PATH", selection)
    return runtime, lock


def test_ready_database_skips_import_and_model(bootstrap_dependencies):
    runtime, lock = bootstrap_dependencies
    runtime.get.side_effect = lambda key: (
        {"value": {"status": "ready"}}
        if key == bootstrap.BOOTSTRAP_KEY
        else {"value": {"version": "local-events-v1"}}
    )
    bootstrap.bootstrap()
    bootstrap.import_companies.assert_not_called()
    bootstrap.import_bundle.assert_not_called()
    bootstrap.prepare_companies.assert_not_called()
    bootstrap.refresh_local_data.assert_called_once()
    runtime.save.assert_not_called()
    assert lock.execute.called


def test_first_boot_marks_ready_after_success(bootstrap_dependencies):
    runtime, _ = bootstrap_dependencies
    bootstrap.bootstrap()
    bootstrap.prepare_companies.assert_called_once()
    assert runtime.save.call_args.args[1]["status"] == "ready"


def test_failed_tagging_does_not_publish_ready_and_can_resume(bootstrap_dependencies):
    runtime, lock = bootstrap_dependencies
    bootstrap.prepare_companies.side_effect = RuntimeError("model unavailable")
    with pytest.raises(RuntimeError):
        bootstrap.bootstrap()
    runtime.save.assert_not_called()
    assert lock.execute.called
    bootstrap.prepare_companies.side_effect = None
    bootstrap.bootstrap()
    assert runtime.save.call_args.args[1]["status"] == "ready"


def test_failed_reports_do_not_start_paid_tagging(bootstrap_dependencies):
    runtime, _ = bootstrap_dependencies
    bootstrap.ReportService.return_value.import_directory.return_value = {
        "imported": 8,
        "errors": [],
    }
    with pytest.raises(ValueError, match="reports"):
        bootstrap.bootstrap()
    bootstrap.prepare_companies.assert_not_called()
    runtime.save.assert_not_called()


def test_concurrent_bootstrap_does_not_import(bootstrap_dependencies):
    _, lock = bootstrap_dependencies
    lock.scalar.return_value = False
    with pytest.raises(RuntimeError, match="Another bootstrap"):
        bootstrap.bootstrap()
    bootstrap.import_companies.assert_not_called()


def test_existing_database_refreshes_changed_data_once(monkeypatch, tmp_path):
    from app import refresh_company_context

    runtime = Mock()
    runtime.get.return_value = {"value": {"version": "old"}}
    monkeypatch.setattr(bootstrap, "local_data_version", Mock(return_value="new"))
    importer = Mock(return_value={"imported": 9, "errors": []})
    monkeypatch.setattr(
        bootstrap, "ReportService", lambda: Mock(import_directory=importer)
    )
    refresh = Mock(return_value=50)
    monkeypatch.setattr(refresh_company_context, "refresh", refresh)
    bootstrap.refresh_local_data(runtime, tmp_path, 9)
    runtime.save.assert_called_once_with("bootstrap_local_data", {"version": "new"})
    runtime.get.return_value = {"value": {"version": "new"}}
    bootstrap.refresh_local_data(runtime, tmp_path, 9)
    refresh.assert_called_once()
    importer.assert_called_once()


def test_failed_local_refresh_does_not_mark_data_ready(monkeypatch, tmp_path):
    runtime = Mock()
    runtime.get.return_value = None
    monkeypatch.setattr(bootstrap, "local_data_version", Mock(return_value="new"))
    monkeypatch.setattr(
        bootstrap,
        "ReportService",
        lambda: Mock(import_directory=Mock(return_value={"imported": 0, "errors": []})),
    )
    with pytest.raises(ValueError, match="reports"):
        bootstrap.refresh_local_data(runtime, tmp_path, 9)
    runtime.save.assert_not_called()


@pytest.mark.parametrize("status, expected_calls", [(429, 2), (503, 2), (401, 1)])
def test_company_retries_only_temporary_gateway_errors(
    monkeypatch, tmp_path, status, expected_calls
):
    from app import import_companies
    from app.services.ai_agents import _common

    monkeypatch.setattr(_common, "settings", lambda: {"LLM_MODEL_CONTEXT": "test"})
    monkeypatch.setattr(_common, "validate_configuration", Mock())
    delay = Mock()
    monkeypatch.setattr(import_companies.time, "sleep", delay)
    error = RuntimeError("gateway request failed")
    error.__cause__ = HTTPError("https://gateway.test", status, "unavailable", {}, None)
    pipeline = Mock()
    pipeline.prepare_company.side_effect = [error, True]
    result = {
        "report_dir": str(tmp_path),
        "company_ids": ["U_1"],
        "selected": 1,
        "sha256": "test",
    }
    if status == 401:
        with pytest.raises(RuntimeError):
            import_companies.prepare_companies(
                result, pipeline=pipeline, runtime=Mock(), retries=3
            )
        delay.assert_not_called()
    else:
        import_companies.prepare_companies(
            result, pipeline=pipeline, runtime=Mock(), retries=3
        )
        assert result["status"] == "completed"
        delay.assert_called_once_with(15)
    assert pipeline.prepare_company.call_count == expected_calls
