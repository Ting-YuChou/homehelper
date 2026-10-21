# models.py
from sqlalchemy import Column, Integer, String, Text, DateTime
from sqlalchemy.ext.declarative import declarative_base
from datetime import datetime, UTC

Base = declarative_base()

class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(String(64), index=True, nullable=False)
    user_message = Column(Text, nullable=True)
    agent_response = Column(Text, nullable=True)
    product_links = Column(Text, nullable=True)
    files = Column(Text, nullable=True)  # Store as comma-separated paths or JSON string
    timestamp = Column(DateTime, default=datetime.now(UTC))