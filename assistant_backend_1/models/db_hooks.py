# db_hooks.py
# Mirrors all Neo4j saves into Supabase/PostgreSQL
# Called alongside memory_journal.py functions in llm_conversation.py

from assistant_backend_1.models.db import (
    upsert_user,
    get_user_by_chat_id,
    save_message,
    save_memory,
    save_task,
    update_task_status,
    save_reminder,
    mark_reminder_sent,
    save_capture,
    save_voice_message,
)
from assistant_backend_1.models.db import db


# ─── User ─────────────────────────────────────────────────────────

def hook_upsert_user(chat_id: str, first_name: str = None, username: str = None) -> dict | None:
    """Mirror user into Supabase. Called on every incoming message."""
    try:
        return upsert_user(chat_id, first_name, username)
    except Exception as e:
        print(f"[DB] Failed to upsert user {chat_id}: {e}")
        return None


def hook_get_user(chat_id: str) -> dict | None:
    """Get user by chat_id. Used internally by other hooks."""
    try:
        return get_user_by_chat_id(chat_id)
    except Exception as e:
        print(f"[DB] Failed to get user {chat_id}: {e}")
        return None


# ─── Messages ─────────────────────────────────────────────────────

def hook_save_message(
    chat_id: str,
    raw_input: str,
    input_type: str = "text",
    intent: str = None,
    llm_raw_response: dict = None
) -> dict | None:
    """Save every incoming message to Supabase. Called before routing intent."""
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


def hook_save_voice_message(
    chat_id: str,
    message_id: str,
    telegram_file_id: str = None,
    transcription: str = None
) -> dict | None:
    """Save voice note metadata after transcription."""
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


# ─── Captures ─────────────────────────────────────────────────────

def hook_save_capture(
    chat_id: str,
    raw_text: str,
    message_id: str = None
) -> dict | None:
    """Save raw input before any processing. First thing called on every message."""
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


# ─── Memories ─────────────────────────────────────────────────────

def hook_save_memory(
    chat_id: str,
    summary: str,
    category: str = None,
    neo4j_node_id: str = None,
    message_id: str = None
) -> dict | None:
    """Mirror memory into Supabase after Neo4j saves it."""
    try:
        user = get_user_by_chat_id(chat_id)
        if not user:
            return None
        return save_memory(
            user_id=user["id"],
            summary=summary,
            message_id=message_id,
            category=category,
            neo4j_node_id=neo4j_node_id
        )
    except Exception as e:
        print(f"[DB] Failed to save memory for {chat_id}: {e}")
        return None


# ─── Tasks ────────────────────────────────────────────────────────

def hook_save_task(
    chat_id: str,
    title: str,
    due_date: str = None,
    neo4j_node_id: str = None,
    message_id: str = None
) -> dict | None:
    """Mirror task into Supabase after Neo4j saves it."""
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
    """Mark task done in Supabase when user says 'mark done'."""
    try:
        user = get_user_by_chat_id(chat_id)
        if not user:
            return
        # find task by title match
        result = (
            db.table("tasks")
            .select("id")
            .eq("user_id", user["id"])
            .ilike("title", f"%{title}%")
            .eq("status", "pending")
            .limit(1)
            .execute()
        )
        if result.data:
            update_task_status(result.data[0]["id"], "done")
    except Exception as e:
        print(f"[DB] Failed to mark task done for {chat_id}: {e}")


def hook_cancel_task(chat_id: str, title: str) -> None:
    """Mark task cancelled in Supabase when user says 'cancel task'."""
    try:
        user = get_user_by_chat_id(chat_id)
        if not user:
            return
        result = (
            db.table("tasks")
            .select("id")
            .eq("user_id", user["id"])
            .ilike("title", f"%{title}%")
            .eq("status", "pending")
            .limit(1)
            .execute()
        )
        if result.data:
            update_task_status(result.data[0]["id"], "cancelled")
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
    """Mirror reminder into Supabase after Neo4j saves it."""
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


def hook_mark_reminder_sent(chat_id: str, reminder_id: str) -> None:
    """Mark reminder sent after Telegram message is fired."""
    try:
        mark_reminder_sent(reminder_id)
    except Exception as e:
        print(f"[DB] Failed to mark reminder sent {reminder_id}: {e}")


# ─── Habits ───────────────────────────────────────────────────────

def hook_save_habit(chat_id: str, name: str, value: str) -> dict | None:
    """Save habit log to Supabase. Creates habit if it doesn't exist."""
    try:
        user = get_user_by_chat_id(chat_id)
        if not user:
            return None

        # upsert habit
        habit_result = db.table("habits").upsert(
            {"user_id": user["id"], "name": name},
            on_conflict="user_id,name"
        ).execute()
        habit = habit_result.data[0]

        # log the entry
        log_result = db.table("habit_logs").insert(
            {
                "user_id": user["id"],
                "habit_id": habit["id"],
                "value": value,
            }
        ).execute()
        return log_result.data[0]
    except Exception as e:
        print(f"[DB] Failed to save habit for {chat_id}: {e}")
        return None