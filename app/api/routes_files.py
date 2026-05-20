"""
Маршруты приложения.

Файл отвечает за:
- главную страницу;
- управление Excel-файлами;
- автозагрузку с сайта;
- пересборку базы;
- поиск по группе;
- поиск по PDF-выписке с классификацией риска отчисления.
"""

from datetime import datetime
from typing import Iterable

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.core.config import (
    BASE_DIR,
    INPUT_DIR,
    STATEMENT_DIR,
    UNIVERSITY_RETAKES_URL,
    UNIVERSITY_SESSION_URL,
)
from app.services.data_normalizer import DataNormalizer
from app.services.debt_extractor import DebtExtractor
from app.services.discipline_risk import DisciplineRiskClassifier
from app.services.excel_parser import ExcelParser
from app.services.group_search import GroupSearch
from app.services.retake_matcher import RetakeMatcher
from app.services.site_file_collector import SiteFileCollector
from app.services.statement_parser import StatementParser
from app.services.stats_manager import StatsValidationError, save_stats_file
from app.storage.file_repository import UploadedFileRepository
from app.storage.retake_repository import RetakeRepository
from app.utils.db import db_session
from app.utils.file_loader import (
    calculate_file_hash,
    find_existing_file_by_hash,
    save_binary_file,
)


router = APIRouter(prefix="/files", tags=["files"])
templates = Jinja2Templates(directory=str(BASE_DIR / "app" / "templates"))


STAGE_TABS: list[dict] = [
    {"key": "main", "title": "Основная"},
    {"key": "secondary", "title": "Вторичная"},
    {"key": "commission", "title": "Комиссия"},
]


# ---------------------------------------------------------------------------
# Хелперы.
# ---------------------------------------------------------------------------

def _render(request: Request, template: str, **context) -> HTMLResponse:
    """Унифицированный рендер HTML-шаблонов."""
    return templates.TemplateResponse(request=request, name=template, context=context)


def _render_manage(request: Request, db: Session, message: str, message_type: str) -> HTMLResponse:
    """Сокращённый рендер страницы управления файлами."""
    return _render(
        request,
        "manage.html",
        files=_build_file_list(db),
        message=message,
        message_type=message_type,
    )


def _retake_to_dict(record) -> dict:
    """Преобразует ORM-объект записи в словарь для шаблонов."""
    stage = record.attempt_stage or "secondary"
    if stage == "primary":
        stage = "secondary"

    groups_normalized = record.groups_normalized or ""
    groups_list = [g.strip() for g in str(groups_normalized).split(",") if g.strip()]

    return {
        "id": record.id,
        "discipline": record.discipline,
        "teacher": record.teacher,
        "groups": record.groups_raw or "",
        "groups_normalized": groups_normalized,
        "groups_list": groups_list,
        "retake_type": record.retake_type or "",
        "attempt_stage": stage,
        "attempt_number": record.attempt_number,
        "date": record.date_raw or "",
        "event_date": record.event_date,
        "days_left": record.days_left,
        "time": record.time_raw or "",
        "room": record.room or "",
        "consultation_date": record.consultation_date_raw or "",
        "consultation_time": record.consultation_time_raw or "",
        "consultation_room": record.consultation_room or "",
        "risk_score": record.risk_score,
        "risk_level": record.risk_level or "",
        "discipline_difficulty": record.discipline_difficulty,
        "discipline_code": record.discipline_code,
        "discipline_credits": record.discipline_credits,
        "historical_failure_rate": record.historical_failure_rate,
        "failure_probability": record.failure_probability,
        "predicted_final_result": record.predicted_final_result,
        "source_file": record.source_file or "",
        "sheet_name": record.sheet_name or "",
    }


def _build_file_list(db: Session) -> list[dict]:
    """Формирует список загруженных Excel-файлов."""
    meta_by_stored = {item.stored_name: item for item in UploadedFileRepository.list_all(db)}

    files: list[dict] = []
    for file_path in sorted(INPUT_DIR.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        if not file_path.is_file() or file_path.name.startswith("."):
            continue
        meta = meta_by_stored.get(file_path.name)
        files.append(
            {
                "stored_name": file_path.name,
                "display_name": meta.original_name if meta else file_path.name,
                "source": meta.source if meta else "unknown",
                "size_kb": round(file_path.stat().st_size / 1024, 2),
                "updated_at": datetime.fromtimestamp(file_path.stat().st_mtime).strftime("%d.%m.%Y %H:%M"),
            }
        )
    return files


def _sync_retakes(db: Session) -> tuple[int, int]:
    """Пересобирает записи из всех Excel-файлов."""
    rows = ExcelParser().parse_all_files()
    normalized = DataNormalizer.normalize_rows(rows)
    RetakeRepository.clear_all(db)
    return len(rows), RetakeRepository.save_many(db, normalized)


def _ensure_loaded(db: Session) -> None:
    """Если БД пуста, но Excel-файлы есть, пересобирает данные."""
    if RetakeRepository.count(db) == 0 and ExcelParser().get_excel_files():
        _sync_retakes(db)


def _has_consultation(records: Iterable[dict]) -> bool:
    """Проверяет, есть ли в выборке информация о консультациях."""
    return any(
        r.get("consultation_date") or r.get("consultation_time") or r.get("consultation_room")
        for r in records
    )


def _flatten_statement_results(statement_results: list[dict]) -> list[dict]:
    """Превращает результат поиска по выписке в плоский список строк."""
    rows: list[dict] = []

    for item in statement_results:
        if not item.get("matches"):
            rows.append(
                {
                    "attempt_stage": "secondary",
                    "retake_type": "",
                    "attempt_number": None,
                    "discipline": item.get("discipline", ""),
                    "debt_type": item.get("debt_type", ""),
                    "status": item.get("status", ""),
                    "teacher": "",
                    "groups": "",
                    "groups_normalized": "",
                    "groups_list": [],
                    "date": "",
                    "event_date": None,
                    "days_left": None,
                    "risk_level": "",
                    "risk_score": None,
                    "discipline_difficulty": None,
                    "discipline_code": None,
                    "discipline_credits": None,
                    "historical_failure_rate": None,
                    "failure_probability": None,
                    "predicted_final_result": None,
                    "time": "",
                    "room": "Информация о пересдаче пока не найдена",
                    "consultation_date": "",
                    "consultation_time": "",
                    "consultation_room": "",
                    "source_file": "",
                    "sheet_name": "",
                    "not_found": True,
                }
            )
            continue

        for match in item["matches"]:
            row = dict(match)
            row["discipline"] = item.get("discipline", match.get("discipline", ""))
            row["debt_type"] = item.get("debt_type", "")
            row["status"] = item.get("status", "")
            row["not_found"] = False
            rows.append(row)

    return RetakeMatcher.sort_records(rows)


def _save_site_files(
    db: Session,
    page_url: str,
    source_label: str,
    target_tab_ids: tuple[str, ...] | None = None,
) -> tuple[int, int]:
    """Скачивает Excel-файлы со страницы и регистрирует их в БД."""
    collector = SiteFileCollector(page_url, target_tab_ids=target_tab_ids)
    links = collector.collect_excel_links()

    saved_count = 0
    duplicate_count = 0

    for file_url in links:
        original_name, file_bytes = collector.download_file(file_url)
        file_hash = calculate_file_hash(file_bytes)

        if UploadedFileRepository.find_by_hash(db, file_hash) or find_existing_file_by_hash(INPUT_DIR, file_hash):
            duplicate_count += 1
            continue

        stored_name, file_path = save_binary_file(INPUT_DIR, original_name, file_bytes)
        UploadedFileRepository.create(
            db,
            original_name=original_name,
            stored_name=stored_name,
            file_hash=file_hash,
            source=source_label,
            file_type="excel",
            file_path=str(file_path),
        )
        saved_count += 1

    return saved_count, duplicate_count


# ---------------------------------------------------------------------------
# Главная и навигация.
# ---------------------------------------------------------------------------

@router.get("/", response_class=HTMLResponse)
def home_page(request: Request) -> HTMLResponse:
    """Главная страница."""
    return _render(request, "index.html", message="", message_type="info")


@router.get("/search", response_class=HTMLResponse)
def search_page(request: Request) -> HTMLResponse:
    """Страница поиска."""
    return _render(request, "search.html")


@router.get("/manage", response_class=HTMLResponse)
def manage_page(request: Request) -> HTMLResponse:
    """Страница управления файлами."""
    with db_session() as db:
        return _render_manage(request, db, message="", message_type="info")


# ---------------------------------------------------------------------------
# Управление Excel-файлами.
# ---------------------------------------------------------------------------

@router.post("/fetch-from-site", response_class=HTMLResponse)
def fetch_from_site(request: Request) -> HTMLResponse:
    """Автозагрузка Excel-файлов с сайта МИСИС."""
    with db_session() as db:
        try:
            saved_total = 0
            duplicate_total = 0

            sources: list[tuple[str, str, tuple[str, ...] | None]] = []
            if UNIVERSITY_RETAKES_URL:
                sources.append(
                    (UNIVERSITY_RETAKES_URL, "site_retakes", SiteFileCollector.DEFAULT_TARGET_TAB_IDS)
                )
            if UNIVERSITY_SESSION_URL:
                sources.append((UNIVERSITY_SESSION_URL, "site_session", None))

            for url, label, tabs in sources:
                saved, duplicates = _save_site_files(db, page_url=url, source_label=label, target_tab_ids=tabs)
                saved_total += saved
                duplicate_total += duplicates

            if saved_total == 0 and duplicate_total == 0:
                return _render_manage(request, db, "Excel-файлы на страницах не найдены", "error")

            parsed_rows_count, rebuilt_count = (0, 0)
            if saved_total > 0:
                parsed_rows_count, rebuilt_count = _sync_retakes(db)

            return _render_manage(
                request,
                db,
                (
                    f"Автозагрузка завершена: новых файлов — {saved_total}, "
                    f"дубликатов — {duplicate_total}, "
                    f"строк прочитано — {parsed_rows_count}, "
                    f"записей сохранено — {rebuilt_count}"
                ),
                "success",
            )
        except Exception as error:
            return _render_manage(request, db, f"Ошибка автозагрузки: {error}", "error")


@router.post("/upload", response_class=HTMLResponse)
async def upload_file(request: Request, file: UploadFile = File(...)) -> HTMLResponse:
    """Ручная загрузка Excel-файла."""
    with db_session() as db:
        if not file.filename:
            return _render_manage(request, db, "Файл не выбран", "error")

        if not file.filename.lower().endswith((".xls", ".xlsx")):
            return _render_manage(request, db, "Разрешены только Excel-файлы (.xls, .xlsx)", "error")

        file_bytes = await file.read()
        if not file_bytes:
            return _render_manage(request, db, "Файл пустой", "error")

        file_hash = calculate_file_hash(file_bytes)
        if UploadedFileRepository.find_by_hash(db, file_hash) or find_existing_file_by_hash(INPUT_DIR, file_hash):
            return _render_manage(request, db, "Такой файл уже был загружен", "warning")

        stored_name, file_path = save_binary_file(INPUT_DIR, file.filename, file_bytes)
        UploadedFileRepository.create(
            db,
            original_name=file.filename,
            stored_name=stored_name,
            file_hash=file_hash,
            source="manual",
            file_type="excel",
            file_path=str(file_path),
        )

        parsed_rows_count, rebuilt_count = _sync_retakes(db)
        return _render_manage(
            request,
            db,
            (
                f"Файл «{file.filename}» успешно загружен. "
                f"Строк прочитано — {parsed_rows_count}, "
                f"записей сохранено — {rebuilt_count}"
            ),
            "success",
        )


@router.post("/upload-stats", response_class=HTMLResponse)
async def upload_stats(request: Request, file: UploadFile = File(...)) -> HTMLResponse:
    """
    Загрузка статистики дисциплин для модели риска.

    Принимает Excel/CSV в формате disciplines_template.xlsx. После загрузки
    обновляет шаблон, регенерирует обучающий датасет и переобучает
    Random Forest.
    """
    with db_session() as db:
        if not file.filename:
            return _render_manage(request, db, "Файл не выбран", "error")

        suffix = file.filename.lower().rsplit(".", 1)[-1] if "." in file.filename else ""
        if suffix not in ("csv", "xlsx", "xls"):
            return _render_manage(
                request, db,
                "Принимаются только файлы .csv, .xlsx, .xls",
                "error",
            )

        file_bytes = await file.read()
        if not file_bytes:
            return _render_manage(request, db, "Файл пустой", "error")

        # Сохраняем во временный файл.
        from pathlib import Path
        temp_dir = BASE_DIR / "data" / "input" / "stats_uploads"
        temp_dir.mkdir(parents=True, exist_ok=True)
        temp_path = temp_dir / f"upload.{suffix}"
        temp_path.write_bytes(file_bytes)

        try:
            result = save_stats_file(temp_path)
        except StatsValidationError as error:
            return _render_manage(
                request, db,
                f"Ошибка валидации файла: {error}",
                "error",
            )
        except Exception as error:
            return _render_manage(
                request, db,
                f"Ошибка при обработке файла: {error}",
                "error",
            )
        finally:
            if temp_path.exists():
                temp_path.unlink()

        metrics = result.get("metrics", {})
        if metrics:
            metrics_text = (
                f" Метрики модели: Accuracy = {metrics.get('accuracy', 0):.3f}, "
                f"F1 = {metrics.get('f1', 0):.3f}, "
                f"ROC-AUC = {metrics.get('roc_auc', 0):.3f}."
            )
        else:
            metrics_text = ""

        return _render_manage(
            request, db,
            (
                f"Статистика обновлена: {result['discipline_count']} дисциплин. "
                f"Модель Random Forest переобучена.{metrics_text}"
            ),
            "success",
        )


@router.post("/rebuild-db", response_class=HTMLResponse)
def rebuild_db(request: Request) -> HTMLResponse:
    """Явная пересборка данных из всех Excel-файлов."""
    with db_session() as db:
        excel_files = ExcelParser().get_excel_files()
        if not excel_files:
            return _render_manage(request, db, "В папке нет Excel-файлов для пересборки", "warning")

        parsed_rows_count, rebuilt_count = _sync_retakes(db)
        return _render_manage(
            request,
            db,
            (
                f"Данные обновлены. "
                f"Excel-файлов найдено — {len(excel_files)}, "
                f"строк прочитано — {parsed_rows_count}, "
                f"записей сохранено — {rebuilt_count}"
            ),
            "success",
        )


@router.post("/delete-one", response_class=HTMLResponse)
def delete_one_file(request: Request, stored_name: str = Form(...)) -> HTMLResponse:
    """Удаление одного Excel-файла."""
    with db_session() as db:
        file_path = INPUT_DIR / stored_name

        if not file_path.exists():
            return _render_manage(request, db, "Файл не найден", "error")

        if file_path.is_file():
            file_path.unlink()

        if UploadedFileRepository.get_by_stored_name(db, stored_name):
            UploadedFileRepository.delete_by_stored_name(db, stored_name)

        if ExcelParser().get_excel_files():
            parsed_rows_count, rebuilt_count = _sync_retakes(db)
            message = (
                f"Файл успешно удалён. "
                f"Строк прочитано — {parsed_rows_count}, "
                f"записей сохранено — {rebuilt_count}"
            )
        else:
            RetakeRepository.clear_all(db)
            message = "Файл успешно удалён. База очищена, потому что Excel-файлов больше нет."

        return _render_manage(request, db, message, "success")


@router.post("/delete-all", response_class=HTMLResponse)
def delete_all_files(request: Request) -> HTMLResponse:
    """Удаление всех Excel-файлов и очистка базы."""
    with db_session() as db:
        for file_path in INPUT_DIR.iterdir():
            if file_path.is_file() and not file_path.name.startswith("."):
                file_path.unlink()

        UploadedFileRepository.clear_all(db)
        RetakeRepository.clear_all(db)
        return _render(request, "manage.html", files=[], message="Все Excel-файлы и записи удалены", message_type="success")


# ---------------------------------------------------------------------------
# Отладочные маршруты.
# ---------------------------------------------------------------------------

@router.get("/parsed")
def show_parsed_files() -> dict:
    """Отладка: показывает первые строки после парсинга Excel."""
    parsed_data = ExcelParser().parse_all_files()
    return {"message": "Файлы успешно обработаны", "total_rows": len(parsed_data), "data": parsed_data[:20]}


@router.get("/normalized")
def normalized_data() -> dict:
    """Отладка: показывает первые строки после нормализации."""
    rows = ExcelParser().parse_all_files()
    normalized = DataNormalizer.normalize_rows(rows)
    return {"total_records": len(normalized), "data": normalized[:20]}


# ---------------------------------------------------------------------------
# Поиск.
# ---------------------------------------------------------------------------

@router.get("/search-by-group", response_class=HTMLResponse)
def search_by_group(request: Request, group: str) -> HTMLResponse:
    """Поиск пересдач по группе."""
    with db_session() as db:
        _ensure_loaded(db)

        records = [_retake_to_dict(r) for r in RetakeRepository.get_all(db)]
        result = GroupSearch.find_by_group(records, group)
        grouped = RetakeMatcher.group_records_by_stage(result)

        return _render(
            request,
            "results.html",
            search_type="group",
            query=group,
            total_records=len(result),
            records=result,
            records_by_stage=grouped,
            stage_tabs=STAGE_TABS,
            disciplines=[],
            statement_group="",
            markers=[],
            show_consultation=_has_consultation(result),
            statement_results=[],
            discipline_risks=[],
        )


@router.post("/search-by-statement", response_class=HTMLResponse)
async def search_by_statement(request: Request, file: UploadFile = File(...)) -> HTMLResponse:
    """
    Поиск пересдач по PDF-выписке студента.

    Дополнительно — классификация риска отчисления по каждой дисциплине
    через обученный Random Forest. Это основное ML-нововведение проекта.
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="Файл не выбран")
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Поддерживается только PDF")

    save_path = STATEMENT_DIR / file.filename
    file_bytes = await file.read()
    save_path.write_bytes(file_bytes)

    statement_text = StatementParser.parse_statement(save_path)
    debts_data = DebtExtractor.extract_debts(statement_text)

    with db_session() as db:
        _ensure_loaded(db)
        records = [_retake_to_dict(r) for r in RetakeRepository.get_all(db)]

        statement_results = RetakeMatcher.build_statement_results(
            records=records,
            debts=debts_data["debts"],
            group=debts_data["group"],
        )

        # Классификация риска отчисления по каждой дисциплине.
        discipline_risks = [
            risk.to_dict() for risk in DisciplineRiskClassifier.classify_many(debts_data["debts"])
        ]

        flat_rows = _flatten_statement_results(statement_results)
        grouped = RetakeMatcher.group_records_by_stage(flat_rows)
        total_matches = sum(len(item["matches"]) for item in statement_results)

        show_consultation = any(
            match.get("consultation_date") or match.get("consultation_time") or match.get("consultation_room")
            for item in statement_results
            for match in item["matches"]
        )

        return _render(
            request,
            "results.html",
            search_type="statement",
            query="выписка о задолженностях",
            total_records=total_matches,
            records=flat_rows,
            records_by_stage=grouped,
            stage_tabs=STAGE_TABS,
            disciplines=debts_data["disciplines"],
            statement_group=debts_data["group"],
            markers=debts_data["markers"],
            show_consultation=show_consultation,
            statement_results=statement_results,
            discipline_risks=discipline_risks,
        )
