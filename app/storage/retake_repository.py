"""
Репозиторий пересдач.

Отвечает за сохранение и чтение таблицы учебных событий:
основная попытка, вторичная пересдача и комиссия.
"""

from sqlalchemy.orm import Session

from app.models.retake_record import RetakeRecord


class RetakeRepository:
    """
    Репозиторий для работы с таблицей пересдач.
    """

    @staticmethod
    def clear_all(db: Session) -> None:
        """
        Полностью очищает таблицу записей.
        """
        db.query(RetakeRecord).delete()
        db.commit()

    @staticmethod
    def save_many(db: Session, records: list[dict]) -> int:
        """
        Сохраняет список нормализованных записей в БД.
        """
        objects = [
            RetakeRecord(
                source_file=record.get("source_file", ""),
                sheet_name=record.get("sheet_name", ""),
                retake_type=record.get("retake_type", ""),
                attempt_stage=record.get("attempt_stage", ""),
                attempt_number=record.get("attempt_number"),
                discipline=record.get("discipline", ""),
                teacher=record.get("teacher", ""),
                groups_raw=record.get("groups", ""),
                groups_normalized=record.get("groups_normalized", ""),
                date_raw=record.get("date", ""),
                event_date=record.get("event_date"),
                days_left=record.get("days_left"),
                time_raw=record.get("time", ""),
                room=record.get("room", ""),
                consultation_date_raw=record.get("consultation_date", ""),
                consultation_time_raw=record.get("consultation_time", ""),
                consultation_room=record.get("consultation_room", ""),
                risk_score=record.get("risk_score"),
                risk_level=record.get("risk_level", ""),
                discipline_difficulty=record.get("discipline_difficulty"),
                discipline_code=record.get("discipline_code"),
                discipline_credits=record.get("discipline_credits"),
                historical_failure_rate=record.get("historical_failure_rate"),
                failure_probability=record.get("failure_probability"),
                predicted_final_result=record.get("predicted_final_result"),
            )
            for record in records
        ]

        if objects:
            db.add_all(objects)
            db.commit()

        return len(objects)

    @staticmethod
    def count(db: Session) -> int:
        """
        Возвращает количество записей.
        """
        return db.query(RetakeRecord).count()

    @staticmethod
    def get_all(db: Session) -> list[RetakeRecord]:
        """
        Возвращает все записи с сортировкой по критичности и дате.
        """
        return (
            db.query(RetakeRecord)
            .order_by(
                RetakeRecord.risk_score.desc().nullslast(),
                RetakeRecord.event_date.asc().nullslast(),
                RetakeRecord.discipline.asc(),
            )
            .all()
        )

    @staticmethod
    def get_by_stage(db: Session, stage: str) -> list[RetakeRecord]:
        """
        Возвращает записи конкретного этапа: main, secondary, commission.
        """
        return (
            db.query(RetakeRecord)
            .filter(RetakeRecord.attempt_stage == stage)
            .order_by(
                RetakeRecord.risk_score.desc().nullslast(),
                RetakeRecord.event_date.asc().nullslast(),
                RetakeRecord.discipline.asc(),
            )
            .all()
        )
