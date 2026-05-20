"""
ORM-модель записи о пересдаче. Соответствует одной строке расписания пересдачи в таблице retake_records.
"""
from sqlalchemy import Column, Date, Float, Integer, String

from app.storage.database import Base


class RetakeRecord(Base):
    """
    ORM-модель записи о попытке сдачи или пересдачи.

    Одна запись описывает конкретное учебное событие:
    основную попытку, вторичную пересдачу или комиссию. Дополнительные поля критичности нужны для
   Приоритизации задолженностей в интерфейсе.
    """

    __tablename__ = "retake_records"

    id = Column(Integer, primary_key=True, index=True)

    # Исходный файл и лист, откуда была получена запись.
    source_file = Column(String, nullable=True)
    sheet_name = Column(String, nullable=True)

    # Человекочитаемый тип события: основная, вторичная, комиссия.
    retake_type = Column(String, nullable=True, index=True)

    # Машинный этап события: main, secondary, commission.
    attempt_stage = Column(String, nullable=True, index=True)

    # Основные поля записи.
    discipline = Column(String, nullable=False, index=True)
    teacher = Column(String, nullable=True)
    groups_raw = Column(String, nullable=True)
    groups_normalized = Column(String, nullable=True, index=True)

    date_raw = Column(String, nullable=True)
    time_raw = Column(String, nullable=True)
    room = Column(String, nullable=True)

    consultation_date_raw = Column(String, nullable=True)
    consultation_time_raw = Column(String, nullable=True)
    consultation_room = Column(String, nullable=True)

    # Дата события в нормализованном виде. Используется для расчёта срочности.
    event_date = Column(Date, nullable=True, index=True)

    # Количество дней до события. Если дата прошла, значение отрицательное.
    days_left = Column(Integer, nullable=True)

    # Оценка критичности задолженности.
    risk_score = Column(Float, nullable=True, index=True)
    risk_level = Column(String, nullable=True, index=True)

    # Дополнительные признаки для ML-модуля классификации риска.
    discipline_difficulty = Column(Float, nullable=True)
    attempt_number = Column(Integer, nullable=True)
    discipline_code = Column(Integer, nullable=True, index=True)
    discipline_credits = Column(Integer, nullable=True)
    historical_failure_rate = Column(Float, nullable=True)
    failure_probability = Column(Float, nullable=True)
    predicted_final_result = Column(Integer, nullable=True)
