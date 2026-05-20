"""
Парсер Excel-файлов с учебными событиями.

Поддерживает два типа Excel-документов:
1. классические таблицы пересдач кафедр;
2. расписание основной экзаменационной сессии, где группы находятся в
   заголовках столбцов, а дисциплины — в ячейках расписания.
"""

import re
import shutil
import subprocess
import tempfile
import warnings
from pathlib import Path
from typing import Any

import pandas as pd

from app.core.config import INPUT_DIR


class ExcelParser:
    """
    Парсер Excel-файлов кафедр и основной сессии.
    """

    def __init__(self, input_dir: Path = INPUT_DIR):
        """
         Init  .

        Аргументы:
            input_dir: параметр функции.
        """
        self.input_dir = input_dir

    def get_excel_files(self) -> list[Path]:
        """
        Возвращает все Excel-файлы из папки input.
        """
        if not self.input_dir.exists():
            return []

        files = []
        for file_path in self.input_dir.iterdir():
            if not file_path.is_file():
                continue
            if file_path.name.startswith("."):
                continue
            if file_path.suffix.lower() not in {".xls", ".xlsx"}:
                continue
            files.append(file_path)

        return sorted(files)

    @staticmethod
    def _resolve_engine(file_path: Path) -> str | None:
        """
        Выбирает движок чтения Excel по расширению файла.
        """
        if file_path.suffix.lower() == ".xls":
            return "xlrd"
        if file_path.suffix.lower() == ".xlsx":
            return "openpyxl"
        return None

    @staticmethod
    def _clean_cell(value: Any) -> str:
        """
        Нормализует значение ячейки.
        """
        if value is None:
            return ""
        try:
            if pd.isna(value):
                return ""
        except TypeError:
            pass

        text = str(value)
        text = text.replace("\r", " ").replace("\n", " ")
        text = re.sub(r"\s+", " ", text).strip()
        return text

    @staticmethod
    def _normalize_header(value: str) -> str:
        """
        Нормализует заголовок таблицы для сравнения.
        """
        return ExcelParser._clean_cell(value).lower()

    @staticmethod
    def _is_header_row(values: list[str]) -> bool:
        """
        Проверяет, является ли строка строкой заголовков обычной таблицы пересдач.
        """
        normalized_values = {ExcelParser._normalize_header(value) for value in values if value.strip()}

        required_patterns = [
            "дисциплина",
            "дата проведения пересдачи",
            "время проведения пересдачи",
            "аудитория",
        ]

        return all(any(pattern in cell for cell in normalized_values) for pattern in required_patterns)

    @staticmethod
    def _is_session_layout(df_raw: pd.DataFrame) -> bool:
        """
        Определяет файл основной сессии.

        Для расписания сессии первая строка обычно содержит:
        Дата | Номер | Время | Группа 1 | ... | Группа N
        """
        if df_raw.empty:
            return False

        first_row = [ExcelParser._normalize_header(value) for value in df_raw.iloc[0].tolist()]
        has_date = any(value == "дата" for value in first_row[:5])
        has_number = any(value == "номер" for value in first_row[:5])
        has_time = any(value == "время" for value in first_row[:5])
        has_groups = sum(1 for value in first_row[3:] if re.search(r"[А-ЯA-Z]+-\d{2}-", value.upper())) >= 2
        return has_date and has_number and has_time and has_groups

    @staticmethod
    def _extract_date_from_session_cell(value: Any) -> str:
        """
        Извлекает дату из ячейки вида '15.06.2026\nПонедельник'.
        """
        text = ExcelParser._clean_cell(value)
        match = re.search(r"\d{1,2}\.\d{1,2}\.\d{4}", text)
        return match.group(0) if match else ""

    @staticmethod
    def _parse_session_event_cell(value: Any) -> tuple[str, str, str]:
        """
        Разбирает ячейку расписания сессии.

        Пример:
        'Физика (Экзамен)\nГафуров М. Р.  Л-740'
        -> дисциплина='Физика', преподаватель='Гафуров М. Р.', аудитория='Л-740'
        """
        if value is None:
            return "", "", ""
        try:
            if pd.isna(value):
                return "", "", ""
        except TypeError:
            pass

        raw = str(value).replace("\r", "\n")
        lines = [line.strip() for line in raw.split("\n") if line and str(line).strip()]
        if not lines:
            return "", "", ""

        first_line = ExcelParser._clean_cell(lines[0])

        # В расписании сессии из-за объединённых ячеек рядом с дисциплиной
        # иногда попадает отдельная ячейка только с аудиторией. Её нельзя
        # считать дисциплиной.
        if not re.search(r"\((экзамен|зач[её]т|дифференцированный|курсов)", first_line, flags=re.IGNORECASE):
            return "", "", ""

        discipline = re.sub(r"\s*\([^)]*\)\s*$", "", first_line).strip()

        rest = ExcelParser._clean_cell(" ".join(lines[1:]))
        room = ""
        teacher = rest

        room_patterns = [
            r"\b[А-ЯA-Z]-\d{3}(?:-[А-ЯA-Zа-яa-z0-9]+)?\b",
            r"\bЛ-\d{3}(?:-[А-ЯA-Zа-яa-z0-9]+)?\b",
            r"\bОнлайн\b",
        ]
        for pattern in room_patterns:
            matches = re.findall(pattern, rest, flags=re.IGNORECASE)
            if matches:
                room = matches[-1]
                teacher = rest.replace(room, "").strip(" ,;")
                break

        return discipline, teacher, room

    def _read_excel_file(self, file_path: Path) -> pd.ExcelFile:
        """
        Открывает Excel-файл.

        Если .xls не удалось открыть из-за отсутствия xlrd, пробует временно
        конвертировать файл через LibreOffice. Это делает загрузку основной
        сессии устойчивее на окружениях, где xlrd не установлен.
        """
        engine = self._resolve_engine(file_path)
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
                return pd.ExcelFile(file_path, engine=engine)
        except Exception:
            if file_path.suffix.lower() != ".xls" or not shutil.which("libreoffice"):
                raise

            temp_dir = Path(tempfile.mkdtemp(prefix="retake_xls_"))
            subprocess.run(
                [
                    "libreoffice",
                    "--headless",
                    "--convert-to",
                    "xlsx",
                    "--outdir",
                    str(temp_dir),
                    str(file_path),
                ],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            converted_file = temp_dir / f"{file_path.stem}.xlsx"
            return pd.ExcelFile(converted_file, engine="openpyxl")

    def _read_sheet(self, excel_file: pd.ExcelFile, sheet_name: str) -> pd.DataFrame:
        """
        Читает лист без заголовков.
        """
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            return pd.read_excel(
                excel_file,
                sheet_name=sheet_name,
                header=None,
                dtype=object,
            ).dropna(how="all")

    def _find_header_rows(self, df_raw: pd.DataFrame) -> list[int]:
        """
        Ищет строки, похожие на заголовки обычной таблицы пересдач.
        """
        header_rows = []
        for index, row in df_raw.iterrows():
            values = [self._clean_cell(value) for value in row.tolist()]
            if self._is_header_row(values):
                header_rows.append(index)
        return header_rows

    def _parse_regular_sheet(self, file_path: Path, sheet_name: str, df_raw: pd.DataFrame) -> list[dict]:
        """
        Разбирает обычную таблицу пересдач.
        """
        parsed_rows: list[dict] = []
        header_rows = self._find_header_rows(df_raw)
        if not header_rows:
            return parsed_rows

        for position, header_row_index in enumerate(header_rows):
            header_values = [
                self._clean_cell(value) if self._clean_cell(value) else f"Unnamed: {idx}"
                for idx, value in enumerate(df_raw.iloc[header_row_index].tolist())
            ]

            next_header_index = header_rows[position + 1] if position + 1 < len(header_rows) else len(df_raw)
            body_df = df_raw.iloc[header_row_index + 1:next_header_index].copy()
            if body_df.empty:
                continue

            body_df.columns = header_values
            body_df = body_df.dropna(how="all")
            body_df = body_df.ffill().fillna("")

            for _, row in body_df.iterrows():
                row_dict = {column_name: self._clean_cell(value) for column_name, value in row.to_dict().items()}
                parsed_rows.append(
                    {
                        "source_file": file_path.name,
                        "sheet_name": sheet_name,
                        "row_data": row_dict,
                    }
                )

        return parsed_rows

    def _parse_session_sheet(self, file_path: Path, sheet_name: str, df_raw: pd.DataFrame) -> list[dict]:
        """
        Разбирает расписание основной экзаменационной сессии.
        """
        parsed_rows: list[dict] = []
        if df_raw.empty:
            return parsed_rows

        header_values = [self._clean_cell(value) for value in df_raw.iloc[0].tolist()]

        groups_by_col: dict[int, str] = {}
        current_group = ""
        for col_idx, header in enumerate(header_values):
            if col_idx < 3:
                continue
            if header:
                current_group = header
            if current_group:
                groups_by_col[col_idx] = current_group

        current_date = ""

        for row_idx in range(1, len(df_raw)):
            row = df_raw.iloc[row_idx]
            row_date = self._extract_date_from_session_cell(row.iloc[0] if len(row) > 0 else "")
            if row_date:
                current_date = row_date

            lesson_number = self._clean_cell(row.iloc[1] if len(row) > 1 else "")
            time_raw = self._clean_cell(row.iloc[2] if len(row) > 2 else "")

            if not current_date or not time_raw:
                continue

            for col_idx, group_name in groups_by_col.items():
                if col_idx >= len(row):
                    continue

                discipline, teacher, room = self._parse_session_event_cell(row.iloc[col_idx])
                if not discipline:
                    continue

                parsed_rows.append(
                    {
                        "source_file": file_path.name,
                        "sheet_name": sheet_name,
                        "row_data": {
                            "Дисциплина": discipline,
                            "Преподаватель": teacher,
                            "Группы": group_name,
                            "Дата проведения пересдачи": current_date,
                            "Время проведения пересдачи": time_raw,
                            "Аудитория": room,
                            "Номер пары": lesson_number,
                            "Тип попытки": "основная",
                        },
                    }
                )

        return parsed_rows

    def _parse_sheet(self, file_path: Path, sheet_name: str, df_raw: pd.DataFrame) -> list[dict]:
        """
        Разбирает один лист Excel.
        """
        if self._is_session_layout(df_raw):
            return self._parse_session_sheet(file_path, sheet_name, df_raw)
        return self._parse_regular_sheet(file_path, sheet_name, df_raw)

    def parse_file(self, file_path: Path) -> list[dict]:
        """
        Разбирает один Excel-файл.
        """
        parsed_rows: list[dict] = []

        try:
            excel_file = self._read_excel_file(file_path)
            for sheet_name in excel_file.sheet_names:
                df_raw = self._read_sheet(excel_file, sheet_name)
                parsed_rows.extend(self._parse_sheet(file_path, sheet_name, df_raw))
        except Exception as error:
            parsed_rows.append(
                {
                    "source_file": file_path.name,
                    "sheet_name": None,
                    "row_data": {"error": str(error)},
                }
            )

        return parsed_rows

    def parse_all_files(self) -> list[dict]:
        """
        Разбирает все Excel-файлы из папки input.
        """
        all_rows: list[dict] = []
        for file_path in self.get_excel_files():
            all_rows.extend(self.parse_file(file_path))
        return all_rows
