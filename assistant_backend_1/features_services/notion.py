# assistant_backend_1/features_services/notion.py

import requests
import pytz
from datetime import datetime
from assistant_backend_1.helpers import load_users


def get_user_notion_credentials(chat_id: str):
    """Get token and active database id for a user"""
    users = load_users()
    user = users.get(str(chat_id), {})
    notion = user.get("notion", {})
    token = notion.get("token")
    database_id = notion.get("active_database_id")
    return token, database_id


def get_notion_workspace_timezone(token: str, database_id: str) -> str:
    """
    Fetch timezone from Notion database settings.
    Falls back to UTC if not found.
    """
    url = f"https://api.notion.com/v1/databases/{database_id}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Notion-Version": "2022-06-28"
    }
    try:
        response = requests.get(url, headers=headers)
        data = response.json()
        tz = (
            data.get("properties", {})
                .get("Due date", {})
                .get("date", {})
                .get("time_zone")
        )
        if tz:
            print(f"🌍 Notion timezone: {tz}")
            return tz
    except Exception as e:
        print(f"⚠️ Could not fetch timezone: {e}")

    return "UTC"


def format_due_date_for_notion(due_str: str, token: str = None, database_id: str = None) -> str:
    """
    Convert LLM due string to Notion-compatible format.
    - If datetime has no timezone → fetch from Notion and apply
    - If datetime has timezone → use as is
    - If date only → use as is
    - If None → return None
    """
    if not due_str:
        return None

    due_str = due_str.strip()

    try:
        if "T" in due_str:
            dt = datetime.fromisoformat(due_str)

            # No timezone info → fetch from Notion and apply
            if dt.tzinfo is None and token and database_id:
                tz_name = get_notion_workspace_timezone(token, database_id)
                tz = pytz.timezone(tz_name)
                dt = tz.localize(dt)
                print(f"🕒 Applied timezone {tz_name} → {dt.isoformat()}")
                return dt.isoformat()

            # Already has timezone → use as is
            return due_str

        elif len(due_str) == 10 and due_str.count("-") == 2:
            # Date only — no timezone needed
            return due_str

        else:
            print(f"⚠️ Unrecognized date format: {due_str}")
            return None

    except Exception as e:
        print(f"❌ Error formatting date: {e}")
        return None


def save_task_to_notion(chat_id: str, title: str, due: str = None) -> bool:
    """Save a task to user's Notion database"""
    token, database_id = get_user_notion_credentials(chat_id)

    if not token or not database_id:
        print(f"⚠️ No Notion credentials for {chat_id}")
        return False

    url = "https://api.notion.com/v1/pages"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Notion-Version": "2022-06-28"
    }

    props = {
        "Task name": {
            "title": [{"text": {"content": str(title)}}]
        },
        "Status": {
            "status": {"name": "Not started"}
        }
    }

    # Format due date with correct timezone
    formatted_due = format_due_date_for_notion(due, token, database_id)
    if formatted_due:
        props["Due date"] = {
            "date": {"start": formatted_due}
        }

    try:
        response = requests.post(
            url,
            headers=headers,
            json={
                "parent": {"database_id": database_id},
                "properties": props
            }
        )

        if response.status_code == 200:
            print(f"✅ Task saved to Notion: {title}")
            return True
        else:
            print(f"❌ Notion error: {response.text}")
            return False

    except Exception as e:
        print(f"❌ Error saving to Notion: {e}")
        return False


def save_reminder_to_notion(chat_id: str, text: str, remind_at: str = None) -> bool:
    """Save a reminder to user's Notion database as a task"""
    token, database_id = get_user_notion_credentials(chat_id)

    if not token or not database_id:
        print(f"⚠️ No Notion credentials for {chat_id}")
        return False

    url = "https://api.notion.com/v1/pages"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Notion-Version": "2022-06-28"
    }

    props = {
        "Task name": {
            "title": [{"text": {"content": f"🔔 {str(text)}"}}]
        },
        "Status": {
            "status": {"name": "Not started"}
        }
    }

    # Format remind_at with correct timezone
    formatted_due = format_due_date_for_notion(remind_at, token, database_id)
    if formatted_due:
        props["Due date"] = {
            "date": {"start": formatted_due}
        }

    try:
        response = requests.post(
            url,
            headers=headers,
            json={
                "parent": {"database_id": database_id},
                "properties": props
            }
        )

        if response.status_code == 200:
            print(f"✅ Reminder saved to Notion: {text}")
            return True
        else:
            print(f"❌ Notion error: {response.text}")
            return False

    except Exception as e:
        print(f"❌ Error saving reminder to Notion: {e}")
        return False