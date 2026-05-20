"""
Подключение к БД и мягкая миграция схемы.
"""

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import declarative_base, sessionmaker

from app.core.config import DATABASE_URL


_is_sqlite = DATABASE_URL.startswith("sqlite")

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if _is_sqlite else {},
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()


# Поля retake_records, которые могут отсутствовать в старой БД.
_RETAKE_NEW_COLUMNS: dict[str, str] = {
    "attempt_stage": "VARCHAR",
    "event_date": "DATE",
    "days_left": "INTEGER",
    "risk_score": "FLOAT",
    "risk_level": "VARCHAR",
    "discipline_difficulty": "FLOAT",
    "attempt_number": "INTEGER",
    "discipline_code": "INTEGER",
    "discipline_credits": "INTEGER",
    "historical_failure_rate": "FLOAT",
    "failure_probability": "FLOAT",
    "predicted_final_result": "INTEGER",
}


def ensure_retake_schema() -> None:
    """
    Мягкая миграция для SQLite.

    create_all не добавляет новые колонки в существующую таблицу,
    поэтому здесь они досоздаются через ALTER TABLE.
    """
    inspector = inspect(engine)
    if "retake_records" not in inspector.get_table_names():
        return

    existing = {column["name"] for column in inspector.get_columns("retake_records")}
    missing = {name: ctype for name, ctype in _RETAKE_NEW_COLUMNS.items() if name not in existing}
    if not missing:
        return

    with engine.begin() as connection:
        for column_name, column_type in missing.items():
            connection.execute(
                text(f"ALTER TABLE retake_records ADD COLUMN {column_name} {column_type}")
            )
