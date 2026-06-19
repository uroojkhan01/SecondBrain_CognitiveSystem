# db_hooks.py
# Called after Neo4j saves — mirrors data into Supabase/PostgreSQL

from assistant_backend_1.models.db import (
    upsert_user,
    get_user_by_chat_id,
    save_message,
    save_memory,
    save_task,
    save_reminder,
    save_capture,
    mark_reminder_sent,
)


def hook_upsert_user(chat_id: str, first_name: str = None, username: str = None) -> dict | None:
    """Mirror user into Supabase. Called on every incoming message."""
    try:
        return upsert_user(chat_id, first_name, username)
    except Exception as e:
        print(f"[DB] Failed to upsert user {chat_id}: {e}")
        return None


def hook_save_message(
    chat_id: str,
    raw_input: str,
    input_type: str = "text",
    intent: str = None,
    llm_raw_response: dict = None
) -> dict | None:
    """Save incoming message to Supabase after LLM processes it."""
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


def hook_save_capture(
    chat_id: str,
    raw_text: str,
    message_id: str = None
) -> dict | None:
    """Save raw capture to Supabase before processing."""
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