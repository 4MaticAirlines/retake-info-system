"""
Репозиторий доступа к таблице uploaded_files.

Назначение модуля
-----------------
Класс ``UploadedFileRepository`` инкапсулирует операции работы с
таблицей ``uploaded_files``: создание новой записи, поиск по
hash-значению или сохранённому имени, перечисление всех записей,
удаление по имени и полная очистка таблицы.

Используется в HTTP-обработчиках и сервисах загрузки файлов.
"""
from sqlalchemy.orm import Session

from app.models.uploaded_file import UploadedFile


class UploadedFileRepository:
    """
    Репозиторий для работы с таблицей uploaded_files.

    Все методы статические — экземпляр класса создавать не требуется.
    Каждый метод принимает активную ``Session`` SQLAlchemy и работает
   С ней транзакционно.
    """

    @staticmethod
    def find_by_hash(db: Session, file_hash: str) -> UploadedFile | None:
        """
        Поиск записи по SHA-256 хэшу содержимого файла.

        Используется для предотвращения повторной загрузки одного и
       Того же файла.

        Аргументы:
            db: активная сессия SQLAlchemy.
            file_hash: SHA-256 хэш содержимого файла в hex-формате.

        Возвращает:
            Объект UploadedFile, если запись найдена; иначе None.
        """
        return db.query(UploadedFile).filter(UploadedFile.file_hash == file_hash).first()

    @staticmethod
    def get_by_stored_name(db: Session, stored_name: str) -> UploadedFile | None:
        """
        Поиск записи по уникальному имени файла на диске.

        Аргументы:
            db: активная сессия SQLAlchemy.
            stored_name: имя файла в файловом хранилище.

        Возвращает:
            Объект UploadedFile, если запись найдена; иначе None.
        """
        return db.query(UploadedFile).filter(UploadedFile.stored_name == stored_name).first()

    @staticmethod
    def list_all(db: Session) -> list[UploadedFile]:
        """
        Возвращает все записи о загруженных файлах в порядке убывания
       Даты создания.

        Аргументы:
            db: активная сессия SQLAlchemy.

        Возвращает:
            Список UploadedFile, отсортированный по created_at DESC.
        """
        return db.query(UploadedFile).order_by(UploadedFile.created_at.desc()).all()

    @staticmethod
    def create(
        db: Session,
        *,
        original_name: str,
        stored_name: str,
        file_hash: str,
        source: str,
        file_type: str,
        file_path: str,
    ) -> UploadedFile:
        """
        Создаёт новую запись о загруженном файле и фиксирует изменения.

        Аргументы:
            db: активная сессия SQLAlchemy.
            original_name: исходное имя файла, как его назвал пользователь.
            stored_name: уникальное имя файла в файловом хранилище.
            file_hash: SHA-256 хэш содержимого.
            source: источник файла (например, "upload" или "site").
            file_type: тип файла ("excel" или "pdf").
            file_path: абсолютный путь к файлу на диске.

        Возвращает:
            Созданный объект UploadedFile с заполненным id.
        """
        obj = UploadedFile(
            original_name=original_name,
            stored_name=stored_name,
            file_hash=file_hash,
            source=source,
            file_type=file_type,
            file_path=file_path,
        )
        db.add(obj)
        db.commit()
        db.refresh(obj)
        return obj

    @staticmethod
    def delete_by_stored_name(db: Session, stored_name: str) -> None:
        """
        Удаляет запись о файле по его сохранённому имени.

        Если запись не найдена, операция выполняется молча
        (без исключения).

        Аргументы:
            db: активная сессия SQLAlchemy.
            stored_name: имя файла в файловом хранилище.
        """
        obj = UploadedFileRepository.get_by_stored_name(db, stored_name)
        if obj:
            db.delete(obj)
            db.commit()

    @staticmethod
    def clear_all(db: Session) -> None:
        """
        Полностью очищает таблицу uploaded_files.

        Используется при инициализации тестовых сценариев или при
       Ручной очистке базы данных через интерфейс администратора.

        Аргументы:
            db: активная сессия SQLAlchemy.
        """
        db.query(UploadedFile).delete()
        db.commit()
