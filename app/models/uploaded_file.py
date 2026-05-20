"""
ORM-модель загруженного файла (Excel или PDF). Хранит метаданные о файле в таблице uploaded_files.
"""
from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, String

from app.storage.database import Base


class UploadedFile(Base):
    """
    Uploaded file.
    """
    __tablename__ = "uploaded_files"

    id = Column(Integer, primary_key=True, index=True)
    original_name = Column(String, nullable=False)
    stored_name = Column(String, nullable=False, unique=True, index=True)
    file_hash = Column(String, nullable=False, unique=True, index=True)
    source = Column(String, nullable=False)  # site / manual
    file_type = Column(String, nullable=False)  # excel / statement
    file_path = Column(String, nullable=False, unique=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)