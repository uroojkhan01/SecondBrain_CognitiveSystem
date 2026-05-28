import os
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()


def get_client() -> Client:
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_KEY")
    if not url or not key:
        raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_KEY are not set in .env")
    return create_client(url, key)


db: Client = get_client()


# users

def upsert_user(chat_id: str, first_name: str = None, username: str = None) -> dict:
    """
    Insert user if they don't exist, otherwise update their name/username.
    Called on every incoming Telegram message.
    """
    result = db.table("users").upsert(
        {
            "chat_id": chat_id,
            "first_name": first_name,
            "username": username,
        },
        on_conflict="chat_id"
    ).execute()
    return result.data[0]


def get_user_by_chat_id(chat_id: str) -> dict | None:
    result = db.table("users").select("*").eq("chat_id", chat_id).execute()
    return result.data[0] if result.data else None


def set_notion_connected(user_id: str, connected: bool) -> dict:
    result = db.table("users").update(
        {"notion_connected": connected}
    ).eq("id", user_id).execute()
    return result.data[0]


# messages

def save_message(
    user_id: str,
    raw_input: str,
    input_type: str = "text",
    intent: str = None,
    llm_raw_response: dict = None
) -> dict:
    result = db.table("messages").insert(
        {
            "user_id": user_id,
            "raw_input": raw_input,
            "input_type": input_type,
            "intent": intent,
            "llm_raw_response": llm_raw_response,
        }
    ).execute()
    return result.data[0]


def get_recent_messages(user_id: str, limit: int = 10) -> list:
    """Returns most recent messages for a user, useful for LLM conversation context."""
    result = (
        db.table("messages")
        .select("*")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    return result.data


# memories

def save_memory(
    user_id: str,
    summary: str,
    message_id: str = None,
    category: str = None,
    neo4j_node_id: str = None
) -> dict:
    result = db.table("memories").insert(
        {
            "user_id": user_id,
            "message_id": message_id,
            "summary": summary,
            "category": category,
            "neo4j_node_id": neo4j_node_id,
        }
    ).execute()
    return result.data[0]


def get_memories(user_id: str, category: str = None, limit: int = 20) -> list:
    query = (
        db.table("memories")
        .select("*")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .limit(limit)
    )
    if category:
        query = query.eq("category", category)
    return query.execute().data


def update_memory_neo4j_id(memory_id: str, neo4j_node_id: str) -> dict:
    result = db.table("memories").update(
        {"neo4j_node_id": neo4j_node_id}
    ).eq("id", memory_id).execute()
    return result.data[0]



# reminders

def save_reminder(
    user_id: str,
    text: str,
    remind_at: str,
    message_id: str = None,
    neo4j_node_id: str = None
) -> dict:
    """
    remind_at must be an ISO 8601 string with timezone, e.g. '2026-05-30T09:00:00+00:00'
    """
    result = db.table("reminders").insert(
        {
            "user_id": user_id,
            "message_id": message_id,
            "text": text,
            "remind_at": remind_at,
            "neo4j_node_id": neo4j_node_id,
        }
    ).execute()
    return result.data[0]


def get_due_reminders() -> list:
    """
    Returns all unsent reminders whose remind_at is in the past or now.
    Called by the background job on a schedule.
    Includes user chat_id so the job knows where to send the Telegram message.
    """
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    result = (
        db.table("reminders")
        .select("*, users(chat_id)")
        .eq("is_sent", False)
        .lte("remind_at", now)
        .execute()
    )
    return result.data


def mark_reminder_sent(reminder_id: str) -> dict:
    result = db.table("reminders").update(
        {"is_sent": True}
    ).eq("id", reminder_id).execute()
    return result.data[0]


def get_reminders_for_user(user_id: str, include_sent: bool = False) -> list:
    query = (
        db.table("reminders")
        .select("*")
        .eq("user_id", user_id)
        .order("remind_at")
    )
    if not include_sent:
        query = query.eq("is_sent", False)
    return query.execute().data


def delete_reminder(reminder_id: str) -> None:
    db.table("reminders").delete().eq("id", reminder_id).execute()


def reschedule_reminder(reminder_id: str, new_remind_at: str) -> dict:
    result = db.table("reminders").update(
        {"remind_at": new_remind_at, "is_sent": False}
    ).eq("id", reminder_id).execute()
    return result.data[0]


# tasks

def save_task(
    user_id: str,
    title: str,
    message_id: str = None,
    due_date: str = None,
    notion_page_id: str = None,
    neo4j_node_id: str = None
) -> dict:
    """
    due_date must be an ISO date string, e.g. '2026-05-30'
    """
    result = db.table("tasks").insert(
        {
            "user_id": user_id,
            "message_id": message_id,
            "title": title,
            "due_date": due_date,
            "notion_page_id": notion_page_id,
            "neo4j_node_id": neo4j_node_id,
        }
    ).execute()
    return result.data[0]


def get_tasks(user_id: str, status: str = None) -> list:
    """status can be: pending, done, cancelled"""
    query = (
        db.table("tasks")
        .select("*")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
    )
    if status:
        query = query.eq("status", status)
    return query.execute().data


def update_task_status(task_id: str, status: str) -> dict:
    result = db.table("tasks").update(
        {"status": status}
    ).eq("id", task_id).execute()
    return result.data[0]


def update_task_notion_id(task_id: str, notion_page_id: str) -> dict:
    result = db.table("tasks").update(
        {"notion_page_id": notion_page_id}
    ).eq("id", task_id).execute()
    return result.data[0]


def delete_task(task_id: str) -> None:
    db.table("tasks").delete().eq("id", task_id).execute()