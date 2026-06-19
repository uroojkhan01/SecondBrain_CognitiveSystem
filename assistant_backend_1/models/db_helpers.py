# db_helpers.py
# Drop-in replacement for helpers.py — uses Supabase instead of JSON file

from assistant_backend_1.models.db import (
    upsert_user,
    get_user_by_chat_id,
    save_notion_token,
    save_notion_database,
    set_notion_connected,
)
from assistant_backend_1.config import (
    NOTION_CLIENT_ID,
    NOTION_CLIENT_SECRET,
    NOTION_REDIRECT_URI,
)


def save_user(chat_id: str, first_name: str = None, username: str = None) -> dict:
    """Upsert user into Supabase. Replaces JSON save_user."""
    try:
        user = upsert_user(chat_id, first_name, username)
        print(f"✅ User saved to Supabase: {chat_id}")
        return user
    except Exception as e:
        print(f"[DB] Failed to save user {chat_id}: {e}")
        return {}


def load_users() -> dict:
    """
    Not needed with Supabase — kept for compatibility.
    Returns empty dict so any code still calling this doesn't crash.
    """
    return {}


def is_notion_connected(chat_id: str) -> bool:
    """Check if user has connected Notion — reads from Supabase."""
    try:
        user = get_user_by_chat_id(chat_id)
        if not user:
            return False
        return bool(user.get("notion_access_token"))
    except Exception as e:
        print(f"[DB] Failed to check notion connection for {chat_id}: {e}")
        return False


def get_oauth_url(chat_id: str) -> str:
    """Generate Notion OAuth URL. Same logic as helpers.py."""
    return (
        f"https://api.notion.com/v1/oauth/authorize"
        f"?client_id={NOTION_CLIENT_ID}"
        f"&response_type=code"
        f"&owner=user"
        f"&redirect_uri={NOTION_REDIRECT_URI}"
        f"&state=tg_{str(chat_id)}"
    )


def save_notion_user_token(chat_id: str, token: str) -> None:
    """Save Notion OAuth token to Supabase after OAuth callback."""
    try:
        user = get_user_by_chat_id(chat_id)
        if not user:
            upsert_user(chat_id)
            user = get_user_by_chat_id(chat_id)
        save_notion_token(user["id"], token)
        set_notion_connected(user["id"], True)
        print(f"✅ Notion token saved for {chat_id}")
    except Exception as e:
        print(f"[DB] Failed to save notion token for {chat_id}: {e}")


def save_notion_user_database(chat_id: str, notion_db_id: str, name: str = None) -> None:
    """Save connected Notion database to Supabase."""
    try:
        user = get_user_by_chat_id(chat_id)
        if not user:
            return
        save_notion_database(user["id"], notion_db_id, name)
        print(f"✅ Notion database saved for {chat_id}: {name}")
    except Exception as e:
        print(f"[DB] Failed to save notion database for {chat_id}: {e}")