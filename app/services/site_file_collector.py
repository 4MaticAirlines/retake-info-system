"""
Сервис автоматической загрузки Excel-файлов с сайта МИСИС.

Используется для двух источников:
- страницы ликвидации задолженностей;
- страницы актуальной экзаменационной сессии.
"""

from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


class SiteFileCollector:
    """
    Загружает Excel-файлы со страницы сайта.
    """

    # Вкладки страницы ликвидации задолженностей, где обычно лежат файлы пересдач.
    DEFAULT_TARGET_TAB_IDS = ("tab-1-1", "tab-1-3")

    def __init__(self, page_url: str, target_tab_ids: tuple[str, ...] | None = DEFAULT_TARGET_TAB_IDS):
        """
        Инициализация сервиса.

        target_tab_ids=None означает, что Excel-ссылки будут собираться
        со всей страницы. Это удобно для страницы актуальной сессии.
        """
        self.page_url = page_url.split("#")[0].strip()
        self.target_tab_ids = target_tab_ids
        self.session = self._build_session()

    @staticmethod
    def _build_session() -> requests.Session:
        """
        Создаёт requests.Session с повторными попытками.
        """
        session = requests.Session()

        retry_strategy = Retry(
            total=3,
            backoff_factor=1.5,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET"],
        )

        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("https://", adapter)
        session.mount("http://", adapter)

        session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0 Safari/537.36"
                )
            }
        )

        return session

    def _get_page_html(self) -> str:
        """
        Загружает HTML страницы.
        """
        response = self.session.get(self.page_url, timeout=60)
        response.raise_for_status()
        return response.text

    @staticmethod
    def _is_excel_link(href: str) -> bool:
        """
        Проверяет, ведёт ли ссылка на Excel-файл.
        """
        href = href.lower()
        return ".xls" in href or ".xlsx" in href

    def _collect_links_from_tab(self, soup: BeautifulSoup, tab_id: str) -> list[str]:
        """
        Собирает Excel-ссылки из конкретной вкладки.
        """
        tab_block = soup.find(id=tab_id)
        if not tab_block:
            return []

        return self._collect_links_from_block(tab_block)

    def _collect_links_from_block(self, block) -> list[str]:
        """
        Собирает Excel-ссылки из HTML-блока.
        """
        links = []
        for tag in block.find_all("a", href=True):
            href = tag["href"].strip()
            if self._is_excel_link(href):
                links.append(urljoin(self.page_url, href))
        return links

    def collect_excel_links(self) -> list[str]:
        """
        Собирает все уникальные Excel-ссылки.
        """
        html = self._get_page_html()
        soup = BeautifulSoup(html, "html.parser")

        links = []

        if self.target_tab_ids is None:
            links.extend(self._collect_links_from_block(soup))
        else:
            for tab_id in self.target_tab_ids:
                links.extend(self._collect_links_from_tab(soup, tab_id))

        return list(dict.fromkeys(links))

    def download_file(self, file_url: str) -> tuple[str, bytes]:
        """
        Скачивает один Excel-файл.
        """
        response = self.session.get(file_url, timeout=90)
        response.raise_for_status()

        file_name = file_url.split("/")[-1]
        return file_name, response.content
