"""
Оценка качества Random Forest.

Считает метрики на тестовой выборке, делает 5-fold cross-validation
и сохраняет три графика в data/output/.

Запуск:
    python scripts/evaluate_model.py
"""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import (
    accuracy_score,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
    roc_curve,
)
from sklearn.model_selection import StratifiedKFold, cross_val_score, train_test_split


FEATURES = [
    "DisciplineCode",
    "Term",
    "AttemptNumber",
    "DisciplineCredits",
    "HistoricalFailureRate",
]
TARGET = "FinalResult"

HISTORY = PROJECT_ROOT / "data" / "history.csv"
OUTPUT = PROJECT_ROOT / "data" / "output"


def load_data() -> pd.DataFrame:
    """
    Load data.

    Возвращает:
        Результат работы функции.
    """
    df = pd.read_csv(HISTORY)
    for column in FEATURES + [TARGET]:
        df[column] = pd.to_numeric(df[column], errors="coerce")
    df = df.dropna(subset=FEATURES + [TARGET])
    for column in ("DisciplineCode", "Term", "AttemptNumber", "DisciplineCredits", TARGET):
        df[column] = df[column].astype(int)
    return df


def main() -> None:
    """
    Main.

    Возвращает:
        Результат работы функции.
    """
    df = load_data()
    print(f"Загружено строк: {len(df)}")
    print(f"Распределение классов: 0 (провал)={(df[TARGET] == 0).sum()}, "
          f"1 (сдал)={(df[TARGET] == 1).sum()}")
    print()

    X = df[FEATURES]
    y = df[TARGET]

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )

    model = RandomForestClassifier(
        n_estimators=120, max_depth=6, class_weight="balanced",
        random_state=42, n_jobs=-1,
    )
    model.fit(X_train, y_train)

    y_pred = model.predict(X_test)
    classes = list(model.classes_)
    y_proba = model.predict_proba(X_test)[:, classes.index(1)]

    print("=" * 60)
    print("Метрики на тестовой выборке (test_size = 20 %)")
    print("=" * 60)
    print(f"  Объём train:  {len(X_train)}")
    print(f"  Объём test:   {len(X_test)}")
    print(f"  Accuracy:     {accuracy_score(y_test, y_pred):.3f}")
    print(f"  Precision:    {precision_score(y_test, y_pred, zero_division=0):.3f}")
    print(f"  Recall:       {recall_score(y_test, y_pred, zero_division=0):.3f}")
    print(f"  F1:           {f1_score(y_test, y_pred, zero_division=0):.3f}")
    print(f"  ROC-AUC:      {roc_auc_score(y_test, y_proba):.3f}")
    print()

    print("=" * 60)
    print("5-fold cross-validation")
    print("=" * 60)
    cv_scores = cross_val_score(
        model, X, y,
        cv=StratifiedKFold(n_splits=5, shuffle=True, random_state=42),
        scoring="roc_auc",
        n_jobs=-1,
    )
    print(f"  ROC-AUC по фолдам: {[f'{s:.3f}' for s in cv_scores]}")
    print(f"  Среднее:           {cv_scores.mean():.3f}")
    print(f"  Стандартное откл.: {cv_scores.std():.3f}")
    print()

    OUTPUT.mkdir(parents=True, exist_ok=True)

    # --- ROC-кривая ---
    fpr, tpr, _ = roc_curve(y_test, y_proba)
    auc = roc_auc_score(y_test, y_proba)

    plt.figure(figsize=(7, 6))
    plt.plot(fpr, tpr, color="#2D5C8F", lw=2.0, label=f"Random Forest (AUC = {auc:.3f})")
    plt.plot([0, 1], [0, 1], "k--", lw=1.0, label="Случайный классификатор")
    plt.xlabel("False Positive Rate", fontsize=11)
    plt.ylabel("True Positive Rate", fontsize=11)
    plt.title("ROC-кривая классификатора риска", fontsize=12, fontweight="bold")
    plt.legend(loc="lower right", fontsize=10)
    plt.grid(True, linestyle=":", alpha=0.5)
    plt.tight_layout()
    plt.savefig(OUTPUT / "roc_curve.png", dpi=180, facecolor="white")
    plt.close()
    print(f"Сохранено: {OUTPUT / 'roc_curve.png'}")

    # --- Матрица ошибок ---
    cm = confusion_matrix(y_test, y_pred)
    fig, ax = plt.subplots(figsize=(6, 5))
    ax.imshow(cm, cmap="Blues", interpolation="nearest")
    ax.set_xticks([0, 1])
    ax.set_yticks([0, 1])
    ax.set_xticklabels(["Провал (0)", "Сдал (1)"])
    ax.set_yticklabels(["Провал (0)", "Сдал (1)"])
    ax.set_xlabel("Предсказание", fontsize=11)
    ax.set_ylabel("Истинный класс", fontsize=11)
    ax.set_title("Матрица ошибок", fontsize=12, fontweight="bold")
    for i in range(cm.shape[0]):
        for j in range(cm.shape[1]):
            ax.text(
                j, i, f"{cm[i, j]}",
                ha="center", va="center",
                color="white" if cm[i, j] > cm.max() / 2 else "black",
                fontsize=14, fontweight="bold",
            )
    plt.tight_layout()
    plt.savefig(OUTPUT / "confusion_matrix.png", dpi=180, facecolor="white")
    plt.close()
    print(f"Сохранено: {OUTPUT / 'confusion_matrix.png'}")

    # --- Важность признаков ---
    importances = model.feature_importances_
    indices = np.argsort(importances)[::-1]
    labels_ru = {
        "DisciplineCode": "Код дисциплины",
        "Term": "Семестр",
        "AttemptNumber": "Номер попытки",
        "DisciplineCredits": "Кредиты",
        "HistoricalFailureRate": "Ист. доля провалов",
    }
    sorted_labels = [labels_ru.get(FEATURES[i], FEATURES[i]) for i in indices]
    sorted_values = importances[indices]

    plt.figure(figsize=(8, 4.5))
    bars = plt.barh(range(len(sorted_labels)), sorted_values,
                    color="#2D5C8F", edgecolor="black", lw=0.7)
    plt.yticks(range(len(sorted_labels)), sorted_labels, fontsize=10)
    plt.xlabel("Важность признака", fontsize=11)
    plt.title("Важность признаков (Random Forest)", fontsize=12, fontweight="bold")
    plt.grid(True, axis="x", linestyle=":", alpha=0.5)
    plt.gca().invert_yaxis()
    for bar, value in zip(bars, sorted_values):
        plt.text(value + 0.005, bar.get_y() + bar.get_height() / 2,
                 f"{value:.3f}", va="center", fontsize=9)
    plt.tight_layout()
    plt.savefig(OUTPUT / "feature_importances.png", dpi=180, facecolor="white")
    plt.close()
    print(f"Сохранено: {OUTPUT / 'feature_importances.png'}")

    print()
    print("Готово. Графики сохранены в data/output/")


if __name__ == "__main__":
    main()
