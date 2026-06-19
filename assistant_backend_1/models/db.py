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

def save_notion_token(user_id: str, token: str) -> dict:
    result = db.table("users").update(
        {"notion_access_token": token}
    ).eq("id", user_id).execute()
    return result.data[0]

# notion_databases

def save_notion_database(user_id: str, notion_db_id: str, name: str = None) -> dict:
    """
    Store a Notion database ID for a user after they connect their Notion account.
    notion_db_id is the ID from the Notion API.
    """
    result = db.table("notion_databases").insert(
        {
            "user_id": user_id,
            "notion_db_id": notion_db_id,
            "name": name,
        }
    ).execute()
    return result.data[0]


def get_notion_databases(user_id: str) -> list:
    result = (
        db.table("notion_databases")
        .select("*")
        .eq("user_id", user_id)
        .order("created_at")
        .execute()
    )
    return result.data


def delete_notion_database(notion_database_id: str) -> None:
    db.table("notion_databases").delete().eq("id", notion_database_id).execute()


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


# voice_messages

def save_voice_message(
    message_id: str,
    user_id: str,
    telegram_file_id: str = None,
    transcription: str = None
) -> dict:
    """
    Store voice note metadata linked to a message.
    telegram_file_id: file ID from Telegram, used to fetch audio if needed.
    transcription: text output from the transcription agent, can be updated later.
    """
    result = db.table("voice_messages").insert(
        {
            "message_id": message_id,
            "user_id": user_id,
            "telegram_file_id": telegram_file_id,
            "transcription": transcription,
        }
    ).execute()
    return result.data[0]


def update_voice_transcription(voice_message_id: str, transcription: str) -> dict:
    """Called by the transcription agent once it finishes processing the audio."""
    result = db.table("voice_messages").update(
        {"transcription": transcription}
    ).eq("id", voice_message_id).execute()
    return result.data[0]


def get_voice_message(message_id: str) -> dict | None:
    result = (
        db.table("voice_messages")
        .select("*")
        .eq("message_id", message_id)
        .execute()
    )
    return result.data[0] if result.data else None


# memories

def save_memory(
    user_id: str,
    summary: str,
    message_id: str = None,
    category: str = None,
    event_date: str = None,
    neo4j_node_id: str = None
) -> dict:
    """
    event_date: when the event actually happened, e.g. '2026-05-28'
                separate from created_at which is when it was logged
    """
    result = db.table("memories").insert(
        {
            "user_id": user_id,
            "message_id": message_id,
            "summary": summary,
            "category": category,
            "event_date": event_date,
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


def get_memories_by_date(user_id: str, event_date: str) -> list:
    """
    Fetch memories by the date the event actually happened.
    event_date: ISO date string e.g. '2026-05-28'
    """
    result = (
        db.table("memories")
        .select("*")
        .eq("user_id", user_id)
        .eq("event_date", event_date)
        .order("created_at", desc=True)
        .execute()
    )
    return result.data


def search_memories(user_id: str, keyword: str) -> list:
    """
    Case-insensitive keyword search across memory summaries.
    Used when user asks 'what did I say about my doctor'.
    """
    result = (
        db.table("memories")
        .select("*")
        .eq("user_id", user_id)
        .ilike("summary", f"%{keyword}%")
        .order("created_at", desc=True)
        .execute()
    )
    return result.data


def update_memory_neo4j_id(memory_id: str, neo4j_node_id: str) -> dict:
    result = db.table("memories").update(
        {"neo4j_node_id": neo4j_node_id}
    ).eq("id", memory_id).execute()
    return result.data[0]


def delete_memory(memory_id: str) -> None:
    """Called when user says 'forget that' or 'delete that memory'."""
    db.table("memories").delete().eq("id", memory_id).execute()


# tasks

def save_task(
    user_id: str,
    title: str,
    message_id: str = None,
    notion_database_id: str = None,
    due_date: str = None,
    notion_page_id: str = None,
    neo4j_node_id: str = None
) -> dict:
    """
    due_date: ISO date string e.g. '2026-05-30'
    notion_database_id: FK to notion_databases table, nullable
    """
    result = db.table("tasks").insert(
        {
            "user_id": user_id,
            "message_id": message_id,
            "notion_database_id": notion_database_id,
            "title": title,
            "due_date": due_date,
            "notion_page_id": notion_page_id,
            "neo4j_node_id": neo4j_node_id,
        }
    ).execute()
    return result.data[0]


def get_tasks(user_id: str, status: str = None) -> list:
    """status options: pending, done, cancelled"""
    query = (
        db.table("tasks")
        .select("*")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
    )
    if status:
        query = query.eq("status", status)
    return query.execute().data


def update_task(task_id: str, title: str = None, due_date: str = None) -> dict:
    """Update task title and/or due date."""
    updates = {}
    if title is not None:
        updates["title"] = title
    if due_date is not None:
        updates["due_date"] = due_date
    result = db.table("tasks").update(updates).eq("id", task_id).execute()
    return result.data[0]


def update_task_status(task_id: str, status: str) -> dict:
    """status options: pending, done, cancelled"""
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


# reminders

def save_reminder(
    user_id: str,
    text: str,
    remind_at: str,
    message_id: str = None,
    task_id: str = None,
    neo4j_node_id: str = None
) -> dict:
    """
    remind_at: ISO 8601 with timezone e.g. '2026-05-30T09:00:00+00:00'
    task_id: nullable, link to a task if reminder is task-related
    """
    result = db.table("reminders").insert(
        {
            "user_id": user_id,
            "message_id": message_id,
            "task_id": task_id,
            "text": text,
            "remind_at": remind_at,
            "neo4j_node_id": neo4j_node_id,
        }
    ).execute()
    return result.data[0]


def get_due_reminders() -> list:
    """
    Returns all unsent reminders whose remind_at is now or in the past.
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


def get_next_reminder(user_id: str) -> dict | None:
    """Returns the next upcoming unsent reminder for a user."""
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    result = (
        db.table("reminders")
        .select("*")
        .eq("user_id", user_id)
        .eq("is_sent", False)
        .gte("remind_at", now)
        .order("remind_at")
        .limit(1)
        .execute()
    )
    return result.data[0] if result.data else None


def mark_reminder_sent(reminder_id: str) -> dict:
    result = db.table("reminders").update(
        {"is_sent": True}
    ).eq("id", reminder_id).execute()
    return result.data[0]


def update_reminder(reminder_id: str, text: str = None, remind_at: str = None) -> dict:
    """Update reminder text and/or time."""
    updates = {}
    if text is not None:
        updates["text"] = text
    if remind_at is not None:
        updates["remind_at"] = remind_at
        updates["is_sent"] = False
    result = db.table("reminders").update(updates).eq("id", reminder_id).execute()
    return result.data[0]


def delete_reminder(reminder_id: str) -> None:
    db.table("reminders").delete().eq("id", reminder_id).execute()

# captures

def save_capture(
    user_id: str,
    raw_text: str,
    message_id: str = None,
    source: str = "telegram"
) -> dict:
    """Store raw incoming message before processing."""
    result = db.table("captures").insert(
        {
            "user_id": user_id,
            "message_id": message_id,
            "raw_text": raw_text,
            "source": source,
        }
    ).execute()
    return result.data[0]


def mark_capture_processed(capture_id: str) -> dict:
    result = db.table("captures").update(
        {"processed": True}
    ).eq("id", capture_id).execute()
    return result.data[0]


def get_unprocessed_captures(user_id: str) -> list:
    result = (
        db.table("captures")
        .select("*")
        .eq("user_id", user_id)
        .eq("processed", False)
        .order("created_at")
        .execute()
    )
    return result.data


# RAG / embeddings

def save_memory_with_embedding(
    user_id: str,
    summary: str,
    embedding: list,
    message_id: str = None,
    category: str = None,
    event_date: str = None,
    neo4j_node_id: str = None
) -> dict:
    """Save memory with vector embedding for semantic search."""
    result = db.table("memories").insert(
        {
            "user_id": user_id,
            "message_id": message_id,
            "summary": summary,
            "category": category,
            "event_date": event_date,
            "neo4j_node_id": neo4j_node_id,
            "embedding": embedding,
        }
    ).execute()
    return result.data[0]


def search_memories_by_embedding(
    user_id: str,
    query_embedding: list,
    limit: int = 5,
    threshold: float = 0.7
) -> list:
    """
    Semantic search across memories using cosine similarity.
    query_embedding: vector from the same embedding model used to save.
    threshold: minimum similarity score (0-1), higher = more similar.
    """
    result = db.rpc(
        "match_memories",
        {
            "query_embedding": query_embedding,
            "match_user_id": user_id,
            "match_threshold": threshold,
            "match_count": limit,
        }
    ).execute()
    return result.data