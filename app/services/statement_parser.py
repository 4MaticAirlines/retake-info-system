"""
Сервис чтения PDF-выписки.

На этом этапе приложение поддерживает только PDF,
потому что именно этот формат используется для поиска по выписке.
"""

from pathlib import Path

from pypdf import PdfReader


class StatementParser:
    """
    Извлекает текст из PDF-выписки.
    """

    @staticmethod
    def parse_statement(file_path: Path) -> str:
        """
        Возвращает полный текст PDF-документа.
        """
        suffix = file_path.suffix.lower()

        if suffix != ".pdf":
            raise ValueError("Поддерживаются только PDF-файлы")

        reader = PdfReader(str(file_path))
        pages_text = []

        for page in reader.pages:
            page_text = page.extract_text() or ""
            pages_text.append(page_text)

        return "\n".join(pages_text)