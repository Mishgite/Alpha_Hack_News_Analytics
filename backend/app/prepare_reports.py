"""распознаёт PDF по страницам и сохраняет текст, координаты слов и превью"""

import argparse
import csv
import hashlib
import io
import json
import os
import re
import shutil
import statistics
import time
import urllib.request
from pathlib import Path
from urllib.parse import quote

import pypdfium2 as pdfium
import pytesseract

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
MODEL_URL = (
    "https://raw.githubusercontent.com/tesseract-ocr/tessdata_best/main/{}.traineddata"
)
FORMAT_VERSION = 1


def sha256(path: Path) -> str:
    """считает контрольную сумму файла без загрузки всего файла в память"""
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_json(path: Path, value: dict) -> None:
    """заменяет готовый JSON после успешной записи временного файла"""
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    temporary.replace(path)


def prepare_ocr(model_dir: Path, executable: str | None) -> dict:
    """находит Tesseract и скачивает недостающие языковые модели в папку data"""
    command = executable or shutil.which("tesseract")
    windows_path = (
        Path(os.environ.get("ProgramFiles", "C:/Program Files"))
        / "Tesseract-OCR/tesseract.exe"
    )
    if not command and windows_path.is_file():
        command = str(windows_path)
    if not command:
        raise RuntimeError(
            "Tesseract не найден: установите его или передайте --tesseract ПУТЬ"
        )
    pytesseract.pytesseract.tesseract_cmd = command
    model_dir.mkdir(parents=True, exist_ok=True)
    models = {}
    for language in ("rus", "eng"):
        target = model_dir / f"{language}.traineddata"
        if not target.is_file():
            print(f"Downloading OCR model: {language}", flush=True)
            temporary = target.with_suffix(".download")
            with urllib.request.urlopen(
                MODEL_URL.format(language), timeout=90
            ) as source, temporary.open("wb") as destination:
                shutil.copyfileobj(source, destination)
            temporary.replace(target)
        models[language] = {"url": MODEL_URL.format(language), "sha256": sha256(target)}
    return {"tesseract": str(pytesseract.get_tesseract_version()), "models": models}


def read_words(tsv: str) -> list[dict]:
    """сохраняет распознанные слова с оценкой OCR и прямоугольником на изображении"""
    words = []
    for row in csv.DictReader(io.StringIO(tsv), delimiter="\t", quoting=csv.QUOTE_NONE):
        if row["level"] != "5" or not (row.get("text") or "").strip():
            continue
        words.append(
            {
                "text": row["text"].strip(),
                "confidence": round(float(row["conf"]), 2),
                "block": int(row["block_num"]),
                "paragraph": int(row["par_num"]),
                "line": int(row["line_num"]),
                "bbox": [int(row[key]) for key in ("left", "top", "width", "height")],
            }
        )
    return words


def make_blocks(words: list[dict]) -> list[dict]:
    """собирает строки в блоки в порядке Tesseract без угадывания структуры таблиц"""
    blocks = {}
    for word in words:
        block = blocks.setdefault(word["block"], {})
        line_key = (word["paragraph"], word["line"])
        block.setdefault(line_key, []).append(word)
    result = []
    for block_number, lines in blocks.items():
        block_words = [word for line in lines.values() for word in line]
        left = min(w["bbox"][0] for w in block_words)
        top = min(w["bbox"][1] for w in block_words)
        right = max(w["bbox"][0] + w["bbox"][2] for w in block_words)
        bottom = max(w["bbox"][1] + w["bbox"][3] for w in block_words)
        result.append(
            {
                "number": block_number,
                "bbox": [left, top, right - left, bottom - top],
                "text": "\n".join(
                    " ".join(w["text"] for w in line) for line in lines.values()
                ),
            }
        )
    return result


def classify_blocks(page: dict) -> None:
    """помечает графики, числовые блоки и неуверенное распознавание для проверки по изображению"""
    for block in page["blocks"]:
        words = [w for w in page["words"] if w["block"] == block["number"]]
        count = len(words)
        low_ratio = sum(w["confidence"] < 60 for w in words) / max(count, 1)
        numeric_ratio = sum(any(c.isdigit() for c in w["text"]) for w in words) / max(
            count, 1
        )
        reasons = []
        if re.match(
            r"^(рис[.\s]|рисунок|график|таблица)", block["text"], flags=re.IGNORECASE
        ):
            reasons.append("figure_or_table_caption")
        if count >= 12 and numeric_ratio > 0.4:
            reasons.append("numeric_layout")
        if count >= 8 and low_ratio > 0.25:
            reasons.append("low_confidence")
        if not any(c.isalpha() for c in block["text"]):
            reasons.append("symbols_without_text")
        elif count <= 4 and sum(c.isalpha() for c in block["text"]) <= 2:
            reasons.append("short_isolated_fragment")
        block["review_reasons"] = reasons
        block["status"] = "needs_review" if reasons else "text_candidate"
    page["quality"]["review_block_count"] = sum(
        b["status"] == "needs_review" for b in page["blocks"]
    )


def save_color_preview(page, output: Path, result: dict, dpi: int) -> None:
    """сохраняет цветную страницу для сверки графиков, даже если OCR использовал серое изображение"""
    if result.get("preview_mode") == "RGB":
        return
    bitmap = page.render(scale=dpi / 72)
    image = bitmap.to_pil().copy()
    bitmap.close()
    try:
        image.save(output / result["image"])
        result["preview_mode"] = "RGB"
    finally:
        image.close()


def apply_review(page: dict, annotation: dict) -> None:
    """применяет только записанные после визуальной сверки исправления, сохраняя исходный OCR"""
    display_blocks = page.get("display_blocks", page["blocks"])
    for block in display_blocks:
        block["display_text"] = block["text"]
    page["verified_corrections"] = []
    for correction in annotation.get("corrections", []):
        if correction["page"] != page["page"]:
            continue
        matches = [
            b for b in display_blocks if correction["original"] in b["display_text"]
        ]
        if (
            len(matches) != 1
            or matches[0]["display_text"].count(correction["original"]) != 1
        ):
            raise ValueError(
                f"Не удалось однозначно применить исправление: {correction}"
            )
        block = matches[0]
        block["display_text"] = block["display_text"].replace(
            correction["original"], correction["corrected"], 1
        )
        page["verified_corrections"].append(correction)
    if page["page"] in annotation.get("spot_checked_pages", []):
        page["quality"]["review_status"] = "spot_checked"
        page["quality"]["review_scope"] = "title_date_and_selected_passages_only"
    page["verified_tables"] = [
        table for table in annotation.get("tables", []) if table["page"] == page["page"]
    ]
    page["manual_transcription"] = annotation.get("manual_transcriptions", {}).get(
        str(page["page"])
    )


def select_text_regions(page: dict, annotation: dict) -> None:
    """разделяет текст и графики по областям, проверенным на изображении страницы"""
    page.pop("display_blocks", None)
    regions = annotation.get("text_regions", {}).get(str(page["page"]))
    if not regions:
        return
    display_blocks = []
    selected = set()
    for region_number, (left, top, right, bottom) in enumerate(regions, start=1):
        words = []
        for index, word in enumerate(page["words"]):
            x, y, width, height = word["bbox"]
            center_x = (x + width / 2) / page["width"]
            center_y = (y + height / 2) / page["height"]
            if (
                index not in selected
                and left <= center_x < right
                and top <= center_y < bottom
            ):
                selected.add(index)
                words.append(word)
        region_page = {"words": words, "blocks": make_blocks(words), "quality": {}}
        classify_blocks(region_page)
        for block in region_page["blocks"]:
            block["source_block"] = block["number"]
            block["number"] = f"{region_number}.{block['number']}"
            display_blocks.append(block)
    page["display_blocks"] = display_blocks
    page["quality"]["layout_reviewed"] = True
    page["quality"]["words_outside_text_regions"] = len(page["words"]) - len(selected)
    page["quality"]["review_block_count"] = sum(
        b["status"] == "needs_review" for b in display_blocks
    )


def recognize_page(
    page, page_number: int, output: Path, config: dict, key: str
) -> dict:
    """распознаёт одну страницу и освобождает её изображение до перехода к следующей"""
    json_path = output / f"page_{page_number:03}.json"
    image_path = output / f"page_{page_number:03}.png"
    text_path = output / f"page_{page_number:03}.txt"
    if all(
        path.is_file()
        for path in (
            json_path,
            image_path,
            text_path,
            output / f"page_{page_number:03}.tsv",
        )
    ):
        saved = json.loads(json_path.read_text(encoding="utf-8"))
        if saved.get("cache_key") == key:
            return saved
    scale = config["dpi"] / 72
    bitmap = page.render(scale=scale, grayscale=True)
    image = bitmap.to_pil().copy()
    bitmap.close()
    try:
        image.save(image_path)
        tsv = pytesseract.image_to_data(
            image,
            lang="rus+eng",
            config=f"--oem 1 --psm 3 --dpi {config['dpi']}",
            timeout=240,
        )
        words = read_words(tsv)
        blocks = make_blocks(words)
        text = "\n\n".join(block["text"] for block in blocks)
        scores = [w["confidence"] for w in words]
        low_ratio = sum(score < 60 for score in scores) / max(len(scores), 1)
        numeric_ratio = sum(any(ch.isdigit() for ch in w["text"]) for w in words) / max(
            len(words), 1
        )
        warnings = []
        if len(words) < 30:
            warnings.append("little_text")
        if low_ratio > 0.15:
            warnings.append("many_low_confidence_words")
        if numeric_ratio > 0.25:
            warnings.append("numeric_layout_check_required")
        result = {
            "cache_key": key,
            "page": page_number,
            "image": image_path.name,
            "width": image.width,
            "height": image.height,
            "pdf_width_points": page.get_width(),
            "pdf_height_points": page.get_height(),
            "text": text,
            "blocks": blocks,
            "words": words,
            "quality": {
                "word_count": len(words),
                "mean_confidence": round(statistics.mean(scores), 2) if scores else 0,
                "low_confidence_fraction": round(low_ratio, 4),
                "numeric_word_fraction": round(numeric_ratio, 4),
                "warnings": warnings,
                "review_status": "not_manually_reviewed",
            },
        }
        text_path.write_text(text + "\n", encoding="utf-8")
        (output / f"page_{page_number:03}.tsv").write_text(tsv, encoding="utf-8")
        write_json(json_path, result)
        return result
    finally:
        image.close()


def process_pdf(
    source: Path,
    output_root: Path,
    config: dict,
    max_pages: int | None,
    annotation: dict,
) -> dict:
    """создаёт постраничный текст документа и проверяет сохранность исходного PDF"""
    digest = sha256(source)
    if annotation and annotation["source_sha256"] != digest:
        raise ValueError(
            f"PDF изменился, результаты ручной сверки устарели: {source.name}"
        )
    output = output_root / source.stem
    output.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha256(
        json.dumps({"source": digest, **config}, sort_keys=True).encode()
    ).hexdigest()
    pdf = pdfium.PdfDocument(source)
    pages = []
    try:
        count = len(pdf)
        for index in range(min(count, max_pages or count)):
            page = pdf[index]
            try:
                result = recognize_page(page, index + 1, output, config, key)
                result["source_file"] = source.name
                result["source_sha256"] = digest
                result["publication_date"] = annotation.get("publication_date")
                result["publication_month"] = annotation.get("publication_month")
                save_color_preview(page, output, result, config["dpi"])
                classify_blocks(result)
                select_text_regions(result, annotation)
                apply_review(result, annotation)
                write_json(output / f"page_{index + 1:03}.json", result)
                pages.append(result)
                print(
                    f"{source.name}: {index + 1}/{count}, words={result['quality']['word_count']}, confidence={result['quality']['mean_confidence']}",
                    flush=True,
                )
            finally:
                page.close()
    finally:
        pdf.close()
    if sha256(source) != digest:
        raise RuntimeError(f"Исходный PDF изменился во время обработки: {source}")
    summary = {
        "source_file": source.name,
        "source_sha256": digest,
        "page_count": count,
        "processed_pages": len(pages),
        "complete": len(pages) == count,
        "config": config,
        "publication_date": annotation.get("publication_date"),
        "publication_month": annotation.get("publication_month"),
        "title": annotation.get("title"),
        "metadata_source_page": 1 if annotation else None,
        "publication_date_note": annotation.get(
            "date_note", "дата требует сверки с первой страницей"
        ),
        "pages": [
            {"page": p["page"], "json": f"page_{p['page']:03}.json", **p["quality"]}
            for p in pages
        ],
    }
    write_json(output / "manifest.json", summary)
    markdown = [
        f"# {source.name}",
        "",
        f"[Исходный PDF](../../reports/{quote(source.name)})",
        "",
        "Текст получен OCR, возможны ошибки распознавания",
        "",
        "Блоки с признаками графиков, таблиц и ошибок вынесены в ссылки на изображения",
        "Это предварительный отбор по эвристикам, оставшийся текст также требует проверки перед использованием чисел",
        "",
        "[Полный результат OCR](ocr_raw.md)",
        "",
    ]
    if annotation:
        markdown.extend(
            [
                f"Название: {annotation['title']}",
                "",
                f"Дата: {annotation.get('publication_date') or annotation.get('publication_month')}",
                "",
            ]
        )
    raw_markdown = [f"# {source.name}: полный результат OCR", ""]
    for page in pages:
        header = [
            f"## Страница {page['page']}",
            "",
            f"[Изображение страницы](page_{page['page']:03}.png)",
            "",
        ]
        markdown.extend(header)
        if "display_blocks" in page:
            markdown.extend(
                [
                    "> Графики и таблицы сохранены на изображении страницы, текстовые области разобраны отдельно",
                    "",
                ]
            )
        raw_markdown.extend([*header, page["text"], ""])
        blocks = page.get("display_blocks", page["blocks"])
        if page["manual_transcription"]:
            markdown.extend([page["manual_transcription"], ""])
            blocks = []
        for block in blocks:
            if block["status"] == "needs_review":
                label = (
                    "График или таблица"
                    if any(
                        r in block["review_reasons"]
                        for r in ("numeric_layout", "figure_or_table_caption")
                    )
                    else "Неуверенное распознавание"
                )
                markdown.extend(
                    [
                        f"> {label}: [сверить с изображением](page_{page['page']:03}.png), блок {block['number']}",
                        "",
                    ]
                )
            else:
                markdown.extend([block["display_text"], ""])
        for table in page["verified_tables"]:
            markdown.extend(
                [f"### {table['title']}", "", "Перенесено по изображению страницы", ""]
            )
            markdown.append("| " + " | ".join(table["columns"]) + " |")
            markdown.append("| " + " | ".join("---" for _ in table["columns"]) + " |")
            for row in table["rows"]:
                markdown.append("| " + " | ".join(row) + " |")
            markdown.extend(["", table.get("note", ""), ""])
    (output / "document.md").write_text("\n".join(markdown), encoding="utf-8")
    (output / "ocr_raw.md").write_text("\n".join(raw_markdown), encoding="utf-8")
    return summary


def main() -> None:
    """обрабатывает PDF последовательно и продолжает готовые страницы при повторном запуске"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DATA_DIR / "reports")
    parser.add_argument("--output", type=Path, default=DATA_DIR / "reports_processed")
    parser.add_argument("--pdf", default="*.pdf", help="имя файла или шаблон")
    parser.add_argument("--dpi", type=int, default=300, choices=(200, 250, 300))
    parser.add_argument(
        "--max-pages", type=int, help="ограничение для пробного запуска"
    )
    parser.add_argument("--tesseract", help="путь к исполняемому файлу Tesseract")
    args = parser.parse_args()
    if args.max_pages is not None and args.max_pages < 1:
        parser.error("--max-pages должен быть больше нуля")
    sources = sorted(args.input.glob(args.pdf))
    if not sources:
        parser.error(f"PDF не найдены: {args.input / args.pdf}")
    if args.input.resolve() == args.output.resolve():
        parser.error("папки исходников и результатов должны различаться")
    os.environ["OMP_THREAD_LIMIT"] = "1"
    model_dir = DATA_DIR / "ocr_models"
    engine = prepare_ocr(model_dir, args.tesseract)
    os.environ["TESSDATA_PREFIX"] = str(model_dir)
    config = {
        "format_version": FORMAT_VERSION,
        "dpi": args.dpi,
        "model_dir": str(model_dir),
        **engine,
    }
    args.output.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    documents = []
    annotation_path = DATA_DIR / "report_annotations.json"
    annotations = (
        json.loads(annotation_path.read_text(encoding="utf-8"))
        if annotation_path.is_file()
        else {}
    )
    for source in sources:
        documents.append(
            process_pdf(
                source,
                args.output,
                config,
                args.max_pages,
                annotations.get(source.name, {}),
            )
        )
    write_json(
        args.output / "manifest.json",
        {
            "documents": documents,
            "elapsed_seconds": round(time.monotonic() - started, 2),
            "complete": all(doc["complete"] for doc in documents),
        },
    )
    index = [
        "# Распознанные отчёты",
        "",
        "В каждой папке: document.md для чтения, ocr_raw.md без отбора блоков, изображения и JSON по страницам",
        "",
        "Статус text_candidate означает только прохождение эвристик, а не подтверждённую точность OCR",
        "",
    ]
    for doc in documents:
        folder = quote(Path(doc["source_file"]).stem)
        index.append(
            f"- [{doc['source_file']}]({folder}/document.md): {doc['processed_pages']}/{doc['page_count']} страниц"
        )
    (args.output / "README.md").write_text("\n".join(index) + "\n", encoding="utf-8")
    print(
        f"Done: {len(documents)} documents, {sum(doc['processed_pages'] for doc in documents)} pages",
        flush=True,
    )


if __name__ == "__main__":
    main()
