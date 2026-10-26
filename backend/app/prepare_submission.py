"""собирает код и отдельный закрытый архив исходных данных без ключей и окружения"""

import argparse
import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "backend/data"


def checksum(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def private_files(data):
    """проверяет оригиналы и страницы перед включением разрешённых файлов в архив"""
    paths = [
        data / "companies" / name
        for name in (
            "df_Uid_data_hack.csv",
            "df_Fid_Uid_link_hack.csv",
            "df_Uid_payment_hack.csv",
            "selection.txt",
        )
    ]
    selection = paths[-1].read_text(encoding="utf-8").splitlines()
    if len(set(selection)) != 50 or len(selection) != 50:
        raise ValueError("Expected exactly 50 distinct company IDs")
    paths.append(data / "report_annotations.json")
    manifests = sorted((data / "reports_processed").glob("*/manifest.json"))
    if not manifests:
        raise ValueError("Prepared reports are missing")
    for path in manifests:
        manifest = json.loads(path.read_text(encoding="utf-8"))
        if not manifest.get("complete") or not manifest.get("pages"):
            raise ValueError("Incomplete report: " + path.parent.name)
        name = manifest["source_file"]
        if Path(name).name != name or "\\" in name:
            raise ValueError("Invalid PDF filename")
        source = data / "reports" / name
        if checksum(source) != manifest["source_sha256"]:
            raise ValueError("PDF checksum mismatch: " + name)
        paths.extend((source, path))
        for info in manifest["pages"]:
            filename = info["json"]
            if Path(filename).name != filename or "\\" in filename:
                raise ValueError("Invalid page filename")
            page = path.parent / filename
            json.loads(page.read_text(encoding="utf-8"))
            paths.append(page)
    return sorted(set(paths))


def code_files(root):
    """берёт только файлы Git и новые рабочие файлы, исключая локальный main.py и данные"""
    output = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=root,
        capture_output=True,
        check=True,
    ).stdout
    paths = []
    for name in output.decode("utf-8").split("\0"):
        if not name:
            continue
        relative = Path(name)
        if relative.as_posix() == "backend/app/main.py" or (
            relative.parts[:2] == ("backend", "data")
            and relative.parts[:3] != ("backend", "data", "examples")
        ):
            continue
        if any(
            part in {".git", ".venv", "node_modules", "__pycache__", ".idea"}
            for part in relative.parts
        ):
            continue
        if (
            relative.name == ".env"
            or (
                relative.name.startswith(".env.")
                and not relative.name.endswith(".example")
            )
            or relative.suffix in {".pem", ".key"}
        ):
            continue
        path = root / relative
        if path.is_file():
            paths.append(path)
    return sorted(set(paths))


def archive(path, files, root):
    """включает контрольные суммы и повторно проверяет архив после записи"""
    manifest = {
        file.relative_to(root).as_posix(): {
            "sha256": checksum(file),
            "size": file.stat().st_size,
        }
        for file in files
    }
    with ZipFile(path, "x", compression=ZIP_DEFLATED) as output:
        for file in files:
            if not file.resolve().is_relative_to(root.resolve()):
                raise ValueError("Archive input outside root")
            output.write(file, file.relative_to(root).as_posix())
        output.writestr(
            "SHA256.json", json.dumps(manifest, ensure_ascii=False, indent=2)
        )
    with ZipFile(path) as saved:
        for name, value in manifest.items():
            with saved.open(name) as stream:
                if hashlib.file_digest(stream, "sha256").hexdigest() != value["sha256"]:
                    raise ValueError("Archive checksum mismatch: " + name)
    return {
        "file": path.name,
        "sha256": checksum(path),
        "files": len(files),
        "size": path.stat().st_size,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=DATA)
    parser.add_argument("--output", type=Path, default=DATA / "submission")
    args = parser.parse_args()
    private = private_files(args.data)
    code = code_files(ROOT)
    destination = args.output / datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    destination.mkdir(parents=True, exist_ok=False)
    result = [
        archive(destination / "source.zip", code, ROOT),
        archive(destination / "private-data.zip", private, args.data),
    ]
    (destination / "archives.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (destination / "START.md").write_text(
        "# Запуск\n\n1. Распаковать source.zip в папку проекта\n2. Распаковать private-data.zip в backend/data\n3. Настроить ключи в docker/.env по docker/.env.example\n4. Запустить по backend/docs/run.md, раздел «Сервер: Docker и отдельный фронтенд»\n\nПервый запуск размечает 50 компаний через модель в пределах настроенного лимита\nПовторный запуск использует сохранённую БД\nДанные компаний передаются отдельно и не публикуются в Git\nВ каждом архиве SHA256.json содержит суммы входных файлов\n",
        encoding="utf-8",
    )
    print(destination)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
