# db.py
# Database client using SQLAlchemy + psycopg
# All functions are synchronous for simplicity

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session
from dotenv import load_dotenv
import os
from datetime import datetime, timezone

from assistant_backend_1.models.database import (
    User, Message, Capture, Task, Reminder, VoiceMessage, NotionDatabase
)

load_dotenv()

engine = create_engine(os.getenv("DATABASE_URL"))
SessionLocal = sessionmaker(bind=engine)


def get_session() -> Session:
    return SessionLocal()


#  Users 

def upsert_user(chat_id: str, first_name: str = None, username: str = None) -> dict:
    """Insert user if not exists, update name/username if they do."""
    with get_session() as session:
        user = session.query(User).filter_by(chat_id=chat_id).first()
        if user:
            user.first_name = first_name
            user.username = username
        else:
            user = User(chat_id=chat_id, first_name=first_name, username=username)
            session.add(user)
        session.commit()
        session.refresh(user)
        return _user_to_dict(user)


def get_user_by_chat_id(chat_id: str) -> dict | None:
    with get_session() as session:
        user = session.query(User).filter_by(chat_id=chat_id).first()
        return _user_to_dict(user) if user else None


def set_notion_connected(user_id: str, connected: bool) -> dict | None:
    with get_session() as session:
        user = session.query(User).filter_by(id=user_id).first()
        if not user:
            return None
        user.notion_connected = connected
        session.commit()
        session.refresh(user)
        return _user_to_dict(user)


def save_notion_token(user_id: str, token: str) -> dict | None:
    with get_session() as session:
        user = session.query(User).filter_by(id=user_id).first()
        if not user:
            return None
        user.notion_access_token = token
        session.commit()
        session.refresh(user)
        return _user_to_dict(user)


#  Notion Databases 

def save_notion_database(user_id: str, notion_db_id: str, name: str = None) -> dict:
    with get_session() as session:
        notion_db = NotionDatabase(user_id=user_id, notion_db_id=notion_db_id, name=name)
        session.add(notion_db)
        session.commit()
        session.refresh(notion_db)
        return _to_dict(notion_db)


def get_notion_databases(user_id: str) -> list:
    with get_session() as session:
        dbs = session.query(NotionDatabase).filter_by(user_id=user_id).order_by(NotionDatabase.created_at).all()
        return [_to_dict(db) for db in dbs]


def delete_notion_database(notion_database_id: str) -> None:
    with get_session() as session:
        db = session.query(NotionDatabase).filter_by(id=notion_database_id).first()
        if db:
            session.delete(db)
            session.commit()


#  Messages 

def save_message(
    user_id: str,
    raw_input: str,
    input_type: str = "text",
    intent: str = None,
    llm_raw_response: dict = None
) -> dict:
    with get_session() as session:
        msg = Message(
            user_id=user_id,
            raw_input=raw_input,
            input_type=input_type,
            intent=intent,
            llm_raw_response=llm_raw_response
        )
        session.add(msg)
        session.commit()
        session.refresh(msg)
        return _to_dict(msg)


def get_recent_messages(user_id: str, limit: int = 10) -> list:
    with get_session() as session:
        msgs = (
            session.query(Message)
            .filter_by(user_id=user_id)
            .order_by(Message.created_at.desc())
            .limit(limit)
            .all()
        )
        return [_to_dict(m) for m in msgs]


#  Captures 

def save_capture(
    user_id: str,
    raw_text: str,
    message_id: str = None,
    source: str = "telegram"
) -> dict:
    with get_session() as session:
        capture = Capture(
            user_id=user_id,
            raw_text=raw_text,
            message_id=message_id,
            source=source
        )
        session.add(capture)
        session.commit()
        session.refresh(capture)
        return _to_dict(capture)


def mark_capture_processed(capture_id: str) -> dict | None:
    with get_session() as session:
        capture = session.query(Capture).filter_by(id=capture_id).first()
        if not capture:
            return None
        capture.processed = True
        session.commit()
        session.refresh(capture)
        return _to_dict(capture)


#  Voice Messages 

def save_voice_message(
    message_id: str,
    user_id: str,
    telegram_file_id: str = None,
    transcription: str = None
) -> dict:
    with get_session() as session:
        voice = VoiceMessage(
            message_id=message_id,
            user_id=user_id,
            telegram_file_id=telegram_file_id,
            transcription=transcription
        )
        session.add(voice)
        session.commit()
        session.refresh(voice)
        return _to_dict(voice)


def update_voice_transcription(voice_message_id: str, transcription: str) -> dict | None:
    with get_session() as session:
        voice = session.query(VoiceMessage).filter_by(id=voice_message_id).first()
        if not voice:
            return None
        voice.transcription = transcription
        session.commit()
        session.refresh(voice)
        return _to_dict(voice)


#  Tasks 

def save_task(
    user_id: str,
    title: str,
    message_id: str = None,
    notion_database_id: str = None,
    due_date: str = None,
    notion_page_id: str = None,
    neo4j_node_id: str = None
) -> dict:
    with get_session() as session:
        task = Task(
            user_id=user_id,
            message_id=message_id,
            notion_database_id=notion_database_id,
            title=title,
            due_date=due_date,
            notion_page_id=notion_page_id,
            neo4j_node_id=neo4j_node_id
        )
        session.add(task)
        session.commit()
        session.refresh(task)
        return _to_dict(task)


def get_tasks(user_id: str, status: str = None) -> list:
    with get_session() as session:
        query = session.query(Task).filter_by(user_id=user_id).order_by(Task.created_at.desc())
        if status:
            query = query.filter_by(status=status)
        return [_to_dict(t) for t in query.all()]


def update_task_status(task_id: str, status: str) -> dict | None:
    with get_session() as session:
        task = session.query(Task).filter_by(id=task_id).first()
        if not task:
            return None
        task.status = status
        session.commit()
        session.refresh(task)
        return _to_dict(task)


def update_task(task_id: str, title: str = None, due_date: str = None) -> dict | None:
    with get_session() as session:
        task = session.query(Task).filter_by(id=task_id).first()
        if not task:
            return None
        if title:
            task.title = title
        if due_date:
            task.due_date = due_date
        session.commit()
        session.refresh(task)
        return _to_dict(task)


def delete_task(task_id: str) -> None:
    with get_session() as session:
        task = session.query(Task).filter_by(id=task_id).first()
        if task:
            session.delete(task)
            session.commit()


#  Reminders 

def save_reminder(
    user_id: str,
    text: str,
    remind_at: str,
    message_id: str = None,
    task_id: str = None,
    neo4j_node_id: str = None
) -> dict:
    # Parse ISO string to datetime so SQLAlchemy/psycopg gets the right type
    if isinstance(remind_at, str):
        remind_at = datetime.fromisoformat(remind_at)
    with get_session() as session:
        reminder = Reminder(
            user_id=user_id,
            message_id=message_id,
            task_id=task_id,
            text=text,
            remind_at=remind_at,
            neo4j_node_id=neo4j_node_id
        )
        session.add(reminder)
        session.commit()
        session.refresh(reminder)
        return _to_dict(reminder)


def get_due_reminders() -> list:
    with get_session() as session:
        now = datetime.now(timezone.utc)
        reminders = (
            session.query(Reminder)
            .filter(Reminder.is_sent == False, Reminder.remind_at <= now)
            .all()
        )
        # include chat_id for telegram sending
        result = []
        for r in reminders:
            d = _to_dict(r)
            user = session.query(User).filter_by(id=r.user_id).first()
            d["chat_id"] = user.chat_id if user else None
            result.append(d)
        return result


def get_reminders_for_user(user_id: str, include_sent: bool = False) -> list:
    with get_session() as session:
        query = session.query(Reminder).filter_by(user_id=user_id).order_by(Reminder.remind_at)
        if not include_sent:
            query = query.filter(Reminder.is_sent == False)
        return [_to_dict(r) for r in query.all()]


def mark_reminder_sent(reminder_id: str) -> dict | None:
    with get_session() as session:
        reminder = session.query(Reminder).filter_by(id=reminder_id).first()
        if not reminder:
            return None
        reminder.is_sent = True
        session.commit()
        session.refresh(reminder)
        return _to_dict(reminder)


def update_reminder(reminder_id: str, text: str = None, remind_at: str = None) -> dict | None:
    with get_session() as session:
        reminder = session.query(Reminder).filter_by(id=reminder_id).first()
        if not reminder:
            return None
        if text:
            reminder.text = text
        if remind_at:
            reminder.remind_at = remind_at
            reminder.is_sent = False
        session.commit()
        session.refresh(reminder)
        return _to_dict(reminder)


def delete_reminder(reminder_id: str) -> None:
    with get_session() as session:
        reminder = session.query(Reminder).filter_by(id=reminder_id).first()
        if reminder:
            session.delete(reminder)
            session.commit()

def get_voice_message(message_id: str) -> dict | None:
    with get_session() as session:
        voice = session.query(VoiceMessage).filter_by(message_id=message_id).first()
        return _to_dict(voice) if voice else None


def get_next_reminder(user_id: str) -> dict | None:
    with get_session() as session:
        now = datetime.now(timezone.utc)
        reminder = (
            session.query(Reminder)
            .filter(
                Reminder.user_id == user_id,
                Reminder.is_sent == False,
                Reminder.remind_at >= now
            )
            .order_by(Reminder.remind_at)
            .first()
        )
        return _to_dict(reminder) if reminder else None


def update_task_notion_id(task_id: str, notion_page_id: str) -> dict | None:
    with get_session() as session:
        task = session.query(Task).filter_by(id=task_id).first()
        if not task:
            return None
        task.notion_page_id = notion_page_id
        session.commit()
        session.refresh(task)
        return _to_dict(task)

def update_message_intent(message_id: str, intent: str, llm_raw_response: dict = None) -> dict:
    with get_session() as session:
        msg = session.query(Message).filter_by(id=message_id).first()
        if msg:
            msg.intent = intent
            if llm_raw_response:
                msg.llm_raw_response = llm_raw_response
            session.commit()
            session.refresh(msg)
            return _to_dict(msg)

def get_all_users() -> list:
    """Get all users — used by reminders background job to find chat_ids."""
    with get_session() as session:
        users = session.query(User).all()
        return [_user_to_dict(u) for u in users]
        
#  Helpers 

def _user_to_dict(user: User) -> dict:
    return {
        "id": str(user.id),
        "chat_id": user.chat_id,
        "first_name": user.first_name,
        "username": user.username,
        "notion_connected": user.notion_connected,
        "notion_access_token": user.notion_access_token,
        "created_at": str(user.created_at),
        "updated_at": str(user.updated_at),
    }


def _to_dict(obj) -> dict:
    """Generic converter for SQLAlchemy models to dict."""
    result = {}
    for col in obj.__table__.columns:
        val = getattr(obj, col.name)
        if val is None:
            result[col.name] = None
        elif isinstance(val, bool):
            result[col.name] = val
        elif hasattr(val, "isoformat"):
            result[col.name] = val.isoformat()
        else:
            result[col.name] = str(val)
    return result