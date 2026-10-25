"""загружает 50 компаний разных отраслей из CSV и получает темы профилей через модель"""

import argparse
import csv
import hashlib
import json
import os
import re
import sys
import tempfile
from collections import Counter, defaultdict
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from uuid import uuid4

if __name__ == "__main__" and not __package__:
    # при запуске через Run пакет app ищется от папки backend
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from filelock import FileLock
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from app.infrastructure.database.session import get_engine
from app.schemas.database import CompanyData
from app.services.profiles import ProfileService

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
SOURCE_PATH = DATA_DIR / "companies" / "df_Uid_data_hack.csv"
SELECTION_PATH = DATA_DIR / "companies" / "selection.txt"
BATCH_SIZE = 100
COLUMNS = (
    "SYNTHETIC_U",
    "ORG_TYPE",
    "OKFS_NAME",
    "COMPANY_AGE_YEARS_GRADATION",
    "ECO_MARK_LABEL",
    "MAINOKVED_CODE",
    "MAINOKVED_NAME",
    "NEGATIVEMARK",
    "AMOUNT_WORKERS_FNS_GRADATION",
    "AMOUNT_WORKERS_SPARK_GRADATION",
    "CL_TYPE",
    "CL_PRODUCT_RKO_MARK",
    "CL_PRODUCT_GAR_MARK",
    "CL_PRODUCT_LOA_MARK",
    "CL_PRODUCT_LEA_MARK",
    "CL_PRODUCT_DEP_MARK",
    "CL_PRODUCT_ZPP_MARK",
    "FTS_FLAG",
    "FTS_COUNTRY_NAME",
    "FACTORING_MARK",
    "REVENUE_COMPANY",
    "GROUP_ID",
    "CITY",
    "REGION",
)
FLAGS = (
    "NEGATIVEMARK",
    "FTS_FLAG",
    "FACTORING_MARK",
    *(c for c in COLUMNS if c.startswith("CL_PRODUCT_")),
)


def file_hash(path: Path) -> str:
    """считает контрольную сумму CSV без чтения всего файла в память"""
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def read_rows(path: Path):
    """читает CSV построчно, проверяет обязательные колонки и сохраняет номер записи"""
    with path.open(encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source, delimiter=";")
        fields = reader.fieldnames or []
        missing = set(COLUMNS) - set(fields)
        if missing or len(fields) != len(set(fields)):
            raise ValueError("Неверные колонки CSV: " + ", ".join(sorted(missing)))
        yield from enumerate(reader, start=2)


def build_company(
    row: dict, *, filename: str, checksum: str, number: int
) -> CompanyData:
    """переносит исходные признаки в профиль, сохраняя неизвестные значения и происхождение"""
    if None in row or any(value is None for value in row.values()):
        raise ValueError("Количество полей строки не совпадает с заголовком")
    values = {key: value.strip() or None for key, value in row.items()}
    if any(
        "\x00" in key or (value is not None and "\x00" in value)
        for key, value in values.items()
    ):
        raise ValueError(
            "Строка содержит нулевой байт, который нельзя сохранить в PostgreSQL"
        )
    if not re.fullmatch(r"U_\d+", values["SYNTHETIC_U"] or ""):
        raise ValueError("Неверный ID компании")
    for flag in FLAGS:
        if values[flag] not in (None, "0", "1", "0.0", "1.0"):
            raise ValueError(f"Неверный флаг {flag}")
    revenue = None
    if values["REVENUE_COMPANY"] is not None:
        try:
            revenue = Decimal(values["REVENUE_COMPANY"])
        except InvalidOperation:
            raise ValueError("Выручка не является числом") from None
        if not revenue.is_finite() or revenue < 0 or revenue >= Decimal("1e22"):
            raise ValueError("Выручка вне допустимого диапазона")
        if revenue != revenue.quantize(Decimal("0.01")):
            raise ValueError(
                "Выручка содержит больше двух значащих знаков после запятой"
            )
    version = hashlib.sha256(
        json.dumps(values, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return CompanyData(
        id=values["SYNTHETIC_U"],
        profile_version=f"hackathon-csv-v1:{version}",
        okved_code=values["MAINOKVED_CODE"],
        okved_name=values["MAINOKVED_NAME"],
        industry=values["MAINOKVED_NAME"],
        city=values["CITY"],
        region=values["REGION"],
        revenue=revenue,
        group_id=values["GROUP_ID"],
        profile_json={
            **values,
            "_source": {
                "file": filename,
                "sha256": checksum,
                "record": number,
                "mapping_version": 1,
            },
        },
    )


def import_companies(
    source: Path = SOURCE_PATH,
    *,
    limit: int | None = 50,
    check_only: bool = False,
    service: ProfileService | None = None,
    output_dir: Path | None = None,
    company_ids: list[str] | None = None,
) -> dict:
    """проверяет весь CSV и добавляет выбранные профили порциями, записывая причины пропусков"""
    if limit is not None and (
        isinstance(limit, bool) or not isinstance(limit, int) or limit < 1
    ):
        raise ValueError("Количество компаний должно быть положительным целым числом")
    if company_ids is not None:
        if (
            not company_ids
            or len(set(company_ids)) != len(company_ids)
            or any(not re.fullmatch(r"U_\d+", item) for item in company_ids)
        ):
            raise ValueError("Список выбора должен содержать уникальные ID вида U_123")
        if limit != len(company_ids):
            raise ValueError("Количество ID в списке не совпадает с --limit")
    requested = set(company_ids) if company_ids is not None else None
    print("Проверка CSV:", source)
    checksum = file_hash(source)
    # исключаем все строки с повторным ID, даже если они находятся за пределами выборки
    counts = Counter(
        (row.get("SYNTHETIC_U") or "").strip() for _, row in read_rows(source)
    )
    repeated = {key for key, count in counts.items() if count > 1}
    output_dir = output_dir or DATA_DIR / "import_results" / (
        datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid4().hex[:8]
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    print("Отчёт:", output_dir.resolve())
    result = {
        "source": str(source.resolve()),
        "sha256": checksum,
        "limit": limit,
        "check_only": check_only,
        "status": "validating",
        "rows": 0,
        "valid": 0,
        "rejected": 0,
        "selected": 0,
        "created": 0,
        "already_exists": 0,
        "company_ids": [],
        "repeated_ids": sorted(repeated),
        "report_dir": str(output_dir.resolve()),
    }

    def save_result():
        """обновляет итог после каждой сохранённой порции и при завершении с ошибкой"""
        (output_dir / "summary.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    try:
        # проверенная выборка хранится на диске, запись в БД начинается только после проверки файла
        with tempfile.TemporaryFile(
            mode="w+t", encoding="utf-8", dir=output_dir
        ) as selected:
            candidates = defaultdict(list)
            candidate_keys = defaultdict(Counter)
            with (output_dir / "rejected.csv").open(
                "w", encoding="utf-8-sig", newline=""
            ) as rejected:
                writer = csv.writer(rejected, delimiter=";")
                writer.writerow(["record", "reason", "raw_row_json"])
                for number, row in read_rows(source):
                    result["rows"] += 1
                    company_id = (row.get("SYNTHETIC_U") or "").strip()
                    try:
                        if company_id in repeated:
                            raise ValueError(
                                "Повторяющийся ID в CSV, все строки с этим ID исключены"
                            )
                        company = build_company(
                            row, filename=source.name, checksum=checksum, number=number
                        )
                    except (ValueError, InvalidOperation) as error:
                        result["rejected"] += 1
                        writer.writerow(
                            [number, str(error), json.dumps(row, ensure_ascii=False)]
                        )
                        continue
                    result["valid"] += 1
                    if requested is not None:
                        if company.id in requested:
                            selected.write(company.model_dump_json() + "\n")
                            result["company_ids"].append(company.id)
                            result["selected"] += 1
                    elif limit is None:
                        selected.write(company.model_dump_json() + "\n")
                        result["selected"] += 1
                    else:
                        sector = (company.okved_code or "").split(".")[0] or "unknown"
                        key = (company.region, company.okved_code)
                        if len(candidates[sector]) < limit:
                            candidates[sector].append(company)
                            candidate_keys[sector][key] += 1
                        elif key not in candidate_keys[sector]:
                            pool = candidates[sector]
                            for index, previous in enumerate(pool):
                                previous_key = (previous.region, previous.okved_code)
                                if candidate_keys[sector][previous_key] > 1:
                                    candidate_keys[sector][previous_key] -= 1
                                    pool[index] = company
                                    candidate_keys[sector][key] += 1
                                    break
            if requested is not None:
                missing = requested - set(result["company_ids"])
                if missing:
                    raise ValueError(
                        "В CSV отсутствуют корректные записи: "
                        + ", ".join(sorted(missing))
                    )
                result["company_ids"] = company_ids
            elif limit is not None:
                regions = set()
                while result["selected"] < limit and any(candidates.values()):
                    for sector in sorted(candidates):
                        pool = candidates[sector]
                        if not pool or result["selected"] == limit:
                            continue
                        index = next(
                            (
                                i
                                for i, item in enumerate(pool)
                                if item.region and item.region not in regions
                            ),
                            0,
                        )
                        company = pool.pop(index)
                        regions.add(company.region)
                        selected.write(company.model_dump_json() + "\n")
                        result["company_ids"].append(company.id)
                        result["selected"] += 1
                if result["selected"] < limit:
                    raise ValueError(
                        f"В CSV недостаточно разных компаний: {result['selected']} из {limit}"
                    )
            if file_hash(source) != checksum:
                raise ValueError("CSV изменился во время проверки, импорт отменён")
            print(
                f"Подходящих компаний: {result['valid']}; отклонено строк: {result['rejected']}"
            )
            print(f"Выбрано: {result['selected']}")
            if check_only:
                result["status"] = "checked"
            else:
                service = service if service is not None else ProfileService()
                result["status"] = "importing"
                selected.seek(0)
                batch = []
                for line in selected:
                    batch.append(CompanyData.model_validate_json(line))
                    if len(batch) == BATCH_SIZE:
                        created = service.create_companies(batch)
                        result["created"] += len(created)
                        result["already_exists"] += len(batch) - len(created)
                        save_result()
                        print(
                            f"Обработано: {result['created'] + result['already_exists']}/{result['selected']}",
                            flush=True,
                        )
                        batch.clear()
                if batch:
                    created = service.create_companies(batch)
                    result["created"] += len(created)
                    result["already_exists"] += len(batch) - len(created)
                result["status"] = "completed"
        save_result()
        return result
    except BaseException:
        result["status"] = "interrupted"
        save_result()
        raise


def save_selection(company_ids: list[str], path: Path) -> None:
    """сохраняет выбранные ID до платных запросов, не оставляет частично записанный список"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with FileLock(str(path) + ".lock", timeout=1):
        if path.exists():
            existing = [
                line.strip()
                for line in path.read_text(encoding="utf-8-sig").splitlines()
                if line.strip()
            ]
            if existing != company_ids:
                raise ValueError(
                    "Выборку уже изменил другой процесс, повторите запуск с сохранённым списком ID"
                )
            return
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=path.parent, delete=False
            ) as output:
                temporary = Path(output.name)
                output.write("\n".join(company_ids) + "\n")
                output.flush()
                os.fsync(output.fileno())
            temporary.replace(path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)


def prepare_companies(result: dict, *, pipeline=None, runtime=None) -> dict:
    """получает темы выбранных компаний и публикует выборку после успешной разметки всех профилей"""
    from app.services.ai_agents._common import settings, validate_configuration
    from app.services.profile_pipeline import TAGGING_VERSION, ProfilePipeline
    from app.services.runtime import RuntimeService

    config = settings()
    validate_configuration(config, "LLM_MODEL_CONTEXT")
    version = TAGGING_VERSION + config["LLM_MODEL_CONTEXT"]
    pipeline = pipeline if pipeline is not None else ProfilePipeline()
    runtime = runtime if runtime is not None else RuntimeService()
    result.update(status="tagging", tagged=0, ready=0)
    result.pop("error", None)
    summary = Path(result["report_dir"]) / "summary.json"
    try:
        for index, company_id in enumerate(result["company_ids"], 1):
            result["current_company"] = company_id
            changed = pipeline.prepare_company(company_id, version)
            result["tagged" if changed else "ready"] += 1
            summary.write_text(
                json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            print(
                f"Профили: {index}/{result['selected']}; {company_id}; {'размечен' if changed else 'уже готов'}",
                flush=True,
            )
        runtime.save(
            "demo_companies",
            {"ids": result["company_ids"][:50], "source_sha256": result["sha256"]},
        )
        result["status"] = "completed"
        result.pop("current_company", None)
        return result
    except BaseException as error:
        result.update(status="interrupted", error=type(error).__name__)
        raise
    finally:
        summary.write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )


def main() -> int:
    """запускает импорт через Run или параметры командной строки, не выводит пароль подключения"""
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--all", action="store_true", help="выбрать все подходящие компании"
    )
    mode.add_argument(
        "--limit",
        type=int,
        default=50,
        help="количество компаний разных отраслей, по умолчанию 50",
    )
    parser.add_argument(
        "--skip-tagging",
        action="store_true",
        help="только CSV, без вызова модели и смены выборки в интерфейсе",
    )
    parser.add_argument(
        "--check", action="store_true", help="проверить CSV без подключения к БД"
    )
    parser.add_argument("--source", type=Path, default=SOURCE_PATH)
    parser.add_argument(
        "--ids", type=Path, help="файл с ID выбранных компаний, по одному в строке"
    )
    args = parser.parse_args()
    try:
        limit = None if args.all else args.limit
        if args.all and not (args.skip_tagging or args.check):
            parser.error(
                "--all требует --skip-tagging: массовый импорт не запускает платную разметку всего датасета"
            )
        if limit is not None and limit < 1:
            parser.error("--limit должен быть больше нуля")
        if not args.check:
            print("База:", get_engine().url.database)
            if not args.skip_tagging:
                from app.services.ai_agents._common import (
                    settings,
                    validate_configuration,
                )

                validate_configuration(settings(), "LLM_MODEL_CONTEXT")
        selection = args.ids or (
            SELECTION_PATH if SELECTION_PATH.exists() and limit == 50 else None
        )
        ids = (
            [
                line.strip()
                for line in selection.read_text(encoding="utf-8-sig").splitlines()
                if line.strip()
            ]
            if selection
            else None
        )
        result = import_companies(
            args.source, limit=limit, check_only=args.check, company_ids=ids
        )
        if not args.check and not args.skip_tagging:
            if limit == 50 and not selection:
                save_selection(result["company_ids"], SELECTION_PATH)
            prepare_companies(result)
        print(
            f"Добавлено: {result['created']}; уже существовали: {result['already_exists']}"
        )
        print("Отчёт:", result["report_dir"])
        return 0
    except (KeyboardInterrupt, EOFError):
        print("Запуск прерван, уже сохранённые порции остаются в БД")
        return 1
    except ValidationError:
        print(
            "Ошибка настроек или структуры данных, проверьте app/.env и CSV",
            file=sys.stderr,
        )
        return 1
    except SQLAlchemyError:
        print(
            "Ошибка PostgreSQL, проверьте подключение и создание таблиц через init_db.py",
            file=sys.stderr,
        )
        return 1
    except (OSError, ValueError, csv.Error) as error:
        print(str(error), file=sys.stderr)
        return 1
    except Exception as error:  # noqa: BLE001
        # сообщение сторонней библиотеки может содержать ключ или запрос, выводим только тип ошибки
        print(
            f"Импорт остановлен: {type(error).__name__}. Проверьте настройки модели, лимиты и доступность API, затем повторите запуск",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
