from sqlalchemy import (
    Column, String, Text, Boolean, DateTime, Date,
    ForeignKey, JSON, func, Index
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, relationship
import uuid


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    chat_id = Column(String, unique=True, nullable=False)
    first_name = Column(String)
    username = Column(String)
    notion_connected = Column(Boolean, default=False, nullable=False)
    notion_access_token = Column(String)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    messages = relationship("Message", back_populates="user", cascade="all, delete")
    captures = relationship("Capture", back_populates="user", cascade="all, delete")
    tasks = relationship("Task", back_populates="user", cascade="all, delete")
    reminders = relationship("Reminder", back_populates="user", cascade="all, delete")
    voice_messages = relationship("VoiceMessage", back_populates="user", cascade="all, delete")
    notion_databases = relationship("NotionDatabase", back_populates="user", cascade="all, delete")


class Message(Base):
    __tablename__ = "messages"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    raw_input = Column(Text)
    input_type = Column(String, default="text", nullable=False)
    intent = Column(String)
    llm_raw_response = Column(JSON)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="messages")
    voice_message = relationship("VoiceMessage", back_populates="message", cascade="all, delete")


class Capture(Base):
    __tablename__ = "captures"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    message_id = Column(UUID(as_uuid=True), ForeignKey("messages.id", ondelete="SET NULL"), nullable=True)
    raw_text = Column(Text, nullable=False)
    source = Column(String, default="telegram", nullable=False)
    processed = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="captures")


class Task(Base):
    __tablename__ = "tasks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    message_id = Column(UUID(as_uuid=True), ForeignKey("messages.id", ondelete="SET NULL"), nullable=True)
    notion_database_id = Column(UUID(as_uuid=True), ForeignKey("notion_databases.id", ondelete="SET NULL"), nullable=True)
    title = Column(Text, nullable=False)
    due_date = Column(Date)
    status = Column(String, default="pending", nullable=False)
    notion_page_id = Column(String)
    neo4j_node_id = Column(String)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    user = relationship("User", back_populates="tasks")


class Reminder(Base):
    __tablename__ = "reminders"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    message_id = Column(UUID(as_uuid=True), ForeignKey("messages.id", ondelete="SET NULL"), nullable=True)
    task_id = Column(UUID(as_uuid=True), ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True)
    text = Column(Text, nullable=False)
    remind_at = Column(DateTime(timezone=True), nullable=False)
    is_sent = Column(Boolean, default=False, nullable=False)
    neo4j_node_id = Column(String)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    user = relationship("User", back_populates="reminders")


class VoiceMessage(Base):
    __tablename__ = "voice_messages"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    message_id = Column(UUID(as_uuid=True), ForeignKey("messages.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    telegram_file_id = Column(String)
    transcription = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="voice_messages")
    message = relationship("Message", back_populates="voice_message")


class NotionDatabase(Base):
    __tablename__ = "notion_databases"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    notion_db_id = Column(String, nullable=False)
    name = Column(String)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="notion_databases")


# indexes for performance
Index('idx_messages_user_id', Message.user_id)
Index('idx_captures_user_id', Capture.user_id)
Index('idx_tasks_user_status', Task.user_id, Task.status)
Index('idx_reminders_remind_at', Reminder.remind_at, Reminder.is_sent)
Index('idx_notion_databases_user', NotionDatabase.user_id)