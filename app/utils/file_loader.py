"""
Утилиты для загрузки и хранения файлов на диске.
"""

import re
from hashlib import md5
from pathlib import Path
from uuid import uuid4


def calculate_file_hash(file_bytes: bytes) -> str:
    """Возвращает md5-хеш содержимого файла."""
    return md5(file_bytes).hexdigest()


def calculate_file_hash_from_path(file_path: Path) -> str:
    """Возвращает md5-хеш файла по его пути."""
    return calculate_file_hash(file_path.read_bytes())


def _sanitize_name(file_name: str) -> str:
    """Очищает имя файла от недопустимых символов."""
    name = re.sub(r"\s+", "_", file_name.strip())
    name = re.sub(r"[^A-Za-zА-Яа-яЁё0-9._-]", "", name)
    return name or "file"


def build_stored_file_name(original_name: str) -> str:
    """Строит уникальное имя для сохранения файла."""
    path = Path(original_name)
    return f"{_sanitize_name(path.stem)}_{uuid4().hex[:8]}{path.suffix.lower()}"


def save_binary_file(directory: Path, original_name: str, file_bytes: bytes) -> tuple[str, Path]:
    """Сохраняет бинарные данные в каталог и возвращает (имя_на_диске, путь)."""
    directory.mkdir(parents=True, exist_ok=True)
    stored_name = build_stored_file_name(original_name)
    file_path = directory / stored_name
    file_path.write_bytes(file_bytes)
    return stored_name, file_path


def find_existing_file_by_hash(directory: Path, file_hash: str) -> Path | None:
    """Ищет в каталоге файл с указанным md5-хешем."""
    if not directory.exists():
        return None

    for file_path in directory.iterdir():
        if not file_path.is_file() or file_path.name.startswith("."):
            continue
        if calculate_file_hash_from_path(file_path) == file_hash:
            return file_path
    return None
