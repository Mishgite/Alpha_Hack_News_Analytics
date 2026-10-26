"""загружает подготовленные отчёты и выдаёт фрагменты с происхождением текста"""

import json
from pathlib import Path
from uuid import UUID

from app.infrastructure.database.uow import UnitOfWork
from app.schemas.reports import ReportInput, ReportPart

from ._common import digest

IMPORT_VERSION = "reviewed-text-v2"


def split_report_text(content: str, limit: int = 3000) -> list[str]:
    """разбивает текст по границам предложений или слов, не теряя остаток блока"""
    parts = []
    content = content.strip()
    while len(content) > limit:
        boundary = content.rfind(". ", limit // 2, limit)
        boundary = (
            boundary + 1 if boundary >= 0 else content.rfind(" ", limit // 2, limit)
        )
        boundary = boundary if boundary > 0 else limit
        parts.append(content[:boundary].strip())
        content = content[boundary:].strip()
    if content:
        parts.append(content)
    return parts


class ReportService:
    """паттерн Service Layer: отделяет импорт документов от хранения и HTTP"""

    def __init__(self, *, uow_factory=UnitOfWork):
        """принимает фабрику транзакций для импорта и чтения отчётов"""
        self._uow = uow_factory

    def save_report(self, report: ReportInput) -> UUID:
        """сохраняет документ целиком, повтор того же содержимого не меняет ID фрагментов"""
        keys = [(p.page_num, p.chunk_no) for p in report.parts]
        if len(keys) != len(set(keys)):
            raise ValueError("Duplicate report fragment")
        with self._uow() as db:
            result = db.reports.save(report)
            db.commit()
            return result

    def get_chunk(self, chunk_id: UUID):
        """возвращает текст, страницу и название источника для панели доказательств"""
        with self._uow() as db:
            return db.reports.get_chunk(chunk_id)

    def corpus_version(self) -> str:
        """считает версию готового корпуса для ключей кеша аналитики"""
        with self._uow() as db:
            return digest(db.reports.versions())

    def import_directory(self, directory: Path) -> dict:
        """читает результаты prepare_reports, исключает блоки с непроверенным распознаванием"""
        result = {"imported": 0, "skipped": 0, "errors": []}
        for manifest_path in sorted(directory.glob("*/manifest.json")):
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                if not manifest.get("complete"):
                    result["skipped"] += 1
                    continue
                parts = []
                for page_info in manifest["pages"]:
                    filename = page_info["json"]
                    if Path(filename).name != filename or "\\" in filename:
                        raise ValueError("Invalid page filename")
                    page = json.loads(
                        (manifest_path.parent / filename).read_text(encoding="utf-8")
                    )
                    blocks = page.get("display_blocks", page.get("blocks", []))
                    if page.get("manual_transcription"):
                        blocks = [
                            {
                                "number": 0,
                                "status": "text_candidate",
                                "display_text": page["manual_transcription"],
                                "method": "manual_transcription",
                            }
                        ]
                    for block in blocks:
                        if block.get("status") != "text_candidate":
                            continue
                        content = block.get(
                            "display_text", block.get("text", "")
                        ).strip()
                        if len(content) < 80:
                            continue
                        for text in split_report_text(content):
                            parts.append(
                                ReportPart(
                                    page_num=page["page"],
                                    chunk_no=len(parts),
                                    text=text,
                                    source_span_json={
                                        "block": block["number"],
                                        "bbox": block.get("bbox"),
                                        "method": block.get("method", "ocr"),
                                        "review_status": page_info.get(
                                            "review_status", "unknown"
                                        ),
                                        "original_sha256": manifest["source_sha256"],
                                    },
                                )
                            )
                if not parts:
                    result["skipped"] += 1
                    continue
                # новая обработка создаёт новую версию, прежние цитаты остаются доступными
                version = digest(
                    {
                        "source": manifest["source_sha256"],
                        "title": manifest.get("title"),
                        "date": manifest.get("publication_date"),
                        "parts": [p.model_dump() for p in parts],
                    }
                )
                self.save_report(
                    ReportInput(
                        filename=manifest["source_file"],
                        title=manifest.get("title") or manifest["source_file"],
                        file_hash=version,
                        report_date=manifest.get("publication_date"),
                        parts=parts,
                    )
                )
                result["imported"] += 1
            except (ValueError, KeyError, OSError, TypeError, AttributeError) as error:
                result["errors"].append(
                    {
                        "document": manifest_path.parent.name,
                        "error": type(error).__name__,
                    }
                )
        return result
