"""
Сервис поиска записей о пересдачах по учебной группе.
"""

from app.services.retake_matcher import RetakeMatcher
from app.utils.common import DEDUP_KEYS, dedupe_records


def _normalize(value: str) -> str:
    """
    Normalize.

    Аргументы:
        value: параметр функции.

    Возвращает:
        Результат работы функции.
    """
    return str(value).strip().upper()


def _is_exact_query(query: str) -> bool:
    """Запрос считается точным, если содержит >= 2 дефисов."""
    return query.count("-") >= 2


def _group_matches(query: str, candidate: str) -> bool:
    """Проверяет, подходит ли группа candidate под запрос query."""
    query, candidate = _normalize(query), _normalize(candidate)
    if not query or not candidate:
        return False
    if candidate == "ВСЕ ГРУППЫ":
        return True
    if _is_exact_query(query):
        return query == candidate
    return candidate == query or candidate.startswith(query + "-")


class GroupSearch:
    """Поиск записей по названию учебной группы."""

    @staticmethod
    def find_by_group(records: list[dict], group_name: str) -> list[dict]:
        """Возвращает отсортированный список записей для заданной группы."""
        query = _normalize(group_name)
        filtered = [
            record
            for record in records
            if any(_group_matches(query, g) for g in (_normalize(x) for x in record.get("groups_list", [])))
        ]
        return RetakeMatcher.sort_records(dedupe_records(filtered, DEDUP_KEYS))
