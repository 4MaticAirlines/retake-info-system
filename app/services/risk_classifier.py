"""
ML-классификация риска незакрытия задолженности.

Модель: Random Forest на 5 признаках:
- DisciplineCode       — числовой код дисциплины
- Term                 — семестр (1..8)
- AttemptNumber        — номер попытки (1, 2, 3)
- DisciplineCredits    — зачётные единицы
- HistoricalFailureRate — историческая доля провалов первой попытки

Целевая переменная FinalResult:
- 1 — задолженность ликвидирована (сдал)
- 0 — задолженность не ликвидирована (провалил)

Модель обучается при старте на data/history.csv. Если файл отсутствует
или scikit-learn недоступен — fallback на эвристику.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

try:
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.metrics import (
        accuracy_score,
        f1_score,
        precision_score,
        recall_score,
        roc_auc_score,
    )
    from sklearn.model_selection import train_test_split
except Exception:  # pragma: no cover
    RandomForestClassifier = None


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ModelMetrics:
    """Метрики обученной модели на тестовой выборке."""

    accuracy: float
    precision: float
    recall: float
    f1: float
    roc_auc: float
    n_train: int
    n_test: int


@dataclass(frozen=True)
class RiskPrediction:
    """Результат ML-оценки риска для одной задолженности."""

    discipline_code: int
    discipline_credits: int
    historical_failure_rate: float
    failure_probability: float
    predicted_final_result: int


_FEATURES = [
    "DisciplineCode",
    "Term",
    "AttemptNumber",
    "DisciplineCredits",
    "HistoricalFailureRate",
]
_TARGET = "FinalResult"
_DEFAULT_DIFFICULTY = 0.35


def _safe_int(value: Any, default: int = 0) -> int:
    """
    Safe int.

    Аргументы:
        value: параметр функции.
        default: параметр функции.

    Возвращает:
        Результат работы функции.
    """
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_float(value: Any, default: float = 0.0) -> float:
    """
    Safe float.

    Аргументы:
        value: параметр функции.
        default: параметр функции.

    Возвращает:
        Результат работы функции.
    """
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


class RiskClassifier:
    """Random Forest классификатор риска незакрытия задолженности."""

    def __init__(
        self,
        history_path: str | Path = "data/history.csv",
        template_path: str | Path = "data/disciplines_template.xlsx",
    ) -> None:
        """
         Init  .

        Аргументы:
            history_path: параметр функции.
            template_path: параметр функции.

        Возвращает:
            Результат работы функции.
        """
        self.history_path = Path(history_path)
        self.template_path = Path(template_path)
        self.model: Any | None = None
        self.is_trained = False
        self.metrics: ModelMetrics | None = None

        # Маппинги дисциплин (имя → код, код → данные).
        self.name_to_code: dict[str, int] = {}
        self.discipline_codes: list[int] = list(range(10))
        self.failure_rate_by_code: dict[int, float] = {}
        self.credits_by_code: dict[int, int] = {}

        self._load_template_mapping()
        self._load_and_train()

    # -----------------------------------------------------------------
    # Загрузка шаблона дисциплин.
    # -----------------------------------------------------------------

    def _load_template_mapping(self) -> None:
        """Читает Excel-шаблон, чтобы знать соответствие имя → код."""
        if not self.template_path.exists():
            return

        try:
            df = pd.read_excel(self.template_path, sheet_name="Дисциплины")
        except Exception:
            return

        for _, row in df.iterrows():
            name = str(row.get("Название дисциплины", "")).strip()
            code = row.get("Код")
            if name and pd.notna(code):
                normalized = name.lower().replace("ё", "е")
                self.name_to_code[normalized] = int(code)

    # -----------------------------------------------------------------
    # Загрузка и обучение модели.
    # -----------------------------------------------------------------

    def _load_history(self) -> pd.DataFrame | None:
        """
        Load history.

        Возвращает:
            Результат работы функции.
        """
        if not self.history_path.exists():
            return None

        df = pd.read_csv(self.history_path)
        if not set(_FEATURES + [_TARGET]).issubset(df.columns):
            return None

        for column in _FEATURES + [_TARGET]:
            df[column] = pd.to_numeric(df[column], errors="coerce")

        df = df.dropna(subset=_FEATURES + [_TARGET])
        if df.empty:
            return None

        for column in ("DisciplineCode", "Term", "AttemptNumber", "DisciplineCredits", _TARGET):
            df[column] = df[column].astype(int)

        return df

    def _load_and_train(self) -> None:
        """
        Load and train.

        Возвращает:
            Результат работы функции.
        """
        df = self._load_history()
        if df is None:
            logger.warning("history.csv не найден или пуст — модель не обучена")
            return

        # Собираем справочники по коду дисциплины.
        self.discipline_codes = sorted(df["DisciplineCode"].unique().tolist())
        self.failure_rate_by_code = (
            df.groupby("DisciplineCode")["HistoricalFailureRate"].mean().round(3).to_dict()
        )
        self.credits_by_code = (
            df.groupby("DisciplineCode")["DisciplineCredits"].median().round().astype(int).to_dict()
        )

        if RandomForestClassifier is None or len(set(df[_TARGET].tolist())) < 2:
            logger.warning("scikit-learn недоступен или в данных только один класс")
            return

        X = df[_FEATURES]
        y = df[_TARGET]

        # Train/test split 80/20 для оценки качества.
        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=0.2, random_state=42, stratify=y
        )

        model = RandomForestClassifier(
            n_estimators=120,
            max_depth=6,
            class_weight="balanced",
            random_state=42,
            n_jobs=-1,
        )
        model.fit(X_train, y_train)

        # Метрики на тесте.
        y_pred = model.predict(X_test)
        y_proba = model.predict_proba(X_test)[:, list(model.classes_).index(1)] \
            if 1 in model.classes_ else model.predict_proba(X_test)[:, 0]

        self.metrics = ModelMetrics(
            accuracy=round(accuracy_score(y_test, y_pred), 3),
            precision=round(precision_score(y_test, y_pred, zero_division=0), 3),
            recall=round(recall_score(y_test, y_pred, zero_division=0), 3),
            f1=round(f1_score(y_test, y_pred, zero_division=0), 3),
            roc_auc=round(roc_auc_score(y_test, y_proba), 3),
            n_train=len(X_train),
            n_test=len(X_test),
        )

        self.model = model
        self.is_trained = True

        logger.info(
            "Random Forest обучен: train=%d, test=%d, accuracy=%.3f, "
            "precision=%.3f, recall=%.3f, F1=%.3f, AUC=%.3f",
            self.metrics.n_train,
            self.metrics.n_test,
            self.metrics.accuracy,
            self.metrics.precision,
            self.metrics.recall,
            self.metrics.f1,
            self.metrics.roc_auc,
        )

    # -----------------------------------------------------------------
    # Резолверы признаков.
    # -----------------------------------------------------------------

    def discipline_code(self, discipline: str) -> int:
        """Возвращает код дисциплины: сначала по имени, потом по хешу."""
        if not discipline:
            return self.discipline_codes[0]

        normalized = str(discipline).lower().strip().replace("ё", "е")

        # Точное совпадение.
        if normalized in self.name_to_code:
            return self.name_to_code[normalized]

        # Подстрочное совпадение (если в Excel «Математический анализ»,
        # а в PDF «Мат анализ»).
        for stored_name, code in self.name_to_code.items():
            if normalized in stored_name or stored_name in normalized:
                return code

        # Fallback — стабильный хеш.
        digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        return self.discipline_codes[int(digest, 16) % len(self.discipline_codes)]

    @staticmethod
    def _credits_from_difficulty(difficulty: float) -> int:
        """
        Credits from difficulty.

        Аргументы:
            difficulty: параметр функции.

        Возвращает:
            Результат работы функции.
        """
        difficulty = max(0.0, min(1.0, difficulty))
        if difficulty >= 0.7:
            return 5
        if difficulty >= 0.5:
            return 4
        return 2

    def _resolve_credits(self, code: int, difficulty: float) -> int:
        """
        Resolve credits.

        Аргументы:
            code: параметр функции.
            difficulty: параметр функции.

        Возвращает:
            Результат работы функции.
        """
        return self.credits_by_code.get(code, self._credits_from_difficulty(difficulty))

    def _resolve_failure_rate(self, code: int, difficulty: float) -> float:
        """
        Resolve failure rate.

        Аргументы:
            code: параметр функции.
            difficulty: параметр функции.

        Возвращает:
            Результат работы функции.
        """
        return self.failure_rate_by_code.get(code, difficulty)

    # -----------------------------------------------------------------
    # Предсказание.
    # -----------------------------------------------------------------

    def predict(
        self,
        *,
        discipline: str,
        term: int = 2,
        attempt_number: int = 1,
        discipline_difficulty: float = _DEFAULT_DIFFICULTY,
    ) -> RiskPrediction:
        """Возвращает вероятность незакрытия задолженности (класс 0)."""
        difficulty = _safe_float(discipline_difficulty, _DEFAULT_DIFFICULTY)
        code = self.discipline_code(discipline)
        credits = self._resolve_credits(code, difficulty)
        historical_failure_rate = self._resolve_failure_rate(code, difficulty)

        features = pd.DataFrame(
            [
                {
                    "DisciplineCode": code,
                    "Term": _safe_int(term, 2),
                    "AttemptNumber": _safe_int(attempt_number, 1),
                    "DisciplineCredits": int(credits),
                    "HistoricalFailureRate": float(historical_failure_rate),
                }
            ]
        )

        if self.is_trained and self.model is not None:
            probabilities = self.model.predict_proba(features)[0]
            classes = list(self.model.classes_)
            if 0 in classes:
                failure_probability = float(probabilities[classes.index(0)])
            else:
                failure_probability = 1.0 - float(max(probabilities))
            predicted_final_result = int(self.model.predict(features)[0])
        else:
            # Резервная формула.
            failure_probability = min(
                0.95,
                max(
                    0.05,
                    0.15
                    + historical_failure_rate * 0.65
                    + max(0, _safe_int(attempt_number, 1) - 1) * 0.12,
                ),
            )
            predicted_final_result = 0 if failure_probability >= 0.5 else 1

        return RiskPrediction(
            discipline_code=code,
            discipline_credits=int(credits),
            historical_failure_rate=round(float(historical_failure_rate), 3),
            failure_probability=round(float(failure_probability), 3),
            predicted_final_result=predicted_final_result,
        )


risk_classifier = RiskClassifier()
