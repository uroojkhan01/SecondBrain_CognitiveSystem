# assistant_backend_1/features_services/notion.py

import requests
import pytz
import re
from datetime import datetime, timedelta
from assistant_backend_1.helpers import load_users


def get_active_database_schema(chat_id: str) -> dict:
    """Get schema of user's active database"""
    users = load_users()
    user = users.get(str(chat_id), {})
    notion = user.get("notion", {})
    active_id = notion.get("active_database_id")
    database_ids = notion.get("database_ids", [])
    
    for db in database_ids:
        if db["id"] == active_id:
            return db.get("schema", {})
    
    return {}


def get_column_name(schema: dict, col_type: str) -> str:
    """Find column name by type from schema"""
    for col_name, col_type_val in schema.items():
        if col_type_val == col_type:
            return col_name
    return None

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
    if not due_str:
        return None

    due_str = due_str.strip()
    due_str = parse_relative_time(due_str)

    try:
        if "T" in due_str:
            dt = datetime.fromisoformat(due_str)

            # If already has timezone offset → use directly, no conversion
            if dt.tzinfo is not None:
                print(f"✅ Already has timezone: {dt.isoformat()}")
                return dt.isoformat()

            # No timezone → fallback to Berlin
            print(f"⚠️ No timezone in string, applying Berlin fallback")
            tz = pytz.timezone("Europe/Berlin")
            dt = tz.localize(dt)
            return dt.isoformat()

        elif len(due_str) == 10 and due_str.count("-") == 2:
            # Date only → midnight Berlin
            tz = pytz.timezone("Europe/Berlin")
            dt = datetime.strptime(due_str, "%Y-%m-%d")
            dt = tz.localize(dt.replace(hour=0, minute=0, second=0))
            print(f"📅 Date-only → midnight Berlin: {dt.isoformat()}")
            return dt.isoformat()

        else:
            print(f"⚠️ Unrecognized date format: {due_str}")
            return None

    except Exception as e:
        print(f"❌ Error formatting date: {e}")
        return None

def save_task_to_notion(chat_id: str, title: str, due: str = None) -> bool:
    token, database_id = get_user_notion_credentials(chat_id)

    if not token or not database_id:
        print(f"⚠️ No Notion credentials for {chat_id}")
        return False

    # ← Get schema to find correct column names
    schema = get_active_database_schema(chat_id)
    print(f"📋 Using schema: {schema}")

    # Find correct column names from schema
    title_col = get_column_name(schema, "title") or "Task name"
    date_col = get_column_name(schema, "date") or "Due date"
    status_col = get_column_name(schema, "status") or None
    checkbox_col = get_column_name(schema, "checkbox") or None

    url = "https://api.notion.com/v1/pages"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Notion-Version": "2022-06-28"
    }

    # Build props dynamically
    props = {
        title_col: {
            "title": [{"text": {"content": str(title)}}]
        }
    }

    # Add status if column exists
    if status_col:
        props[status_col] = {"status": {"name": "Not started"}}

    # Add checkbox if exists and no status
    elif checkbox_col:
        props[checkbox_col] = {"checkbox": False}

    # Add due date
    formatted_due = format_due_date_for_notion(due, token, database_id)
    if formatted_due and date_col:
        props[date_col] = {"date": {"start": formatted_due}}

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


def find_task_in_notion(chat_id: str, title: str) -> str | None:
    """Search the active tasks database for a page matching title. Returns page_id or None."""
    token, database_id = get_user_notion_credentials(chat_id)
    if not token or not database_id:
        return None

    schema = get_active_database_schema(chat_id)
    title_col = get_column_name(schema, "title") or "Task Name"

    try:
        response = requests.post(
            f"https://api.notion.com/v1/databases/{database_id}/query",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Notion-Version": "2022-06-28",
            },
            json={
                "filter": {
                    "property": title_col,
                    "title": {"contains": title}
                }
            }
        )
        results = response.json().get("results", [])
        if results:
            return results[0]["id"]
    except Exception as e:
        print(f"❌ Error finding task in Notion: {e}")
    return None


def delete_task_from_notion(chat_id: str, title: str) -> bool:
    """Archive (soft-delete) a matching task page in Notion."""
    token, _ = get_user_notion_credentials(chat_id)
    if not token:
        return False

    page_id = find_task_in_notion(chat_id, title)
    if not page_id:
        print(f"⚠️ Task not found in Notion: {title}")
        return False

    try:
        response = requests.patch(
            f"https://api.notion.com/v1/pages/{page_id}",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Notion-Version": "2022-06-28",
            },
            json={"archived": True}
        )
        if response.status_code == 200:
            print(f"✅ Task archived in Notion: {title}")
            return True
        else:
            print(f"❌ Notion archive error: {response.text}")
            return False
    except Exception as e:
        print(f"❌ Error deleting task from Notion: {e}")
        return False


def update_task_in_notion(chat_id: str, title: str, new_title: str = None, new_due: str = None) -> bool:
    """Update title and/or due date of a matching task page in Notion."""
    token, database_id = get_user_notion_credentials(chat_id)
    if not token:
        return False

    page_id = find_task_in_notion(chat_id, title)
    if not page_id:
        print(f"⚠️ Task not found in Notion: {title}")
        return False

    schema = get_active_database_schema(chat_id)
    title_col = get_column_name(schema, "title") or "Task Name"
    date_col = get_column_name(schema, "date") or "Execution Date"

    props = {}
    if new_title:
        props[title_col] = {"title": [{"text": {"content": str(new_title)}}]}
    if new_due:
        formatted_due = format_due_date_for_notion(new_due, token, database_id)
        if formatted_due:
            props[date_col] = {"date": {"start": formatted_due}}

    if not props:
        return True

    try:
        response = requests.patch(
            f"https://api.notion.com/v1/pages/{page_id}",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Notion-Version": "2022-06-28",
            },
            json={"properties": props}
        )
        if response.status_code == 200:
            print(f"✅ Task updated in Notion: {title}")
            return True
        else:
            print(f"❌ Notion update error: {response.text}")
            return False
    except Exception as e:
        print(f"❌ Error updating task in Notion: {e}")
        return False


def save_reminder_to_notion(chat_id: str, text: str, remind_at: str = None) -> bool:
    token, database_id = get_user_notion_credentials(chat_id)

    if not token or not database_id:
        print(f"⚠️ No Notion credentials for {chat_id}")
        return False

    # ← Get schema
    schema = get_active_database_schema(chat_id)
    print(f"📋 Using schema: {schema}")

    title_col = get_column_name(schema, "title") or "Task name"
    date_col = get_column_name(schema, "date") or "Due date"
    status_col = get_column_name(schema, "status") or None
    checkbox_col = get_column_name(schema, "checkbox") or None

    url = "https://api.notion.com/v1/pages"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Notion-Version": "2022-06-28"
    }

    props = {
        title_col: {
            "title": [{"text": {"content": f"🔔 {str(text)}"}}]
        }
    }

    if status_col:
        props[status_col] = {"status": {"name": "Not started"}}
    elif checkbox_col:
        props[checkbox_col] = {"checkbox": False}

    formatted_due = format_due_date_for_notion(remind_at, token, database_id)
    if formatted_due and date_col:
        props[date_col] = {"date": {"start": formatted_due}}

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