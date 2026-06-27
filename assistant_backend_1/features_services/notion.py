# assistant_backend_1/features_services/notion.py

import requests
import pytz
import re
from datetime import datetime, timedelta
from assistant_backend_1.models.db import get_user_by_chat_id, get_notion_databases

def get_user_notion_credentials(chat_id: str):
    # Token — always read from Postgres (updated on every OAuth)
    user = get_user_by_chat_id(chat_id)
    if not user:
        return None, None
    token = user.get("notion_access_token")

    # Active database — read from user.json where setup_second_brain sets it
    # to the Tasks & To Dos DB.  Fall back to Postgres first-row only if missing.
    from assistant_backend_1.helpers import load_users
    users = load_users()
    notion = users.get(str(chat_id), {}).get("notion", {})
    database_id = notion.get("active_database_id")
    if not database_id:
        dbs = get_notion_databases(user["id"])
        database_id = dbs[0]["notion_db_id"] if dbs else None

    return token, database_id


def get_active_database_schema(chat_id: str) -> dict:
    # """Get schema of user's active database"""
    # users = load_users()
    # user = users.get(str(chat_id), {})
    # notion = user.get("notion", {})
    # active_id = notion.get("active_database_id")
    # database_ids = notion.get("database_ids", [])
    
    # for db in database_ids:
    #     if db["id"] == active_id:
    #         return db.get("schema", {})
    
    return {}


def get_column_name(schema: dict, col_type: str) -> str:
    """Find column name by type from schema"""
    for col_name, col_type_val in schema.items():
        if col_type_val == col_type:
            return col_name
    return None

# def get_user_notion_credentials(chat_id: str):
#     """Get token and active database id for a user"""
#     users = load_users()
#     user = users.get(str(chat_id), {})
#     notion = user.get("notion", {})
#     token = notion.get("token")
#     database_id = notion.get("active_database_id")
#     return token, database_id


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

def save_task_to_notion(chat_id: str, title: str, due: str = None, criticality: str = None) -> bool:
    token, database_id = get_user_notion_credentials(chat_id)

    if not token or not database_id:
        print(f"⚠️ No Notion credentials for {chat_id}")
        return False

    schema = get_active_database_schema(chat_id)
    print(f"📋 Using schema: {schema}")

    title_col = get_column_name(schema, "title") or "Task Name"
    date_col = get_column_name(schema, "date") or "Execution Date"
    criticality_col = get_column_name(schema, "select") or "Criticality"

    url = "https://api.notion.com/v1/pages"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Notion-Version": "2022-06-28"
    }

    props = {
        title_col: {
            "title": [{"text": {"content": str(title)}}]
        }
    }

    formatted_due = format_due_date_for_notion(due, token, database_id)
    if formatted_due and date_col:
        props[date_col] = {"date": {"start": formatted_due}}

    valid_criticalities = {"P1 - Critical", "P2 - Important", "P3 - Minor"}
    if criticality in valid_criticalities and criticality_col:
        props[criticality_col] = {"select": {"name": criticality}}

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
            print(f"✅ Task saved to Notion: {title} [{criticality}]")
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


def mark_task_done_in_notion(chat_id: str, title: str) -> bool:
    """Set Done = True on the matching task so Master Projects rollup updates."""
    token, _ = get_user_notion_credentials(chat_id)
    if not token:
        return False
    page_id = find_task_in_notion(chat_id, title)
    if not page_id:
        print(f"⚠️ Could not find Notion task to mark done: {title}")
        return False
    try:
        response = requests.patch(
            f"https://api.notion.com/v1/pages/{page_id}",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Notion-Version": "2022-06-28",
            },
            json={"properties": {"Done": {"checkbox": True}}},
            timeout=30,
        )
        if response.status_code == 200:
            print(f"✅ Task marked done in Notion: {title}")
            update_project_progress(chat_id, page_id)
            return True
        print(f"❌ Failed to mark task done in Notion: {response.text}")
        return False
    except Exception as e:
        print(f"❌ Error marking task done in Notion: {e}")
        return False


def update_project_progress(chat_id: str, task_page_id: str) -> None:
    """Recalculate and update Progress Bar on any Master Projects linked to this task."""
    from assistant_backend_1.helpers import load_users

    token, _ = get_user_notion_credentials(chat_id)
    if not token:
        return

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Notion-Version": "2022-06-28",
    }

    try:
        r = requests.get(f"https://api.notion.com/v1/pages/{task_page_id}", headers=headers, timeout=30)
        if r.status_code != 200:
            return
        parent_refs = r.json().get("properties", {}).get("Parent Project", {}).get("relation", [])
    except Exception as e:
        print(f"❌ Error fetching task page for progress update: {e}")
        return

    if not parent_refs:
        return

    users = load_users()
    tasks_db_id = users.get(str(chat_id), {}).get("second_brain", {}).get("databases", {}).get("tasks_todos")
    if not tasks_db_id:
        return

    for ref in parent_refs:
        project_page_id = ref["id"]
        try:
            r = requests.post(
                f"https://api.notion.com/v1/databases/{tasks_db_id}/query",
                headers=headers,
                json={"filter": {"property": "Parent Project", "relation": {"contains": project_page_id}}},
                timeout=30,
            )
            results = r.json().get("results", [])
            total = len(results)
            done = sum(1 for t in results if t.get("properties", {}).get("Done", {}).get("checkbox", False))
            progress = round(done / total * 100) if total > 0 else 0

            requests.patch(
                f"https://api.notion.com/v1/pages/{project_page_id}",
                headers=headers,
                json={"properties": {"Progress Bar": {"number": progress}}},
                timeout=30,
            )
            print(f"✅ Progress Bar: {done}/{total} = {progress}% for project {project_page_id}")
        except Exception as e:
            print(f"❌ Error updating progress for project {project_page_id}: {e}")


def get_tasks_from_notion(chat_id: str) -> list:
    """Fetch all non-done tasks from the Notion Tasks & To Dos database."""
    from assistant_backend_1.helpers import load_users
    users = load_users()
    user_data = users.get(str(chat_id), {})
    token = user_data.get("notion", {}).get("token")
    tasks_db_id = user_data.get("second_brain", {}).get("databases", {}).get("tasks_todos")

    if not token or not tasks_db_id:
        print(f"⚠️ No Notion tasks DB credentials for {chat_id}")
        return []

    try:
        response = requests.post(
            f"https://api.notion.com/v1/databases/{tasks_db_id}/query",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Notion-Version": "2022-06-28",
            },
            json={
                "filter": {
                    "property": "Done",
                    "checkbox": {"equals": False}
                },
                "sorts": [{"property": "Execution Date", "direction": "ascending"}]
            },
            timeout=30,
        )
        results = response.json().get("results", [])
        tasks = []
        for page in results:
            props = page.get("properties", {})
            title_parts = props.get("Task Name", {}).get("title", [])
            title = "".join(t.get("plain_text", "") for t in title_parts).strip()
            if not title:
                continue
            due = None
            date_prop = props.get("Execution Date", {}).get("date")
            if date_prop:
                due = date_prop.get("start")
            tasks.append({"page_id": page["id"], "title": title, "due": due})
        return tasks
    except Exception as e:
        print(f"❌ Error fetching tasks from Notion: {e}")
        return []


def mark_task_done_by_page_id(token: str, page_id: str) -> bool:
    """Set Done = True on a Notion task using its page ID directly."""
    try:
        response = requests.patch(
            f"https://api.notion.com/v1/pages/{page_id}",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Notion-Version": "2022-06-28",
            },
            json={"properties": {"Done": {"checkbox": True}}},
            timeout=30,
        )
        return response.status_code == 200
    except Exception as e:
        print(f"❌ Error marking task done by page_id: {e}")
        return False


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