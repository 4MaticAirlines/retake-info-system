"""
Точка входа веб-сервиса «Retake Info System».

Назначение модуля
-----------------
Создаёт экземпляр приложения FastAPI, инициализирует подключение к базе
данных, регистрирует все HTTP-маршруты и обслуживает статические файлы.

Назначение приложения
---------------------
Сервис мониторинга ликвидации академических задолженностей с
визуализацией риска отчисления. Студент в одно действие получает
список доступных пересдач и категорию риска по каждой задолженности.

Архитектура запуска
-------------------
1. Создаётся подключение к SQLite через SQLAlchemy.
2. Импортируются ORM-модели (необходимо ДО вызова ``create_all``).
3. Создаются недостающие таблицы и колонки.
4. Создаётся приложение FastAPI с заголовком.
5. Подключается роутер ``files_router`` с HTTP-маршрутами.
6. Монтируется директория статических файлов.

Запуск из командной строки
--------------------------
.. code-block:: bash

    uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

Где 0.0.0.0 — слушать на всех сетевых интерфейсах (нужно для доступа
извне локальной сети при настройке домена).
"""

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.core.config import BASE_DIR
from app.storage.database import Base, engine, ensure_retake_schema

# Импорт моделей обязателен ДО вызова Base.metadata.create_all,
# иначе SQLAlchemy не «увидит» таблицы и они не будут созданы.
from app.models.uploaded_file import UploadedFile  # noqa: F401
from app.models.retake_record import RetakeRecord  # noqa: F401
from app.api.routes_files import router as files_router


# Создание таблиц при первом запуске. Идемпотентно — повторный вызов
# не приводит к ошибке для уже существующих таблиц.
Base.metadata.create_all(bind=engine)
ensure_retake_schema()


# Экземпляр приложения FastAPI. Импортируется в uvicorn как
# ``app.main:app``.
app = FastAPI(
    title="Retake Info System",
    description=(
        "Сервис мониторинга ликвидации академических задолженностей "
        "с автоматизированной оценкой риска отчисления."
    ),
    version="1.0.0",
)

# Регистрация HTTP-маршрутов, определённых в модуле routes_files.
app.include_router(files_router)

# Монтирование директории со статикой (CSS, изображения).
app.mount(
    "/static",
    StaticFiles(directory=str(BASE_DIR / "app" / "static")),
    name="static",
)


@app.get("/", include_in_schema=False)
def root():
    """
    Обработчик корневого URL «/».

    Назначение:
        Перенаправление пользователя со страницы корня на главную
       Страницу управления файлами.

    Возвращает:
        RedirectResponse: HTTP 307 redirect на «/files/».
    """
    return RedirectResponse(url="/files/")
