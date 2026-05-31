# assistant_backend_1/features_services/notion.py

import requests
import pytz
import re
from datetime import datetime, timedelta
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
        print(f"🔍 Full Notion DB response: {data}")
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


def parse_relative_time(due_str: str) -> str:
    """
    Convert relative time strings to absolute datetime.
    If not relative, return as is.
    """
    now = datetime.now()
    due_str_lower = due_str.lower().strip()

    # "in X minutes"
    match = re.match(r"in (\d+) minutes?", due_str_lower)
    if match:
        mins = int(match.group(1))
        result = (now + timedelta(minutes=mins)).strftime("%Y-%m-%dT%H:%M:%S")
        print(f"⏱ Relative time '{due_str}' → {result}")
        return result

    # "in X hours"
    match = re.match(r"in (\d+) hours?", due_str_lower)
    if match:
        hours = int(match.group(1))
        result = (now + timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%S")
        print(f"⏱ Relative time '{due_str}' → {result}")
        return result

    # "in X days"
    match = re.match(r"in (\d+) days?", due_str_lower)
    if match:
        days = int(match.group(1))
        result = (now + timedelta(days=days)).strftime("%Y-%m-%d")
        print(f"⏱ Relative time '{due_str}' → {result}")
        return result

    # "tomorrow"
    if "tomorrow" in due_str_lower:
        result = (now + timedelta(days=1)).strftime("%Y-%m-%d")
        print(f"⏱ Relative time '{due_str}' → {result}")
        return result

    # "tonight"
    if "tonight" in due_str_lower:
        result = now.strftime("%Y-%m-%d") + "T21:00:00"
        print(f"⏱ Relative time '{due_str}' → {result}")
        return result

    # "next week"
    if "next week" in due_str_lower:
        result = (now + timedelta(weeks=1)).strftime("%Y-%m-%d")
        print(f"⏱ Relative time '{due_str}' → {result}")
        return result

    return due_str  # not relative — return as is


def format_due_date_for_notion(due_str: str, token: str = None, database_id: str = None) -> str:
    """
    Convert LLM due string to Notion-compatible format.
    - Handles relative times like 'in 15 minutes'
    - If datetime has no timezone → fetch from Notion and apply
    - If datetime has timezone → use as is
    - If date only → apply midnight in user's timezone
    - If None → return None
    """
    if not due_str:
        return None

    due_str = due_str.strip()
    print(f"🔍 Input due_str: {due_str}")
    # Try to parse relative time first
    due_str = parse_relative_time(due_str)
    print(f"🔍 After parse_relative_time: {due_str}")

    try:
        if "T" in due_str:
            dt = datetime.fromisoformat(due_str)

            # No timezone → fetch from Notion and apply
            if dt.tzinfo is None and token and database_id:
                tz_name = get_notion_workspace_timezone(token, database_id)
                tz = pytz.timezone(tz_name)
                dt = tz.localize(dt)
                print(f"🕒 Applied timezone {tz_name} → {dt.isoformat()}")
                print(f"🔍 Final formatted: {dt.isoformat()}")
                return dt.isoformat()

            # Already has timezone → use as is
            return due_str

        elif len(due_str) == 10 and due_str.count("-") == 2:
            # Date only → apply midnight in user's timezone
            if token and database_id:
                tz_name = get_notion_workspace_timezone(token, database_id)
                tz = pytz.timezone(tz_name)
                dt = datetime.strptime(due_str, "%Y-%m-%d")
                dt = tz.localize(dt.replace(hour=0, minute=0, second=0))
                print(f"📅 Date-only → midnight in {tz_name}: {dt.isoformat()}")
                return dt.isoformat()

            return due_str  # fallback if no credentials

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