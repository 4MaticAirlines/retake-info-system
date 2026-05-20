"""
Сервис сопоставления дисциплин из выписки с записями о пересдачах.
"""

import re

from app.utils.common import (
    DEDUP_KEYS,
    STAGE_SORT_ORDER,
    dedupe_records,
)


_MATCH_THRESHOLD = 0.45


def _normalize_text(text: str) -> str:
    """Приводит строку к виду, удобному для сравнения."""
    text = str(text).lower().strip()
    text = re.sub(r"[^a-zа-яё0-9\s-]", " ", text)
    return re.sub(r"\s+", " ", text)


def _token_similarity(left: str, right: str) -> float:
    """Похожесть двух названий по словам (коэффициент Жаккара)."""
    left_tokens = set(_normalize_text(left).split())
    right_tokens = set(_normalize_text(right).split())

    if not left_tokens or not right_tokens:
        return 0.0

    union = left_tokens | right_tokens
    return len(left_tokens & right_tokens) / len(union) if union else 0.0


def _discipline_matches(record_name: str, statement_name: str) -> bool:
    """Проверяет, что дисциплина из записи совпадает с дисциплиной выписки."""
    left = _normalize_text(record_name)
    right = _normalize_text(statement_name)

    if not left or not right:
        return False
    if left == right or left in right or right in left:
        return True

    return _token_similarity(left, right) >= _MATCH_THRESHOLD


def _record_groups(record: dict) -> list[str]:
    """Возвращает список групп из записи."""
    groups_list = record.get("groups_list", [])
    if groups_list:
        return [str(g).strip().upper() for g in groups_list if str(g).strip()]

    groups_normalized = str(record.get("groups_normalized", ""))
    if groups_normalized:
        return [item.strip().upper() for item in groups_normalized.split(",") if item.strip()]

    groups_raw = str(record.get("groups", ""))
    return [groups_raw.strip().upper()] if groups_raw else []


def _group_matches(record: dict, group: str) -> bool:
    """Проверяет, входит ли группа выписки в группы записи."""
    if not group:
        return False
    target = str(group).strip().upper()
    record_groups = _record_groups(record)
    return target in record_groups or "ВСЕ ГРУППЫ" in record_groups


class RetakeMatcher:
    """Сопоставляет записи о пересдачах с долгами из выписки."""

    @staticmethod
    def sort_records(records: list[dict]) -> list[dict]:
        """Сортирует записи: риск → этап → срочность → дата → время."""
        return sorted(
            records,
            key=lambda r: (
                -float(r.get("risk_score") or 0),
                STAGE_SORT_ORDER.get(str(r.get("attempt_stage", "")), 4),
                r.get("days_left") if r.get("days_left") is not None else 99999,
                str(r.get("date", "")),
                str(r.get("time", "")),
                str(r.get("teacher", "")),
            ),
        )

    @staticmethod
    def group_records_by_stage(records: list[dict]) -> dict[str, list[dict]]:
        """Раскладывает записи по вкладкам интерфейса."""
        grouped: dict[str, list[dict]] = {"main": [], "secondary": [], "commission": []}
        for record in records:
            stage = record.get("attempt_stage") or "secondary"
            if stage == "primary" or stage not in grouped:
                stage = "secondary"
            grouped[stage].append(record)
        return {stage: RetakeMatcher.sort_records(items) for stage, items in grouped.items()}

    @staticmethod
    def build_statement_results(
        records: list[dict],
        debts: list[dict],
        group: str = "",
    ) -> list[dict]:
        """Формирует результат поиска по выписке."""
        result: list[dict] = []

        for debt in debts:
            discipline = debt["discipline"]

            candidates = [r for r in records if _discipline_matches(r.get("discipline", ""), discipline)]
            candidates = dedupe_records(candidates, DEDUP_KEYS)
            group_filtered = [r for r in candidates if _group_matches(r, group)]

            final_matches = RetakeMatcher.sort_records(group_filtered or candidates)

            result.append(
                {
                    "discipline": discipline,
                    "debt_type": debt["debt_type"],
                    "status": debt["status"],
                    "matches": final_matches,
                    "used_group_filter": bool(group_filtered),
                }
            )

        return result
