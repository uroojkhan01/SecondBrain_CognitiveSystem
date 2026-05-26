import json
import os
from assistant_backend_1.config import NOTION_CLIENT_ID, NOTION_CLIENT_SECRET, NOTION_REDIRECT_URI



USERS_FILE="user.json"


def load_users():
    if os.path.exists(USERS_FILE):
        with open(USERS_FILE, "r") as f:
            content = f.read().strip()
            if not content:
                return {}
            return json.loads(content)
    return {}


def save_users(users):
    with open(USERS_FILE, "w") as f:
        json.dump(users, f, indent=2)


def save_user(chat_id: str, first_name: str = None, username: str = None):
    """Save new user if not exists, skip if already saved"""
    users = load_users()

    if str(chat_id) not in users:
        users[str(chat_id)] = {
            "user": {
                "chat_id": chat_id,
                "first_name": first_name,
                "username": username,
                "joined_at": str(__import__("datetime").datetime.now())
            },
            "notion": {
                "token": None,
                "database_id": None
            }
        }
        save_users(users)
        print(f"✅ New user saved: {chat_id}")
    else:
        print(f"👤 Existing user: {chat_id}")


def get_oauth_url(chat_id: str) -> str:
    return (
        f"https://api.notion.com/v1/oauth/authorize"
        f"?client_id={NOTION_CLIENT_ID}"
        f"&response_type=code"
        f"&owner=user"
        f"&redirect_uri={NOTION_REDIRECT_URI}"
        f"&state=tg_{str(chat_id)}"  # ← added tg_ prefix
    )


def is_notion_connected(chat_id: str) -> bool:
    users = load_users()
    user = users.get(str(chat_id), {})
    notion = user.get("notion", {})
    return bool(notion.get("token"))  # ← only check token, not database_id


def has_notion_token(chat_id: str) -> bool:
    """Check if user has token but maybe no database selected"""
    users = load_users()
    user = users.get(str(chat_id), {})
    return bool(user.get("notion", {}).get("token"))

