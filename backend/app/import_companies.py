"""загружает все компании из CSV или выбранное количество через сервис профилей"""

import argparse
import csv
import hashlib
import json
import re
import sys
import tempfile
from collections import Counter
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from uuid import uuid4

if __name__ == "__main__" and not __package__:
    # при запуске через Run пакет app ищется от папки backend
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from app.infrastructure.database.session import get_engine
from app.schemas.database import CompanyData
from app.services.profiles import ProfileService

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
SOURCE_PATH = DATA_DIR / "companies" / "df_Uid_data_hack.csv"
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
    limit: int | None = None,
    check_only: bool = False,
    service: ProfileService | None = None,
    output_dir: Path | None = None,
) -> dict:
    """проверяет весь CSV и добавляет выбранные профили порциями, записывая причины пропусков"""
    if limit is not None and (
        isinstance(limit, bool) or not isinstance(limit, int) or limit < 1
    ):
        raise ValueError("Количество компаний должно быть положительным целым числом")
    print("Проверка CSV:", source)
    checksum = file_hash(source)
    # проверяем повторы во всём файле, даже если для импорта выбраны только первые компании
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
                    if limit is None or result["selected"] < limit:
                        selected.write(company.model_dump_json() + "\n")
                        result["selected"] += 1
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


def choose_limit() -> int | None:
    """запрашивает режим в консоли PyCharm, пустой ввод не запускает полный импорт"""
    while True:
        choice = input(
            "1 - загрузить часть компаний\n2 - загрузить все компании\nРежим: "
        ).strip()
        if choice == "2":
            return None
        if choice == "1":
            while True:
                value = input("Количество компаний: ").strip()
                if value.isascii() and value.isdigit() and int(value) > 0:
                    return int(value)
                print("Нужно целое число больше нуля")
        print("Нужно выбрать 1 или 2")


def main() -> int:
    """запускает импорт через Run или параметры командной строки, не выводит пароль подключения"""
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--all", action="store_true", help="выбрать все подходящие компании"
    )
    mode.add_argument("--limit", type=int, help="выбрать первые N подходящих компаний")
    parser.add_argument(
        "--check", action="store_true", help="проверить CSV без подключения к БД"
    )
    parser.add_argument("--source", type=Path, default=SOURCE_PATH)
    args = parser.parse_args()
    try:
        limit = (
            None
            if args.all
            else args.limit
            if args.limit is not None
            else choose_limit()
        )
        if limit is not None and limit < 1:
            parser.error("--limit должен быть больше нуля")
        if not args.check:
            print("База:", get_engine().url.database)
        result = import_companies(args.source, limit=limit, check_only=args.check)
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


if __name__ == "__main__":
    raise SystemExit(main())
