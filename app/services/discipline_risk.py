"""
Классификация риска отчисления для дисциплин из выписки студента.

Двухуровневая модель:

1. Random Forest даёт P(не закроет текущую попытку) — обучен на data/history.csv.

2. Регламентное произведение:
   По уставу вуза студент отчисляется ТОЛЬКО после провала комиссии (попытки 3).
   Значит риск отчисления = произведение P(провала) по всем оставшимся попыткам:

       P(отчисление | попытка = a) = ∏ P(провала_k) для k = a..3

   Это значит:
   - На попытке 1 (сессия): P_отч = p1 × p2 × p3 (надо провалить все 3)
   - На попытке 2 (пересдача): P_отч = p2 × p3 (надо провалить ещё 2)
   - На попытке 3 (комиссия): P_отч = p3 (один провал = отчисление)
"""

from dataclasses import dataclass

from app.services.risk_classifier import risk_classifier


# Маппинг статуса задолженности из выписки в номер попытки.
# По регламенту: «неявка» и «неудовлетворительно/не зачтено» = студент уже
# использовал ≥ 1 попытку. На момент выписки он ИДЁТ на следующую попытку.
# Минимальная следующая попытка — вторая (первичная пересдача).
_STATUS_TO_ATTEMPT: dict[str, int] = {
    "неявка": 2,
    "неудовлетворительно": 2,
    "не зачтено": 2,
}


# Пороги вероятности отчисления — три уровня.
# Категории определяются по итоговому P(отчисления):
#   низкий   — < 0.30
#   средний  — 0.30..0.60
#   высокий  — >= 0.60
_RISK_THRESHOLDS: tuple[tuple[float, str], ...] = (
    (0.72, "высокий"),
    (0.65, "средний"),
    (0.00, "низкий"),
)


def _risk_category(expulsion_probability: float) -> str:
    """
    Risk category.

    Аргументы:
        expulsion_probability: параметр функции.

    Возвращает:
        Результат работы функции.
    """
    for threshold, category in _RISK_THRESHOLDS:
        if expulsion_probability >= threshold:
            return category
    return "низкий"


@dataclass(frozen=True)
class DisciplineRisk:
    """Результат классификации одной задолженности студента."""

    discipline: str
    debt_type: str
    status: str
    attempt_number: int
    # Вероятность провалить ТЕКУЩУЮ попытку (от Random Forest).
    failure_probability: float
    # Вероятность дойти до отчисления (произведение по оставшимся попыткам).
    expulsion_probability: float
    risk_category: str
    historical_failure_rate: float
    discipline_code: int
    discipline_credits: int
    predicted_final_result: int

    def to_dict(self) -> dict:
        """
        To dict.

        Возвращает:
            Результат работы функции.
        """
        return {
            "discipline": self.discipline,
            "debt_type": self.debt_type,
            "status": self.status,
            "attempt_number": self.attempt_number,
            "failure_probability": self.failure_probability,
            "expulsion_probability": self.expulsion_probability,
            "risk_category": self.risk_category,
            "historical_failure_rate": self.historical_failure_rate,
            "discipline_code": self.discipline_code,
            "discipline_credits": self.discipline_credits,
            "predicted_final_result": self.predicted_final_result,
        }


_CATEGORY_RANK: dict[str, int] = {
    "высокий": 0,
    "средний": 1,
    "низкий": 2,
}


class DisciplineRiskClassifier:
    """Классификатор риска отчисления для дисциплин из выписки."""

    @staticmethod
    def _compute_expulsion_probability(
        discipline: str,
        term: int,
        current_attempt: int,
    ) -> tuple[float, float]:
        """
        Считает (P(провала текущей попытки), P(отчисления)).

        P(отчисления) = произведение P(провала) для всех оставшихся попыток
        от current_attempt до 3 включительно.
        """
        current_failure = 0.0
        expulsion = 1.0

        for attempt in range(current_attempt, 4):
            prediction = risk_classifier.predict(
                discipline=discipline,
                term=term,
                attempt_number=attempt,
            )
            if attempt == current_attempt:
                current_failure = prediction.failure_probability
            expulsion *= prediction.failure_probability

        return current_failure, expulsion

    @staticmethod
    def classify(debt: dict, term: int = 2) -> DisciplineRisk:
        """
        Classify.

        Аргументы:
            debt: параметр функции.
            term: параметр функции.

        Возвращает:
            Результат работы функции.
        """
        discipline = str(debt.get("discipline", ""))
        debt_type = str(debt.get("debt_type", ""))
        status_raw = str(debt.get("status", ""))
        status = status_raw.lower().strip()

        attempt_number = _STATUS_TO_ATTEMPT.get(status, 2)

        # Берём базовые признаки для текущей попытки (нужны для других полей).
        base = risk_classifier.predict(
            discipline=discipline,
            term=term,
            attempt_number=attempt_number,
        )

        # Считаем P(провала текущей попытки) и P(отчисления).
        failure_probability, expulsion_probability = (
            DisciplineRiskClassifier._compute_expulsion_probability(
                discipline=discipline,
                term=term,
                current_attempt=attempt_number,
            )
        )

        return DisciplineRisk(
            discipline=discipline,
            debt_type=debt_type,
            status=status_raw,
            attempt_number=attempt_number,
            failure_probability=round(failure_probability, 3),
            expulsion_probability=round(expulsion_probability, 3),
            risk_category=_risk_category(expulsion_probability),
            historical_failure_rate=base.historical_failure_rate,
            discipline_code=base.discipline_code,
            discipline_credits=base.discipline_credits,
            predicted_final_result=base.predicted_final_result,
        )

    @classmethod
    def classify_many(cls, debts: list[dict], term: int = 2) -> list[DisciplineRisk]:
        """Классифицирует все задолженности и сортирует от опасных к безопасным."""
        classified = [cls.classify(debt, term=term) for debt in debts]
        return sorted(
            classified,
            key=lambda item: (
                _CATEGORY_RANK.get(item.risk_category, 99),
                -item.expulsion_probability,
                item.discipline,
            ),
        )
