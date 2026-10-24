"""Ingest the supplied financial reports and tables into the report-search tables.

PDF pages are stored as searchable text chunks. CSV/XLSX input is reduced to
aggregated numeric statistics; raw rows and synthetic customer identifiers are
never copied to the database. Source files are removed only after all imports
have committed; pass ``--keep-files`` to retain them.

Text PDFs use ``pymupdf`` or ``pypdf`` when available. Scanned PDFs use macOS
Vision on this machine, or PyMuPDF plus the Tesseract CLI with Russian/English
language data on other operating systems.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import re
import shutil
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Sequence


HERE = Path(__file__).resolve().parent
DEFAULT_INPUT_DIR = HERE / "data"
SUPPORTED_SUFFIXES = {".pdf", ".csv", ".xlsx", ".xlsm"}
MAX_CHUNK_CHARS = 2200
METRIC_NAME = re.compile(
    r"amount|sum|amt|pay|count|cnt|worker|age|sales|volume|revenue|income|profit|"
    r"balance|turnover|cost|price|quantity|qty|payment|debit|credit|rate|percent|"
    r"share|score|mark|руб|плат|сумм|колич|числ|штат|возраст|доход|расход|"
    r"выруч|прибыл|баланс|оборот|цен|ставк|дол|рубл|коэфф|платеж|платёж",
    re.IGNORECASE,
)
IDENTIFIER_NAME = re.compile(
    r"(^|[^a-zа-я])(id|uid|fid|inn|ogrn|account|beneficiary|payer|customer|"
    r"client|user|hash|key|identifier|ид|инн|огрн)([^a-zа-я]|$)",
    re.IGNORECASE,
)
DRIVE_URLS = {
    "df_Fid_Uid_link_hack.csv": "https://drive.google.com/file/d/1ZJCiqgY1ma4iQ1_ltabtUuaFIBkrqnOe/view",
    "df_Uid_data_hack.csv": "https://drive.google.com/file/d/12H7sbLwBcpur0fKaGHPqwPwfXfgQq10b/view",
    "df_Uid_payment_hack.csv": "https://drive.google.com/file/d/1zkvWkAS0kZqijD-og_0Cv3o01SoUMY_Z/view",
    "Бонд_Бриф_14092026.pdf": "https://drive.google.com/file/d/1bPzix_332N2CyMY0tqCHuYtGsfJWnFGv/view",
    "ALFA_Russian_Steels_1К21PreviewUpdate_15Apr2021.pdf": "https://drive.google.com/file/d/1yLCBrIoyIsubLTEBvBHh6io48ysnW-wn/view",
    "ALFA-7M26.pdf": "https://drive.google.com/file/d/1HZDq3WGRFdzgm1TZ5hWL23Q3I9c2Eq64/view",
    "ALFA-consumption.pdf": "https://drive.google.com/file/d/1riR1lhsb6EY1MwGMxdBlS_tI5ed9mIiz/view",
    "ALFA-Macro_Insights-Policy_Rate_11Sep.pdf": "https://drive.google.com/file/d/1shHG89LtMgHT1_uEebHmQSFZe_zbeq7-/view",
    "ALFA-macro_stat1H26.pdf": "https://drive.google.com/file/d/1khcHwoS0FkG9p_0J4XoHGaGq3B4V0ime/view",
    "FI_Strategy_3Q26_22072026.pdf": "https://drive.google.com/file/d/1hq3Fhyz9ce_sRyGUQB1MdoHeQdfAJfhK/view",
    "Gold_digest_August26.pdf": "https://drive.google.com/file/d/1a7TXOCHARfKzUR0hn9Cm9gQSrIldxTDE/view",
    "Inflation_tracker_02.pdf": "https://drive.google.com/file/d/19iW3Ph8_wO0HHQY7Ik4lTfC3jRc9gjWV/view",
}


@dataclass(frozen=True)
class TextChunk:
    page_num: int
    chunk_no: int
    text: str
    source_span: dict


@dataclass(frozen=True)
class ParsedDocument:
    title: str
    chunks: list[TextChunk]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def split_text(text: str, max_chars: int = MAX_CHUNK_CHARS) -> list[str]:
    """Split text without dropping characters, preferring paragraph/sentence edges."""
    clean = re.sub(r"[\t\r\f\v ]+", " ", text)
    clean = re.sub(r"\n\s*\n+", "\n\n", clean).strip()
    if not clean:
        return []

    result: list[str] = []
    while len(clean) > max_chars:
        boundary = clean.rfind("\n", 0, max_chars)
        if boundary < max_chars // 2:
            boundary = clean.rfind(". ", 0, max_chars)
            if boundary >= max_chars // 2:
                boundary += 1
        if boundary < max_chars // 2:
            boundary = clean.rfind(" ", 0, max_chars)
        if boundary < 1:
            boundary = max_chars
        result.append(clean[:boundary].strip())
        clean = clean[boundary:].strip()
    if clean:
        result.append(clean)
    return result


def read_pdf(path: Path) -> ParsedDocument:
    pages: list[tuple[int, str]] = []
    try:
        import fitz  # type: ignore[import-not-found]

        with fitz.open(path) as document:
            pages = [(number, page.get_text("text")) for number, page in enumerate(document, 1)]
    except ImportError:
        try:
            from pypdf import PdfReader  # type: ignore[import-not-found]

            reader = PdfReader(str(path))
            pages = [(number, page.extract_text() or "") for number, page in enumerate(reader.pages, 1)]
        except ImportError:
            ocr_pages = _ocr_pdf(path)
            pages = sorted(ocr_pages.items())

    if any(not text.strip() for _, text in pages):
        ocr_pages = _ocr_pdf(path)
        pages = [
            (page_no, text if text.strip() else ocr_pages.get(page_no, ""))
            for page_no, text in pages
        ]

    chunks = [
        TextChunk(page_num=page_no, chunk_no=index, text=chunk, source_span={"page": page_no})
        for page_no, page_text in pages
        for index, chunk in enumerate(split_text(page_text))
    ]
    if not chunks:
        raise ValueError(f"В {path.name} не удалось извлечь текст (возможно, PDF состоит из сканов).")
    return ParsedDocument(title=path.stem, chunks=chunks)


def _ocr_pdf(path: Path) -> dict[int, str]:
    if sys.platform == "darwin" and shutil.which("swift"):
        return _ocr_pdf_with_vision(path)
    return _ocr_pdf_with_tesseract(path)


def _ocr_pdf_with_tesseract(path: Path) -> dict[int, str]:
    tesseract = shutil.which("tesseract")
    if not tesseract:
        raise RuntimeError(
            f"{path.name} — сканированный PDF. Установите PyMuPDF и Tesseract CLI "
            "с языковыми данными rus+eng."
        )
    try:
        import fitz  # type: ignore[import-not-found]
    except ImportError as exc:
        raise RuntimeError("Для OCR через Tesseract дополнительно установите PyMuPDF.") from exc

    result: dict[int, str] = {}
    with fitz.open(path) as document:
        for page_no, page in enumerate(document, 1):
            image = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False).tobytes("png")
            process = subprocess.run(
                [tesseract, "stdin", "stdout", "-l", "rus+eng", "--psm", "3"],
                input=image,
                capture_output=True,
                timeout=180,
                check=False,
            )
            if process.returncode:
                details = process.stderr.decode("utf-8", errors="replace").strip().splitlines()
                message = details[-1] if details else "ошибка Tesseract"
                raise RuntimeError(f"OCR страницы {page_no} в {path.name}: {message}")
            result[page_no] = process.stdout.decode("utf-8", errors="replace").strip()
    return result


def _ocr_pdf_with_vision(path: Path) -> dict[int, str]:
    """OCR image-only PDF pages with the native macOS Vision framework."""
    swift_script = r'''import AppKit
import PDFKit
import Vision
import Foundation

let url = URL(fileURLWithPath: CommandLine.arguments[1])
guard let document = PDFDocument(url: url) else {
    fputs("Не удалось открыть PDF", stderr)
    exit(2)
}
for pageIndex in 0..<document.pageCount {
    autoreleasepool {
        guard let page = document.page(at: pageIndex) else { return }
        let image = page.thumbnail(of: CGSize(width: 1800, height: 2400), for: .mediaBox)
        var bounds = CGRect(origin: .zero, size: image.size)
        guard let cgImage = image.cgImage(forProposedRect: &bounds, context: nil, hints: nil) else { return }
        let request = VNRecognizeTextRequest()
        request.recognitionLevel = .accurate
        request.recognitionLanguages = ["ru-RU", "en-US"]
        request.usesLanguageCorrection = true
        do {
            try VNImageRequestHandler(cgImage: cgImage).perform([request])
            print("<<<PAGE:\(pageIndex + 1)>>>")
            let lines = (request.results ?? []).sorted { $0.boundingBox.midY > $1.boundingBox.midY }
            for line in lines {
                if let text = line.topCandidates(1).first?.string { print(text) }
            }
        } catch {
            fputs("OCR page \(pageIndex + 1): \(error)\n", stderr)
        }
    }
}
'''
    try:
        result = subprocess.run(
            ["swift", "-e", swift_script, str(path)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=1800,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"Истекло время OCR для {path.name}.") from exc
    if result.returncode:
        details = result.stderr.strip().splitlines()
        message = details[-1] if details else "ошибка macOS Vision"
        raise RuntimeError(f"OCR не выполнен для {path.name}: {message}")

    page_text: dict[int, list[str]] = {}
    current_page: int | None = None
    for line in result.stdout.splitlines():
        marker = re.fullmatch(r"<<<PAGE:(\d+)>>>", line.strip())
        if marker:
            current_page = int(marker.group(1))
            page_text[current_page] = []
        elif current_page is not None and line.strip():
            page_text[current_page].append(line.strip())
    return {number: "\n".join(lines) for number, lines in page_text.items()}


def _csv_encoding(path: Path) -> str:
    with path.open("rb") as file:
        sample = file.read(65536)
    for encoding in ("utf-8-sig", "cp1251"):
        try:
            sample.decode(encoding)
            return encoding
        except UnicodeDecodeError:
            continue
    raise UnicodeError(f"Неизвестная кодировка CSV: {path.name}")


def _delimiter(sample: str) -> str:
    try:
        return csv.Sniffer().sniff(sample, delimiters=";,\t|").delimiter
    except csv.Error:
        counts = {delimiter: sample.splitlines()[0].count(delimiter) for delimiter in ";,\t|"}
        return max(counts, key=counts.get) if max(counts.values(), default=0) else ","


def _as_decimal(value: str) -> Decimal | None:
    normalized = value.strip().replace("\u00a0", "").replace(" ", "").replace(",", ".")
    if not normalized:
        return None
    if normalized.endswith("%"):
        normalized = normalized[:-1]
    try:
        number = Decimal(normalized)
    except InvalidOperation:
        return None
    return number if number.is_finite() else None


def _format_number(value: Decimal) -> str:
    return format(value.normalize(), "f")


def summarize_csv(path: Path) -> ParsedDocument:
    """Stream a CSV and retain aggregate metrics only, never source row values."""
    encoding = _csv_encoding(path)
    with path.open("r", encoding=encoding, newline="") as file:
        sample = file.read(8192)
        file.seek(0)
        reader = csv.reader(file, delimiter=_delimiter(sample))
        try:
            headers = [cell.strip() for cell in next(reader)]
        except StopIteration as exc:
            raise ValueError(f"Пустая таблица: {path.name}") from exc

        if not headers or not any(headers):
            raise ValueError(f"В таблице нет заголовков: {path.name}")
        eligible = [
            index
            for index, header in enumerate(headers)
            if header and METRIC_NAME.search(header) and not IDENTIFIER_NAME.search(header)
        ]
        stats = {
            index: {"count": 0, "total": Decimal(0), "min": None, "max": None}
            for index in eligible
        }
        row_count = 0
        nonempty_counts = [0] * len(headers)
        for row in reader:
            if not row or not any(cell.strip() for cell in row):
                continue
            row_count += 1
            for index, value in enumerate(row[: len(headers)]):
                if value.strip():
                    nonempty_counts[index] += 1
            for index in eligible:
                value = _as_decimal(row[index]) if index < len(row) else None
                if value is None:
                    continue
                item = stats[index]
                item["count"] += 1
                item["total"] += value
                item["min"] = value if item["min"] is None else min(item["min"], value)
                item["max"] = value if item["max"] is None else max(item["max"], value)

    lines = [
        f"Таблица: {path.name}",
        f"Строк данных: {row_count}; колонок: {len(headers)}.",
        "Сохранены агрегаты числовых показателей; исходные строки, категории и ID не сохраняются.",
    ]
    for index, metric in stats.items():
        if not metric["count"]:
            continue
        average = metric["total"] / metric["count"]
        lines.append(
            f"{headers[index]}: заполнено {metric['count']} значений; "
            f"сумма {_format_number(metric['total'])}; среднее {_format_number(average)}; "
            f"минимум {_format_number(metric['min'])}; максимум {_format_number(metric['max'])}."
        )
    if not any(stats[index]["count"] for index in stats):
        lines.append("Числовые агрегаты по разрешённым полям отсутствуют.")

    chunks = [
        TextChunk(
            page_num=1,
            chunk_no=index,
            text=chunk,
            source_span={"kind": "table_summary", "columns": len(headers)},
        )
        for index, chunk in enumerate(split_text("\n".join(lines)))
    ]
    return ParsedDocument(title=path.stem, chunks=chunks)


def summarize_xlsx(path: Path) -> ParsedDocument:
    """Load workbook rows as a CSV-like stream; raw cell values remain transient."""
    try:
        from openpyxl import load_workbook  # type: ignore[import-not-found]
    except ImportError as exc:
        raise RuntimeError("Для XLSX нужен openpyxl: pip install openpyxl") from exc

    chunks: list[TextChunk] = []
    workbook = load_workbook(path, read_only=True, data_only=True)
    try:
        for sheet_number, sheet in enumerate(workbook.worksheets, 1):
            rows = sheet.iter_rows(values_only=True)
            try:
                headers = ["" if value is None else str(value).strip() for value in next(rows)]
            except StopIteration:
                continue
            eligible = [
                index
                for index, header in enumerate(headers)
                if header and METRIC_NAME.search(header) and not IDENTIFIER_NAME.search(header)
            ]
            stats = {index: [0, Decimal(0), None, None] for index in eligible}
            count = 0
            for row in rows:
                if not row or not any(value is not None and str(value).strip() for value in row):
                    continue
                count += 1
                for index in eligible:
                    number = _as_decimal(str(row[index])) if index < len(row) and row[index] is not None else None
                    if number is None:
                        continue
                    metric = stats[index]
                    metric[0] += 1
                    metric[1] += number
                    metric[2] = number if metric[2] is None else min(metric[2], number)
                    metric[3] = number if metric[3] is None else max(metric[3], number)
            lines = [f"Лист {sheet.title}: строк данных {count}; колонок {len(headers)}."]
            lines.extend(
                f"{headers[index]}: заполнено {values[0]}; сумма {_format_number(values[1])}; "
                f"среднее {_format_number(values[1] / values[0])}; "
                f"минимум {_format_number(values[2])}; максимум {_format_number(values[3])}."
                for index, values in stats.items()
                if values[0]
            )
            chunks.extend(
                TextChunk(1, len(chunks), text, {"kind": "table_summary", "sheet": sheet.title, "sheet_no": sheet_number})
                for text in split_text("\n".join(lines))
            )
    finally:
        workbook.close()
    if not chunks:
        raise ValueError(f"В книге не найдены таблицы с данными: {path.name}")
    return ParsedDocument(title=path.stem, chunks=chunks)


def parse_document(path: Path) -> ParsedDocument:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return read_pdf(path)
    if suffix == ".csv":
        return summarize_csv(path)
    if suffix in {".xlsx", ".xlsm"}:
        return summarize_xlsx(path)
    raise ValueError(f"Формат не поддерживается: {path.name}")


def _import_to_database(path: Path, parsed: ParsedDocument, file_hash: str) -> str:
    """Commit one complete report and all its chunks; return inserted/already-present."""
    backend_dir = HERE.parents[1]
    if str(backend_dir) not in sys.path:
        sys.path.insert(0, str(backend_dir))

    from sqlalchemy import delete, select

    from app.infrastructure.database.models.analytics import AlfaReport, AlfaReportChunk
    from app.infrastructure.database.session import get_engine, make_session_factory

    session_factory = make_session_factory(get_engine())
    with session_factory() as session, session.begin():
        report = session.scalar(select(AlfaReport).where(AlfaReport.file_hash == file_hash))
        if report is not None and report.status == "ready":
            return "already-present"
        if report is None:
            report = AlfaReport(
                filename=path.name,
                title=parsed.title,
                report_date=_date_from_name(path.name),
                source_url=DRIVE_URLS.get(path.name),
                file_hash=file_hash,
                status="pending",
            )
            session.add(report)
            session.flush()
        else:
            session.execute(delete(AlfaReportChunk).where(AlfaReportChunk.report_id == report.id))
            report.filename = path.name
            report.title = parsed.title
            report.report_date = _date_from_name(path.name)
            report.source_url = DRIVE_URLS.get(path.name)
            report.status = "pending"
            session.flush()

        session.add_all(
            AlfaReportChunk(
                report_id=report.id,
                page_num=chunk.page_num,
                chunk_no=chunk.chunk_no,
                text=chunk.text,
                source_span_json=chunk.source_span,
            )
            for chunk in parsed.chunks
        )
        report.status = "ready"
    return "inserted"


def _date_from_name(filename: str) -> date | None:
    match = re.search(r"(?<!\d)(20\d{2})[-_. ]?(\d{2})[-_. ]?(\d{2})(?!\d)", filename)
    if match:
        year, month, day = map(int, match.groups())
        try:
            return date(year, month, day)
        except ValueError:
            return None
    return None


def ingest_directory(
    directory: Path = DEFAULT_INPUT_DIR, *, delete_after_import: bool = True
) -> dict[str, int]:
    files = sorted(
        path for path in directory.iterdir()
        if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES
    )
    if not files:
        raise FileNotFoundError(f"В папке нет файлов PDF/CSV/XLSX: {directory}")

    counts = Counter()
    successful: list[Path] = []
    failures: list[tuple[Path, Exception]] = []
    for path in files:
        try:
            parsed = parse_document(path)
            status = _import_to_database(path, parsed, sha256_file(path))
            counts[status] += 1
            counts["chunks"] += len(parsed.chunks) if status == "inserted" else 0
            successful.append(path)
            print(f"{status}: {path.name} ({len(parsed.chunks)} фрагм.)")
        except Exception as exc:
            failures.append((path, exc))
            print(f"ОШИБКА: {path.name}: {exc}", file=sys.stderr)

    # A partial run keeps every input so it can be inspected/retried safely.
    if delete_after_import and not failures:
        for path in successful:
            path.unlink()
            counts["deleted"] += 1
    if failures:
        raise RuntimeError(f"Не обработано файлов: {len(failures)}; исходники оставлены.")
    return dict(counts)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=DEFAULT_INPUT_DIR)
    parser.add_argument(
        "--keep-files",
        action="store_true",
        help="не удалять исходные PDF/таблицы после успешной записи в БД",
    )
    args = parser.parse_args(argv)
    try:
        counts = ingest_directory(args.directory, delete_after_import=not args.keep_files)
    except Exception as exc:
        print(f"Импорт завершился с ошибкой: {exc}", file=sys.stderr)
        return 1
    print("Итог:", ", ".join(f"{key}={value}" for key, value in sorted(counts.items())))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
