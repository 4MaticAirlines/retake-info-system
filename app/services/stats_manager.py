"""
Сервис управления статистикой дисциплин для модели риска.

Принимает Excel/CSV-файл от кафедры с тем же форматом, что и
data/disciplines_template.xlsx:
  Код | Название дисциплины | Кредиты | Сложность (0–1) |
  Провал 1-й попытки | Провал 2-й попытки | Провал 3-й попытки (отчисление) |
  Кол-во студентов

После загрузки:
1. Валидирует структуру и содержимое.
2. Сохраняет файл в data/disciplines_template.xlsx.
3. Запускает симулятор и пересоздаёт data/history.csv.
4. Переобучает Random Forest.
"""
from __future__ import annotations

import importlib
import logging
import subprocess
import sys
from pathlib import Path

import pandas as pd

from app.core.config import BASE_DIR


logger = logging.getLogger(__name__)


REQUIRED_COLUMNS = [
    "Код",
    "Название дисциплины",
    "Кредиты",
    "Сложность (0–1)",
    "Провал 1-й попытки",
    "Провал 2-й попытки",
    "Провал 3-й попытки (отчисление)",
    "Кол-во студентов",
]

TEMPLATE_PATH = BASE_DIR / "data" / "disciplines_template.xlsx"
HISTORY_PATH = BASE_DIR / "data" / "history.csv"
GENERATOR_PATH = BASE_DIR / "scripts" / "generate_history.py"


class StatsValidationError(ValueError):
    """Ошибка валидации файла со статистикой."""


def _read_input(file_path: Path) -> pd.DataFrame:
    """Читает CSV или XLSX, возвращает DataFrame."""
    suffix = file_path.suffix.lower()
    if suffix == ".csv":
        return pd.read_csv(file_path)
    if suffix in (".xlsx", ".xls"):
        try:
            return pd.read_excel(file_path, sheet_name="Дисциплины")
        except Exception:
            return pd.read_excel(file_path)
    raise StatsValidationError(
        f"Неподдерживаемое расширение: {suffix}. Принимаются .csv, .xlsx, .xls"
    )


def _validate_dataframe(df: pd.DataFrame) -> None:
    """Проверяет структуру и значения файла."""
    missing = [col for col in REQUIRED_COLUMNS if col not in df.columns]
    if missing:
        raise StatsValidationError(
            f"В файле отсутствуют обязательные колонки: {', '.join(missing)}"
        )

    if df.empty:
        raise StatsValidationError("В файле нет строк с дисциплинами")

    # Проверяем заполненность ключевых полей.
    must_be_filled = [
        "Название дисциплины",
        "Кредиты",
        "Провал 1-й попытки",
        "Провал 2-й попытки",
        "Провал 3-й попытки (отчисление)",
        "Кол-во студентов",
    ]
    for col in must_be_filled:
        if df[col].isna().any():
            bad_rows = df[df[col].isna()].index.tolist()
            raise StatsValidationError(
                f"В колонке «{col}» есть пустые значения в строках: {[r + 2 for r in bad_rows[:5]]}"
            )

    # Проверяем диапазоны вероятностей.
    for col in (
        "Провал 1-й попытки",
        "Провал 2-й попытки",
        "Провал 3-й попытки (отчисление)",
    ):
        bad = df[(df[col] < 0) | (df[col] > 1)]
        if not bad.empty:
            raise StatsValidationError(
                f"В колонке «{col}» есть значения вне диапазона [0, 1] "
                f"в строках: {[r + 2 for r in bad.index.tolist()[:5]]}"
            )

    # Проверяем монотонность: Провал1 ≥ Провал2 ≥ Провал3.
    p1 = df["Провал 1-й попытки"]
    p2 = df["Провал 2-й попытки"]
    p3 = df["Провал 3-й попытки (отчисление)"]
    inversions = df[(p2 > p1) | (p3 > p2)]
    if not inversions.empty:
        rows = [r + 2 for r in inversions.index.tolist()[:5]]
        raise StatsValidationError(
            "Нарушен порядок вероятностей (Провал1 ≥ Провал2 ≥ Провал3) "
            f"в строках: {rows}. На следующую попытку идут только проваленные предыдущей."
        )

    # Проверяем количество студентов.
    if (df["Кол-во студентов"] < 10).any():
        raise StatsValidationError(
            "Минимальное количество студентов на дисциплину — 10"
        )


def save_stats_file(uploaded_path: Path) -> dict:
    """
    Сохраняет загруженный файл как новый шаблон и пересобирает модель.

    Возвращает словарь с информацией: количество дисциплин и метрики модели
   После переобучения.
    """
    # 1. Читаем и валидируем.
    df = _read_input(uploaded_path)
    _validate_dataframe(df)

    # 2. Сохраняем как новый disciplines_template.xlsx (всегда в xlsx).
    TEMPLATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(TEMPLATE_PATH, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="Дисциплины", index=False)

    discipline_count = len(df)
    logger.info("Шаблон обновлён: %d дисциплин", discipline_count)

    # 3. Пересоздаём history.csv через симулятор.
    logger.info("Запускаю симулятор для генерации history.csv...")
    result = subprocess.run(
        [sys.executable, str(GENERATOR_PATH)],
        capture_output=True, text=True, cwd=str(BASE_DIR),
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Ошибка при генерации history.csv: {result.stderr[-500:]}"
        )
    logger.info("history.csv пересоздан")

    # 4. Переобучаем Random Forest (создаём новый экземпляр).
    logger.info("Переобучаю Random Forest...")
    from app.services import risk_classifier as rc_module
    importlib.reload(rc_module)

    # Обновляем ссылку в discipline_risk, чтобы он использовал новую модель.
    from app.services import discipline_risk as dr_module
    importlib.reload(dr_module)

    metrics = rc_module.risk_classifier.metrics
    metrics_summary: dict = {}
    if metrics is not None:
        metrics_summary = {
            "accuracy": metrics.accuracy,
            "precision": metrics.precision,
            "recall": metrics.recall,
            "f1": metrics.f1,
            "roc_auc": metrics.roc_auc,
            "n_train": metrics.n_train,
            "n_test": metrics.n_test,
        }

    return {
        "discipline_count": discipline_count,
        "metrics": metrics_summary,
    }
