"""
Нормализатор строк Excel.

Из сырой строки Excel делает одну структурированную запись.
"""

import re
from datetime import date, datetime
from typing import Any

from app.core.constants import EXCEL_COLUMN_ALIASES, HEADER_SKIP_VALUES
from app.services.risk_classifier import risk_classifier
from app.utils.common import (
    DEDUP_KEYS,
    dedupe_records,
    stage_attempt,
    stage_ru,
)


# ---------------------------------------------------------------------------
# Низкоуровневые помощники.
# ---------------------------------------------------------------------------

def _clean_text(value: Any) -> str:
    """Приводит ячейку Excel к чистой строке."""
    if value is None:
        return ""
    text = str(value).replace("\r", " ").replace("\n", " ").strip()
    return re.sub(r"\s+", " ", text)


def _normalize_date(value: Any) -> str:
    """Очищает строковое представление даты, сохраняя смысл."""
    text = _clean_text(value)
    if not text:
        return ""
    text = text.replace("T00:00:00", "").replace(" 00:00:00", "").replace("/", ".")
    return re.sub(r"\s+", " ", text).strip()


def _normalize_column_name(name: str) -> str:
    """Приводит имя колонки к единому виду."""
    name = str(name).replace("\r", " ").replace("\n", " ")
    return re.sub(r"\s+", " ", name).strip()


def _get_value(data: dict, aliases: list[str]) -> str:
    """
    Возвращает первое непустое значение по списку возможных названий
    колонки. Сравнение регистронезависимое по нормализованным именам.
    """
    normalized_data = {_normalize_column_name(k): v for k, v in data.items()}
    for alias in aliases:
        cleaned = _clean_text(normalized_data.get(_normalize_column_name(alias)))
        if cleaned:
            return cleaned
    return ""


def _normalize_group_token(token: str) -> str:
    """Нормализует одну учебную группу."""
    token = token.strip().upper().replace("–", "-").replace("—", "-")
    return re.sub(r"\s+", "", token).strip(" ,;")


def _extract_groups(groups_text: str) -> list[str]:
    """Извлекает список групп из текстового поля Excel."""
    if not groups_text:
        return []

    text = str(groups_text).replace("\r", "\n").replace("–", "-").replace("—", "-")
    if "все группы" in text.lower():
        return ["ВСЕ ГРУППЫ"]

    pattern = r"[A-Za-zА-Яа-яЁё0-9]+(?:-[A-Za-zА-Яа-яЁё0-9()]+){0,6}"
    found = re.findall(pattern, text)
    groups = [_normalize_group_token(item) for item in found if item.strip()]

    if not groups:
        prepared = text.replace(";", ",").replace("\n", ",")
        groups = [_normalize_group_token(p) for p in prepared.split(",") if p.strip()]

    return list(dict.fromkeys(filter(None, groups)))


# ---------------------------------------------------------------------------
# Этап попытки.
# ---------------------------------------------------------------------------

_STAGE_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("commission", ("комисс",)),
    ("secondary", ("вторич", "вторая", "первич", "первая")),
    ("main", ("main", "session", "сесс", "основ")),
)


def _detect_stage(text: str) -> str | None:
    """Определяет этап по ключевым словам в тексте."""
    text_low = str(text or "").lower().replace("ё", "е")
    for stage, markers in _STAGE_KEYWORDS:
        if any(marker in text_low for marker in markers):
            return stage
    return None


def _detect_attempt_stage(sheet_name: str, source_file: str) -> str:
    """Определяет этап попытки. Лист имеет приоритет над файлом."""
    return _detect_stage(sheet_name) or _detect_stage(source_file) or "secondary"


# ---------------------------------------------------------------------------
# Даты события и срочность.
# ---------------------------------------------------------------------------

_DATE_FORMATS: tuple[tuple[str, str], ...] = (
    (r"\d{4}-\d{2}-\d{2}", "%Y-%m-%d"),
    (r"\d{1,2}\.\d{1,2}\.\d{4}", "%d.%m.%Y"),
)


def _extract_dates(text: str) -> list[date]:
    """Извлекает все даты из строки."""
    text = _clean_text(text)
    if not text:
        return []

    dates: list[date] = []
    for pattern, fmt in _DATE_FORMATS:
        for match in re.findall(pattern, text):
            try:
                dates.append(datetime.strptime(match, fmt).date())
            except ValueError:
                pass

    return list(dict.fromkeys(dates))


def _choose_event_date(text: str) -> date | None:
    """Выбирает ближайшую будущую или последнюю прошедшую дату."""
    dates = _extract_dates(text)
    if not dates:
        return None
    today = date.today()
    future = [d for d in dates if d >= today]
    return min(future) if future else max(dates)


def _days_left(event_date: date | None) -> int | None:
    """Считает количество дней до события."""
    if event_date is None:
        return None
    return (event_date - date.today()).days


# ---------------------------------------------------------------------------
# Расчёт критичности.
# ---------------------------------------------------------------------------

_STAGE_WEIGHT: dict[str, int] = {"main": 0, "secondary": 15, "commission": 25}


def _deadline_weight(days_left: int | None) -> int:
    """Вес срочности по количеству дней до события."""
    if days_left is None:
        return 5
    if days_left < 0:
        return 12
    if days_left <= 2:
        return 18
    if days_left <= 7:
        return 12
    if days_left <= 14:
        return 7
    if days_left <= 30:
        return 3
    return 0


def _risk_score(stage: str, days_left: int | None, failure_probability: float) -> float:
    """Итоговая критичность записи."""
    ml_weight = float(failure_probability or 0) * 70
    stage_w = _STAGE_WEIGHT.get(stage, 10)
    return round(min(100, ml_weight + stage_w + _deadline_weight(days_left)), 2)


def _risk_level(score: float) -> str:
    """Переводит число риска в человекочитаемый уровень: низкий/средний/высокий."""
    if score >= 60:
        return "высокий"
    if score >= 30:
        return "средний"
    return "низкий"


# ---------------------------------------------------------------------------
# Поля Excel-строки, которые «протягиваются» вниз при пустоте.
# ---------------------------------------------------------------------------

_CARRY_FIELDS: tuple[str, ...] = (
    "teacher",
    "groups",
    "date",
    "time",
    "room",
    "consultation_date",
    "consultation_time",
    "consultation_room",
)


def _extract_row_fields(data: dict) -> dict[str, str]:
    """Извлекает все поля из одной строки Excel по алиасам."""
    teacher = _get_value(data, EXCEL_COLUMN_ALIASES["teacher"])
    discipline = _get_value(data, EXCEL_COLUMN_ALIASES["discipline"])
    groups = _get_value(data, EXCEL_COLUMN_ALIASES["groups"])

    date_raw = _normalize_date(_get_value(data, EXCEL_COLUMN_ALIASES["date"]))
    time = _clean_text(_get_value(data, EXCEL_COLUMN_ALIASES["time"]))
    room = _get_value(data, EXCEL_COLUMN_ALIASES["room"])

    consultation_date = _normalize_date(
        _get_value(data, EXCEL_COLUMN_ALIASES["consultation_date"])
    )
    consultation_time = _clean_text(
        _get_value(data, EXCEL_COLUMN_ALIASES["consultation_time"])
    )
    consultation_room = _get_value(data, EXCEL_COLUMN_ALIASES["consultation_room"])

    return {
        "teacher": teacher,
        "discipline": discipline,
        "groups": groups,
        "date": date_raw,
        "time": time,
        "room": room,
        "consultation_date": consultation_date,
        "consultation_time": consultation_time,
        "consultation_room": consultation_room,
    }


# ---------------------------------------------------------------------------
# Главный API.
# ---------------------------------------------------------------------------

class DataNormalizer:
    """Превращает сырые строки Excel в нормализованные записи."""

    @staticmethod
    def normalize_rows(rows: list[dict]) -> list[dict]:
        """Нормализует все строки Excel."""
        normalized: list[dict] = []
        carry: dict[str, str] = dict.fromkeys(_CARRY_FIELDS, "")

        for row in rows:
            data = row.get("row_data", {})
            if "error" in data:
                continue

            fields = _extract_row_fields(data)

            # Протягиваем значения сверху вниз для всех полей, кроме discipline.
            for name in _CARRY_FIELDS:
                if fields[name]:
                    carry[name] = fields[name]
                else:
                    fields[name] = carry[name]

            discipline = fields["discipline"]
            if not discipline:
                continue
            if discipline.strip().lower() in HEADER_SKIP_VALUES:
                continue

            source_file = row.get("source_file", "")
            sheet_name = row.get("sheet_name", "")
            stage = _detect_attempt_stage(sheet_name, source_file)
            attempt_number = stage_attempt(stage)

            groups_list = _extract_groups(fields["groups"])
            groups_normalized = ",".join(groups_list)

            event_date = _choose_event_date(fields["date"])
            days_left = _days_left(event_date)

            risk_prediction = risk_classifier.predict(
                discipline=discipline,
                term=2,
                attempt_number=attempt_number,
            )
            score = _risk_score(stage, days_left, risk_prediction.failure_probability)

            normalized.append(
                {
                    "source_file": source_file,
                    "sheet_name": sheet_name,
                    "retake_type": stage_ru(stage),
                    "attempt_stage": stage,
                    "attempt_number": attempt_number,
                    "discipline": discipline,
                    "teacher": fields["teacher"],
                    "groups": fields["groups"],
                    "groups_list": groups_list,
                    "groups_normalized": groups_normalized,
                    "date": fields["date"],
                    "event_date": event_date,
                    "days_left": days_left,
                    "time": fields["time"],
                    "room": fields["room"],
                    "consultation_date": fields["consultation_date"],
                    "consultation_time": fields["consultation_time"],
                    "consultation_room": fields["consultation_room"],
                    "discipline_difficulty": risk_prediction.historical_failure_rate,
                    "discipline_code": risk_prediction.discipline_code,
                    "discipline_credits": risk_prediction.discipline_credits,
                    "historical_failure_rate": risk_prediction.historical_failure_rate,
                    "failure_probability": risk_prediction.failure_probability,
                    "predicted_final_result": risk_prediction.predicted_final_result,
                    "risk_score": score,
                    "risk_level": _risk_level(score),
                }
            )

        return dedupe_records(normalized, DEDUP_KEYS)
