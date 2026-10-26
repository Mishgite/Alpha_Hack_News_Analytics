"""создаёт схему и загружает исходные данные перед первым запуском сервера"""

import hashlib
import json
import math
import os
import sys
from decimal import Decimal
from pathlib import Path

from sqlalchemy import text

from app.import_companies import (
    SELECTION_PATH,
    SOURCE_PATH,
    import_companies,
    prepare_companies,
)
from app.import_news import DEFAULT_FILE, import_bundle, read_bundle
from app.infrastructure.database.init_db import initialize_database
from app.infrastructure.database.session import get_engine
from app.services.news import NewsService
from app.services.reports import ReportService
from app.services.runtime import RuntimeService

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
BOOTSTRAP_KEY = "server_bootstrap_v1"


def local_data_version(reports_dir):
    """фиксирует исходные CSV, расшифровки и версии локальной обработки для повторного запуска"""
    from app.services.company_context import CONTEXT_VERSION, checksum
    from app.services.reports import IMPORT_VERSION

    files = [
        DATA_DIR / "companies" / name
        for name in (
            "df_Uid_data_hack.csv",
            "df_Fid_Uid_link_hack.csv",
            "df_Uid_payment_hack.csv",
        )
    ]
    files += sorted(reports_dir.glob("*/*.json"))
    value = {
        "context": CONTEXT_VERSION,
        "reports": IMPORT_VERSION,
        "files": {
            str(path.relative_to(DATA_DIR).as_posix()): checksum(path) for path in files
        },
    }
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def refresh_local_data(runtime, reports_dir, report_count):
    """обновляет локальные признаки и поиск при изменении данных без вызова модели"""
    from app.refresh_company_context import refresh

    version = local_data_version(reports_dir)
    previous = runtime.get("bootstrap_local_data")
    if previous and previous["value"].get("version") == version:
        return
    result = ReportService().import_directory(reports_dir)
    if result["errors"] or result["imported"] != report_count:
        raise ValueError("Some reports have no usable text or failed to import")
    updated = refresh(DATA_DIR / "companies")
    if local_data_version(reports_dir) != version:
        raise ValueError("Local data changed during bootstrap")
    runtime.save("bootstrap_local_data", {"version": version})
    print(
        f"Local data updated: {updated} company profiles, {report_count} reports",
        flush=True,
    )


def group_saved_news(runtime):
    """один раз группирует сохранённые новости после обновления алгоритма без платной разметки"""
    from app.infrastructure.news_matching import VERSION

    state = runtime.get("news_event_grouping")
    if state and state["value"].get("version") == VERSION:
        return
    count = NewsService().group_existing_news()
    runtime.save("news_event_grouping", {"version": VERSION, "checked": count})


def validate_reports(directory: Path) -> int:
    """проверяет подготовленный текст и оригиналы PDF до импорта и платных запросов"""
    manifests = sorted(directory.glob("*/manifest.json"))
    if not manifests:
        raise ValueError("Missing reports_processed/*/manifest.json")
    for path in manifests:
        manifest = json.loads(path.read_text(encoding="utf-8"))
        if not manifest.get("complete") or not manifest.get("pages"):
            raise ValueError(f"Incomplete report: {path.parent.name}")
        filename = manifest["source_file"]
        if Path(filename).name != filename or "\\" in filename:
            raise ValueError("Invalid PDF filename")
        original = DATA_DIR / "reports" / filename
        with original.open("rb") as source:
            actual = hashlib.file_digest(source, "sha256").hexdigest()
        if actual != manifest["source_sha256"]:
            raise ValueError(f"PDF checksum mismatch: {filename}")
        for page in manifest["pages"]:
            filename = page["json"]
            if Path(filename).name != filename or "\\" in filename:
                raise ValueError("Invalid page filename")
            json.loads((path.parent / filename).read_text(encoding="utf-8"))
    return len(manifests)


def bootstrap():
    """повторяет незавершённый импорт, готовые профили повторно не отправляет модели"""
    from app.services.ai_agents._common import settings, validate_configuration

    config = settings()
    for key in ("LLM_MODEL_CONTEXT", "LLM_MODEL_TAGGING", "LLM_MODEL_ANALYSIS"):
        validate_configuration(config, key)
    if not 1 <= int(config.get("LLM_DAILY_REQUEST_LIMIT", "100")) <= 10000:
        raise ValueError("Invalid LLM_DAILY_REQUEST_LIMIT")
    if not 1024 <= int(config.get("LLM_MAX_OUTPUT_TOKENS", "8192")) <= 16384:
        raise ValueError("Invalid LLM_MAX_OUTPUT_TOKENS")
    reserve = float(config.get("LLM_BUDGET_RESERVE_RUB", "360"))
    if not math.isfinite(reserve) or reserve < 0:
        raise ValueError("Invalid LLM_BUDGET_RESERVE_RUB")
    engine = get_engine()
    runtime = RuntimeService()
    reports_dir = DATA_DIR / "reports_processed"
    with engine.connect() as lock:
        acquired = lock.scalar(text("SELECT pg_try_advisory_lock(684720269)"))
        lock.commit()
        if not acquired:
            raise RuntimeError("Another bootstrap is running")
        try:
            initialize_database(engine)
            NewsService().sync_tag_catalog()
            examples = os.environ.get("BAD_NEWS_PATH")
            if examples and not Path(examples).exists():
                target = Path(examples)
                target.parent.mkdir(parents=True, exist_ok=True)
                with target.open("x", encoding="utf-8") as output_file:
                    output_file.write(
                        Path(__file__)
                        .with_name("bad_news.json")
                        .read_text(encoding="utf-8")
                    )
            report_count = validate_reports(reports_dir)
            state = runtime.get(BOOTSTRAP_KEY)
            if state and state["value"].get("status") == "ready":
                refresh_local_data(runtime, reports_dir, report_count)
                group_saved_news(runtime)
                print(
                    "Bootstrap already completed; existing data preserved", flush=True
                )
                return
            ids = [
                line.strip()
                for line in SELECTION_PATH.read_text(encoding="utf-8-sig").splitlines()
                if line.strip()
            ]
            if len(ids) != 50 or len(set(ids)) != 50:
                raise ValueError("selection.txt must contain 50 unique company IDs")
            read_bundle(DEFAULT_FILE)
            local_version = local_data_version(reports_dir)
            output = Path(
                os.environ.get("IMPORT_OUTPUT_DIR", str(DATA_DIR / "import_results"))
            )
            preview = import_companies(
                SOURCE_PATH,
                company_ids=ids,
                check_only=True,
                output_dir=output / "validation",
                min_revenue=Decimal(15000000000),
            )
            if preview["selected"] != 50:
                raise ValueError("Not all selected companies exist in the CSV")
            result = ReportService().import_directory(reports_dir)
            if result["errors"] or result["imported"] != report_count:
                raise ValueError("Some reports have no usable text or failed to import")
            news_ids = import_bundle(DEFAULT_FILE)
            companies = import_companies(
                SOURCE_PATH,
                company_ids=ids,
                output_dir=output / "companies",
                min_revenue=Decimal(15000000000),
                enrich_context=True,
            )
            prepare_companies(companies, retries=3)
            group_saved_news(runtime)
            if local_data_version(reports_dir) != local_version:
                raise ValueError("Local data changed during bootstrap")
            runtime.save("bootstrap_local_data", {"version": local_version})
            runtime.save(
                BOOTSTRAP_KEY,
                {
                    "status": "ready",
                    "companies": ids,
                    "news": len(news_ids),
                    "reports": report_count,
                },
            )
            print(
                f"Bootstrap complete: 50 companies, {len(news_ids)} news, {report_count} reports",
                flush=True,
            )
        finally:
            lock.execute(text("SELECT pg_advisory_unlock(684720269)"))
            lock.commit()


def main():
    """завершает запуск с ошибкой, если данные не удалось подготовить полностью"""
    try:
        mode = os.environ.get("BOOTSTRAP_MODE", "full")
        if mode == "demo":
            from app.seed_demo import seed_demo

            seed_demo()
        elif mode == "full":
            bootstrap()
        else:
            raise ValueError("BOOTSTRAP_MODE must be demo or full")
        return 0
    except (OSError, ValueError) as error:
        print(f"Bootstrap stopped: {error}", file=sys.stderr)
        return 1
    except Exception as error:  # noqa: BLE001
        print(
            f"Bootstrap stopped: {type(error).__name__}; check database, model settings and budget",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
