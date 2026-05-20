"""
Симулятор обучающего датасета history.csv.

Принципы работы:
1. Каждый студент получает скрытый параметр «способности» ∈ [0, 1].
2. Этот параметр в выходной CSV НЕ попадает — Random Forest его не видит.
3. Студент пытается сдать дисциплину. Провал/успех зависит от способностей
  И сложности дисциплины с добавлением шума.
4. Провалившие идут на пересдачу, потом на комиссию.
5. На каждой следующей попытке вероятность провала чуть ниже (студент готовится).
6. Каждая попытка превращается в одну строку CSV.

Запуск:
    python scripts/generate_history.py
"""
from __future__ import annotations

import csv
import random
from pathlib import Path

import pandas as pd


# Параметры симулятора.
RANDOM_SEED = 42
NOISE_STD = 0.10            # стандартное отклонение шума при сдаче
ATTEMPT_PREP_BONUS = 0.05   # сложность снижается на каждой следующей попытке (студент готовится)
ABILITY_MEAN = 0.55          # средние способности студентов
ABILITY_STD = 0.18           # разброс способностей


PROJECT_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_PATH = PROJECT_ROOT / "data" / "disciplines_template.xlsx"
OUTPUT_PATH = PROJECT_ROOT / "data" / "history.csv"


def load_template() -> pd.DataFrame:
    """Читает Excel-шаблон с дисциплинами."""
    df = pd.read_excel(TEMPLATE_PATH, sheet_name="Дисциплины")
    return df


def sample_ability() -> float:
    """Скрытая переменная — способности студента."""
    return max(0.0, min(1.0, random.gauss(ABILITY_MEAN, ABILITY_STD)))


def attempt_fails(ability: float, difficulty: float, attempt: int) -> bool:
    """
    Симуляция одной попытки сдачи.

    Студент проваливает, если способности (с шумом) ниже сложности
    (с поправкой на подготовку к попытке).
    """
    # На пересдачах студент готовится — сложность снижается.
    effective_difficulty = max(0.05, difficulty - (attempt - 1) * ATTEMPT_PREP_BONUS)
    noisy_ability = ability + random.gauss(0, NOISE_STD)
    return noisy_ability < effective_difficulty


def calibrate_difficulty(target_p1: float) -> float:
    """
    Подбирает параметр difficulty так, чтобы P(провал 1-й попытки) ≈ target_p1.

    Делаем это численно — гоняем 5000 студентов с разными значениями difficulty
    и берём ту, где доля провалов ближе всего к цели.
    """
    best_diff = 0.5
    best_err = 999.0
    for diff_candidate in [i / 100 for i in range(5, 96)]:
        fails = 0
        n = 3000
        for _ in range(n):
            ab = sample_ability()
            if attempt_fails(ab, diff_candidate, attempt=1):
                fails += 1
        rate = fails / n
        err = abs(rate - target_p1)
        if err < best_err:
            best_err = err
            best_diff = diff_candidate
    return best_diff


def generate_for_discipline(
    discipline_code: int,
    target_p1: float,
    target_p2: float,
    target_p3: float,
    credits: int,
    historical_failure_rate: float,
    students_count: int,
    student_id_start: int,
) -> tuple[list[dict], int]:
    """
    Генерирует записи для одной дисциплины.

    Возвращает (строки CSV, следующий свободный StudentID).
    """
    # Подбираем difficulty под целевую долю провала первой попытки.
    difficulty = calibrate_difficulty(target_p1)

    rows: list[dict] = []
    next_id = student_id_start

    # На второй и третьей попытке вероятности должны соответствовать целевым
    # p2/p1 и p3/p2 — это условные вероятности «провалил, если пришёл».
    cond_p2 = target_p2 / target_p1 if target_p1 > 0 else 0.0
    cond_p3 = target_p3 / target_p2 if target_p2 > 0 else 0.0

    for _ in range(students_count):
        ability = sample_ability()
        student_id = next_id
        next_id += 1

        # Семестр выбирается случайно (1..8) — для разнообразия признака.
        term = random.randint(1, 8)

        # --- Попытка 1 ---
        failed_1 = attempt_fails(ability, difficulty, attempt=1)
        rows.append({
            "StudentID": student_id,
            "DisciplineCode": discipline_code,
            "Term": term,
            "AttemptNumber": 1,
            "DisciplineCredits": credits,
            "HistoricalFailureRate": historical_failure_rate,
            "FinalResult": 0 if failed_1 else 1,
        })

        if not failed_1:
            continue

        # --- Попытка 2 ---
        # Подгоняем «эффективную сложность» так, чтобы условная вероятность
        # P(провал 2 | провал 1) ≈ cond_p2.
        # Делаем это через сравнение со случайным числом, а не пересчёт ability.
        failed_2 = random.random() < cond_p2
        rows.append({
            "StudentID": student_id,
            "DisciplineCode": discipline_code,
            "Term": term,
            "AttemptNumber": 2,
            "DisciplineCredits": credits,
            "HistoricalFailureRate": historical_failure_rate,
            "FinalResult": 0 if failed_2 else 1,
        })

        if not failed_2:
            continue

        # --- Попытка 3 (комиссия) ---
        failed_3 = random.random() < cond_p3
        rows.append({
            "StudentID": student_id,
            "DisciplineCode": discipline_code,
            "Term": term,
            "AttemptNumber": 3,
            "DisciplineCredits": credits,
            "HistoricalFailureRate": historical_failure_rate,
            "FinalResult": 0 if failed_3 else 1,
        })

    return rows, next_id


def main() -> None:
    """
    Main.

    Возвращает:
        Результат работы функции.
    """
    random.seed(RANDOM_SEED)
    template = load_template()

    print(f"Прочитан шаблон: {len(template)} дисциплин")
    print(f"Целевой размер датасета: ~{int(template['Кол-во студентов'].sum() * 1.5)} строк")
    print()

    all_rows: list[dict] = []
    next_student_id = 10001

    for _, row in template.iterrows():
        code = int(row["Код"])
        name = row["Название дисциплины"]
        credits = int(row["Кредиты"])
        p1 = float(row["Провал 1-й попытки"])
        p2 = float(row["Провал 2-й попытки"])
        p3 = float(row["Провал 3-й попытки (отчисление)"])
        students_count = int(row["Кол-во студентов"])

        # HistoricalFailureRate = P1 (доля провалов первой попытки)
        # это согласуется с тем, что было в исходном CSV проекта.
        rows, next_student_id = generate_for_discipline(
            discipline_code=code,
            target_p1=p1,
            target_p2=p2,
            target_p3=p3,
            credits=credits,
            historical_failure_rate=round(p1, 3),
            students_count=students_count,
            student_id_start=next_student_id,
        )
        all_rows.extend(rows)
        print(f"  [{code:>2}] {name[:50]:<50} → {len(rows):>5} строк "
              f"(P1={p1:.2f}, P2={p2:.2f}, P3={p3:.2f})")

    # --- Контроль реализованных частот ---
    df_out = pd.DataFrame(all_rows)
    print()
    print(f"Всего строк сгенерировано: {len(df_out)}")
    overall_fail_rate = (df_out["FinalResult"] == 0).mean()
    print(f"Общая доля провалов: {overall_fail_rate:.3f}")

    # Контрольная сверка
    print("\nКонтрольная сверка реализованных и целевых вероятностей:")
    print(f"  {'Код':>4} {'P1 цель/факт':>14} {'P2 цель/факт':>14} {'P3 цель/факт':>14}")
    for _, row in template.head(10).iterrows():
        code = int(row["Код"])
        sub = df_out[df_out["DisciplineCode"] == code]

        att1 = sub[sub["AttemptNumber"] == 1]
        att2 = sub[sub["AttemptNumber"] == 2]
        att3 = sub[sub["AttemptNumber"] == 3]

        p1_real = (att1["FinalResult"] == 0).mean() if len(att1) else 0.0
        p2_real = (att2["FinalResult"] == 0).mean() if len(att2) else 0.0
        p3_real = (att3["FinalResult"] == 0).mean() if len(att3) else 0.0

        # Целевые на условном уровне: P(провал 2 | пришёл на 2) = P2/P1, и т.д.
        target_p1 = float(row["Провал 1-й попытки"])
        target_p2_cond = float(row["Провал 2-й попытки"]) / target_p1 if target_p1 else 0
        target_p3_cond = (
            float(row["Провал 3-й попытки (отчисление)"]) / float(row["Провал 2-й попытки"])
            if float(row["Провал 2-й попытки"]) else 0
        )

        print(
            f"  {code:>4} "
            f"{target_p1:.2f}/{p1_real:.2f}      "
            f"{target_p2_cond:.2f}/{p2_real:.2f}      "
            f"{target_p3_cond:.2f}/{p3_real:.2f}"
        )

    # --- Записываем CSV ---
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    df_out.to_csv(OUTPUT_PATH, index=False)
    print(f"\nДатасет записан: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
