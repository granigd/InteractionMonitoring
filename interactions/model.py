import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import declarative_base
from sqlalchemy import Column, String, TIMESTAMP, JSON

Base = declarative_base()


# ORM model for interactions
class InteractionModel(Base):
    __tablename__ = "interactions"
    time = Column(TIMESTAMP(timezone=True), primary_key=True, default=lambda: datetime.now(timezone.utc))
    session_id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    action_kind = Column(String, nullable=False)
    payload = Column(JSON, nullable=True)
    client_id = Column(String, nullable=False)
    metadata_json = Column("metadata", JSON, nullable=True)
    user_agent = Column(String, nullable=False)
    url = Column(String, nullable=False)
    source = Column(String, nullable=False)
    batch_id = Column(String, nullable=False)