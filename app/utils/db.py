"""
Контекст-менеджер сессии БД.

Заменяет повторяющийся блок try/finally в каждом HTTP-эндпоинте.
"""

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy.orm import Session

from app.storage.database import SessionLocal


@contextmanager
def db_session() -> Iterator[Session]:
    """Контекст-менеджер для работы с сессией БД."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
