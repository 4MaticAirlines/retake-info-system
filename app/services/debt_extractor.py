"""
Сервис извлечения задолженностей из PDF-выписки.

Главный принцип этой версии:
- не режем предмет на куски по словам;
- работаем по записям вида "одна строка учебной карточки = одна запись";
- извлекаем:
  - дисциплину,
  - тип задолженности,
  - статус.
"""

import re

from app.core.constants import BAD_DEBT_MARKERS, BROKEN_MARKER_REPLACEMENTS


class DebtExtractor:
    """
    Извлекает долги из выписки.
    """

    # Человекочитаемые названия типов задолженности.
    DEBT_TYPE_EXAM = "экзамен"
    DEBT_TYPE_CREDIT = "зачёт"
    DEBT_TYPE_COURSEWORK = "курсовая работа"

    # Допустимые значения в колонках оценивания.
    # Они нужны, чтобы понять структуру записи из выписки.
    GRADE_VALUES = {
        "-",
        "отлично",
        "хорошо",
        "удовлетворительно",
        "неудовлетворительно",
        "зачтено",
        "не зачтено",
        "неявка",
    }

    @staticmethod
    def _normalize_text(text: str) -> str:
        """
        Нормализует текст после извлечения из PDF:
        - исправляет известные разрывы слов;
        - убирает лишние пробелы;
        - делает текст удобным для построчного разбора.
        """
        text = text.replace("\r", "\n")

        for old_value, new_value in BROKEN_MARKER_REPLACEMENTS.items():
            text = text.replace(old_value, new_value)

        # Склеиваем слова, разорванные дефисом и переносом.
        text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)

        # Исправляем типичные разрывы оценок из PDF.
        replacements = {
            r"У\s*довлетворител\s*ьно": "Удовлетворительно",
            r"Не\s*удовлетворит\s*ельно": "Неудовлетворительно",
            r"Не\s*удовлетвори\s*тельно": "Неудовлетворительно",
            r"не\s*удовлетворит\s*ельно": "неудовлетворительно",
            r"не\s*удовлетвори\s*тельно": "неудовлетворительно",
            r"не\s*зачтено": "не зачтено",
        }

        for pattern, replacement in replacements.items():
            text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)

        # Убираем повторы пробелов.
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{2,}", "\n", text)

        return text.strip()

    @staticmethod
    def _extract_group(text: str) -> str:
        """
        Извлекает группу студента из выписки.
        """
        patterns = [
            r"академическая группа:\s*([A-Za-zА-Яа-яЁё0-9\-]+)",
            r"группа:\s*([A-Za-zА-Яа-яЁё0-9\-]+)",
        ]

        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(1).strip().upper()

        return ""

    @staticmethod
    def _find_marker(value: str) -> str:
        """
        Возвращает найденный маркер задолженности, если он есть.
        """
        lowered = value.lower()
        for marker in BAD_DEBT_MARKERS:
            if marker in lowered:
                return marker
        return ""

    @staticmethod
    def _normalize_grade_value(value: str) -> str:
        """
        Нормализует значение оценки/статуса:
        - убирает лишние пробелы;
        - переводит в нижний регистр.
        """
        value = str(value).strip().lower()
        value = re.sub(r"\s+", " ", value)
        return value

    @staticmethod
    def _is_grade_value(value: str) -> bool:
        """
        Проверяет, может ли строка быть значением колонки оценивания.
        """
        return DebtExtractor._normalize_grade_value(value) in DebtExtractor.GRADE_VALUES

    @staticmethod
    def _is_service_line(line: str) -> bool:
        """
        Отбрасывает служебные строки, которые не являются записями дисциплин.
        """
        stripped = line.strip()

        if not stripped:
            return True

        service_patterns = [
            r"^№$",
            r"^Наименование дисциплины",
            r"^по учебному плану",
            r"^Кол-во$",
            r"^часов ЗЕТ$",
            r"^Оценка$",
            r"^экзамен$",
            r"^зачет$",
            r"^зачёт$",
            r"^курсовая",
            r"^1 2 3 4 5 6 7 8$",
            r"^\d{4}\s*-\s*\d{4}\s+учебный год$",
            r"^(первый|второй|третий|четвертый|четвёртый|пятый|шестой|седьмой|восьмой)\s+семестр$",
            r"^Средний балл",
            r"^Приказ о зачислении",
            r"^Директор",
            r"^Дата подписи",
            r"^Сертификат:",
            r"^Кем выдан:",
            r"^Владелец:",
            r"^Действителен:",
        ]

        for pattern in service_patterns:
            if re.search(pattern, stripped, flags=re.IGNORECASE):
                return True

        return False

    @staticmethod
    def _build_record_lines(text: str) -> list[str]:
        """
        Собирает логические записи из текста выписки.

        В PDF одна запись может быть разбита на несколько строк,
       Поэтому мы объединяем строки до следующего номера записи.
        """
        lines = [line.strip() for line in text.split("\n") if line.strip()]
        records = []
        current_parts = []

        for line in lines:
            # Если встретили служебную строку — пропускаем её.
            if DebtExtractor._is_service_line(line):
                continue

            # Начало новой записи дисциплины: "22. ..."
            if re.match(r"^\d+\.\s*", line):
                if current_parts:
                    records.append(" ".join(current_parts))
                    current_parts = []

                current_parts.append(line)
            else:
                # Если это продолжение текущей записи — добавляем.
                if current_parts:
                    current_parts.append(line)

        if current_parts:
            records.append(" ".join(current_parts))

        # Нормализуем пробелы в итоговых записях.
        records = [re.sub(r"\s+", " ", record).strip() for record in records]

        return records

    @staticmethod
    def _parse_record_line(record_line: str) -> list[dict]:
        """
        Разбирает одну запись из учебной карточки.

        Ожидаем структуру примерно такого вида:
        22. Алгоритмы дискретной математики Б1.О 144 4 Хорошо - Неявка

        После кода дисциплины, часов и ЗЕТ идут три колонки:
        - экзамен
        - зачёт
        - курсовая работа
        """
        results = []

        pattern = (
            r"^\d+\.\s*"
            r"(?P<discipline>.*?)\s+"
            r"(?P<block>(?:Б|ФТД|УП)\S+)\s+"
            r"(?P<hours>[\d,]+)\s+"
            r"(?P<zet>[\d,]+)\s+"
            r"(?P<exam>.+?)\s+"
            r"(?P<credit>.+?)\s+"
            r"(?P<coursework>.+?)$"
        )

        match = re.match(pattern, record_line)
        if not match:
            return results

        discipline = match.group("discipline").strip()
        discipline = re.sub(r"\s+", " ", discipline)

        exam_value = match.group("exam").strip()
        credit_value = match.group("credit").strip()
        coursework_value = match.group("coursework").strip()

        # Защита от некорректного распознавания:
        # если одна из колонок оказалась совсем не похожей на оценку,
        # запись считаем ненадёжной и пропускаем.
        if not DebtExtractor._is_grade_value(exam_value):
            return results
        if not DebtExtractor._is_grade_value(credit_value):
            return results
        if not DebtExtractor._is_grade_value(coursework_value):
            return results

        exam_marker = DebtExtractor._find_marker(exam_value)
        if exam_marker:
            results.append(
                {
                    "discipline": discipline,
                    "debt_type": DebtExtractor.DEBT_TYPE_EXAM,
                    "status": exam_marker,
                }
            )

        credit_marker = DebtExtractor._find_marker(credit_value)
        if credit_marker:
            results.append(
                {
                    "discipline": discipline,
                    "debt_type": DebtExtractor.DEBT_TYPE_CREDIT,
                    "status": credit_marker,
                }
            )

        coursework_marker = DebtExtractor._find_marker(coursework_value)
        if coursework_marker:
            results.append(
                {
                    "discipline": discipline,
                    "debt_type": DebtExtractor.DEBT_TYPE_COURSEWORK,
                    "status": coursework_marker,
                }
            )

        return results

    @staticmethod
    def extract_debts(statement_text: str) -> dict:
        """
        Главная функция извлечения долгов из выписки.

        Возвращает:
        - группу;
        - список дисциплин;
        - список долгов с типом задолженности;
        - список найденных маркеров.
        """
        normalized_text = DebtExtractor._normalize_text(statement_text)
        group = DebtExtractor._extract_group(normalized_text)

        record_lines = DebtExtractor._build_record_lines(normalized_text)

        debts = []
        seen = set()
        markers = set()

        for record_line in record_lines:
            extracted_items = DebtExtractor._parse_record_line(record_line)

            for item in extracted_items:
                key = (item["discipline"], item["debt_type"], item["status"])

                if key in seen:
                    continue

                seen.add(key)
                debts.append(item)
                markers.add(item["status"])

        disciplines = []
        seen_disciplines = set()

        for item in debts:
            discipline = item["discipline"]
            if discipline not in seen_disciplines:
                disciplines.append(discipline)
                seen_disciplines.add(discipline)

        return {
            "group": group,
            "disciplines": disciplines,
            "debts": debts,
            "markers": sorted(markers),
        }