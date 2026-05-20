"""
Общие утилиты проекта.

В этом модуле собраны функции и константы, которые ранее дублировались
в нескольких сервисах: дедупликация записей и маппинги этапов попытки.

Контекст-менеджер сессии БД вынесен в app/utils/db.py, чтобы этот модуль
не зависел от SQLAlchemy.
"""

from typing import Iterable


# ---------------------------------------------------------------------------
# Маппинги этапов попытки.
# ---------------------------------------------------------------------------

# Машинный код этапа → человекочитаемое название.
STAGE_RU_NAME: dict[str, str] = {
    "main": "основная",
    "secondary": "вторичная",
    "commission": "комиссия",
}

# Машинный код этапа → условный номер попытки.
STAGE_TO_ATTEMPT: dict[str, int] = {
    "main": 1,
    "secondary": 2,
    "commission": 3,
}

# Порядок этапов для сортировки результатов (сначала критичное).
STAGE_SORT_ORDER: dict[str, int] = {
    "commission": 0,
    "secondary": 1,
    "main": 2,
    "": 3,
}

# Ключевые поля записи, по которым проверяется дубль.
DEDUP_KEYS: tuple[str, ...] = (
    "attempt_stage",
    "discipline",
    "teacher",
    "groups_normalized",
    "date",
    "time",
    "room",
    "consultation_date",
    "consultation_time",
    "consultation_room",
)


def stage_ru(stage: str) -> str:
    """Возвращает русское название этапа."""
    return STAGE_RU_NAME.get(stage, "вторичная")


def stage_attempt(stage: str) -> int:
    """Возвращает условный номер попытки для этапа."""
    return STAGE_TO_ATTEMPT.get(stage, 2)


# ---------------------------------------------------------------------------
# Дедупликация записей.
# ---------------------------------------------------------------------------

def dedupe_records(
    records: Iterable[dict],
    keys: tuple[str, ...] = DEDUP_KEYS,
) -> list[dict]:
    """
    Удаляет дубли записей по набору полей.

    Сравнение регистронезависимое. Если поле отсутствует, оно считается
   Пустой строкой.
    """
    seen: set[tuple] = set()
    unique: list[dict] = []

    for record in records:
        key = tuple(str(record.get(field, "") or "").lower() for field in keys)
        if key in seen:
            continue
        seen.add(key)
        unique.append(record)

    return unique
