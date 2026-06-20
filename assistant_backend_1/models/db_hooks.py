# db_hooks.py
# Called from llm_conversation.py and telegram_handler.py
# Mirrors data into Postgres alongside Neo4j saves

from assistant_backend_1.models.db import (
    upsert_user,
    get_user_by_chat_id,
    save_message,
    save_capture,
    save_task,
    save_reminder,
    save_voice_message,
    update_task_status,
    mark_reminder_sent,
)
from assistant_backend_1.models.database import Task
from assistant_backend_1.models.db import get_session


# ─── User ─────────────────────────────────────────────────────────

def hook_upsert_user(chat_id: str, first_name: str = None, username: str = None) -> dict | None:
    try:
        return upsert_user(chat_id, first_name, username)
    except Exception as e:
        print(f"[DB] Failed to upsert user {chat_id}: {e}")
        return None


# ─── Messages ─────────────────────────────────────────────────────

def hook_save_message(
    chat_id: str,
    raw_input: str,
    input_type: str = "text",
    intent: str = None,
    llm_raw_response: dict = None
) -> dict | None:
    try:
        user = get_user_by_chat_id(chat_id)
        if not user:
            return None
        return save_message(
            user_id=user["id"],
            raw_input=raw_input,
            input_type=input_type,
            intent=intent,
            llm_raw_response=llm_raw_response
        )
    except Exception as e:
        print(f"[DB] Failed to save message for {chat_id}: {e}")
        return None


# ─── Captures ─────────────────────────────────────────────────────

def hook_save_capture(chat_id: str, raw_text: str, message_id: str = None) -> dict | None:
    try:
        user = get_user_by_chat_id(chat_id)
        if not user:
            return None
        return save_capture(
            user_id=user["id"],
            raw_text=raw_text,
            message_id=message_id,
            source="telegram"
        )
    except Exception as e:
        print(f"[DB] Failed to save capture for {chat_id}: {e}")
        return None


# ─── Voice ────────────────────────────────────────────────────────

def hook_save_voice_message(
    chat_id: str,
    message_id: str,
    telegram_file_id: str = None,
    transcription: str = None
) -> dict | None:
    try:
        user = get_user_by_chat_id(chat_id)
        if not user:
            return None
        return save_voice_message(
            message_id=message_id,
            user_id=user["id"],
            telegram_file_id=telegram_file_id,
            transcription=transcription
        )
    except Exception as e:
        print(f"[DB] Failed to save voice message for {chat_id}: {e}")
        return None


# ─── Tasks ────────────────────────────────────────────────────────

def hook_save_task(
    chat_id: str,
    title: str,
    due_date: str = None,
    neo4j_node_id: str = None,
    message_id: str = None
) -> dict | None:
    try:
        user = get_user_by_chat_id(chat_id)
        if not user:
            return None
        return save_task(
            user_id=user["id"],
            title=title,
            message_id=message_id,
            due_date=due_date,
            neo4j_node_id=neo4j_node_id
        )
    except Exception as e:
        print(f"[DB] Failed to save task for {chat_id}: {e}")
        return None


def hook_mark_task_done(chat_id: str, title: str) -> None:
    try:
        user = get_user_by_chat_id(chat_id)
        if not user:
            return
        with get_session() as session:
            task = (
                session.query(Task)
                .filter(
                    Task.user_id == user["id"],
                    Task.title.ilike(f"%{title}%"),
                    Task.status == "pending"
                )
                .first()
            )
            if task:
                task.status = "done"
                session.commit()
    except Exception as e:
        print(f"[DB] Failed to mark task done for {chat_id}: {e}")


def hook_cancel_task(chat_id: str, title: str) -> None:
    try:
        user = get_user_by_chat_id(chat_id)
        if not user:
            return
        with get_session() as session:
            task = (
                session.query(Task)
                .filter(
                    Task.user_id == user["id"],
                    Task.title.ilike(f"%{title}%"),
                    Task.status == "pending"
                )
                .first()
            )
            if task:
                task.status = "cancelled"
                session.commit()
    except Exception as e:
        print(f"[DB] Failed to cancel task for {chat_id}: {e}")


# ─── Reminders ────────────────────────────────────────────────────

def hook_save_reminder(
    chat_id: str,
    text: str,
    remind_at: str,
    neo4j_node_id: str = None,
    message_id: str = None
) -> dict | None:
    try:
        user = get_user_by_chat_id(chat_id)
        if not user:
            return None
        return save_reminder(
            user_id=user["id"],
            text=text,
            remind_at=remind_at,
            message_id=message_id,
            neo4j_node_id=neo4j_node_id
        )
    except Exception as e:
        print(f"[DB] Failed to save reminder for {chat_id}: {e}")
        return None


def hook_mark_reminder_sent(reminder_id: str) -> None:
    try:
        mark_reminder_sent(reminder_id)
    except Exception as e:
        print(f"[DB] Failed to mark reminder sent {reminder_id}: {e}")