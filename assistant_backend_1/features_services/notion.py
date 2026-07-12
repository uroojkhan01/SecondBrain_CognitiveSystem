# assistant_backend_1/features_services/notion.py

import requests
import pytz
import re
from datetime import datetime, timedelta
from assistant_backend_1.models.db import get_user_by_chat_id, get_notion_databases
from assistant_backend_1.config import NOTION_VERSION

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
        "Notion-Version": NOTION_VERSION
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
        "Notion-Version": NOTION_VERSION
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


def _search_tasks_db(token: str, tasks_db_id: str, keyword: str, include_done: bool = False) -> list:
    """Query the Tasks DB for pages whose title contains keyword."""
    conditions = [{"property": "Task Name", "title": {"contains": keyword}}]
    if not include_done:
        conditions.append({"property": "Done", "checkbox": {"equals": False}})
    filter_body = {"and": conditions} if len(conditions) > 1 else conditions[0]
    try:
        r = requests.post(
            f"https://api.notion.com/v1/databases/{tasks_db_id}/query",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Notion-Version": NOTION_VERSION,
            },
            json={"filter": filter_body},
            timeout=30,
        )
        return r.json().get("results", [])
    except Exception as e:
        print(f"❌ _search_tasks_db error: {e}")
        return []


def _find_task_fuzzy(token: str, tasks_db_id: str, title: str, include_done: bool = False) -> str | None:
    """
    Find a task page_id by title with word-based fallback matching.

    1. Try the full LLM title as a substring.
    2. If nothing found, try each significant word (≥5 chars) longest-first
       until exactly one or more results come back.
    This handles cases where the LLM reformulates the title
    (e.g. 'finding a photographer' vs 'Find and book photographer').
    """
    # 1. Exact substring attempt
    results = _search_tasks_db(token, tasks_db_id, title, include_done)
    if results:
        return results[0]["id"]

    # 2. Word-based fallback
    STOP = {"with", "your", "that", "this", "from", "have", "will", "been", "also", "some"}
    words = [
        w.strip("'s.,!?\"").lower()
        for w in title.split()
        if len(w.strip("'s.,!?\"")) >= 5 and w.lower() not in STOP
    ]
    words.sort(key=len, reverse=True)   # most distinctive first

    for word in words:
        results = _search_tasks_db(token, tasks_db_id, word, include_done)
        if results:
            print(f"[fuzzy] matched '{title}' via keyword '{word}'")
            return results[0]["id"]

    return None


def find_task_in_notion(chat_id: str, title: str, include_done: bool = False) -> str | None:
    """Search the Tasks & To Dos database for a page matching title. Returns page_id or None."""
    from assistant_backend_1.helpers import load_users
    users = load_users()
    token = users.get(str(chat_id), {}).get("notion", {}).get("token")
    tasks_db_id = users.get(str(chat_id), {}).get("second_brain", {}).get("databases", {}).get("tasks_todos")
    if not token or not tasks_db_id:
        return None
    return _find_task_fuzzy(token, tasks_db_id, title, include_done)


def mark_task_done_in_notion(chat_id: str, title: str) -> bool:
    """Set Done = True on the matching task so Master Projects rollup updates."""
    from assistant_backend_1.helpers import load_users
    users = load_users()
    token = users.get(str(chat_id), {}).get("notion", {}).get("token")
    tasks_db_id = users.get(str(chat_id), {}).get("second_brain", {}).get("databases", {}).get("tasks_todos")
    if not token or not tasks_db_id:
        return False
    page_id = _find_task_fuzzy(token, tasks_db_id, title)
    if not page_id:
        print(f"⚠️ Could not find Notion task to mark done: {title}")
        return False
    try:
        response = requests.patch(
            f"https://api.notion.com/v1/pages/{page_id}",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Notion-Version": NOTION_VERSION,
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


def mark_task_undone_in_notion(chat_id: str, title: str) -> bool:
    """Set Done = False on the matching task, reverting an accidental mark-done."""
    from assistant_backend_1.helpers import load_users
    users = load_users()
    token = users.get(str(chat_id), {}).get("notion", {}).get("token")
    tasks_db_id = users.get(str(chat_id), {}).get("second_brain", {}).get("databases", {}).get("tasks_todos")
    if not token or not tasks_db_id:
        return False
    page_id = _find_task_fuzzy(token, tasks_db_id, title, include_done=True)
    if not page_id:
        print(f"⚠️ Could not find Notion task to unmark: {title}")
        return False
    try:
        response = requests.patch(
            f"https://api.notion.com/v1/pages/{page_id}",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Notion-Version": NOTION_VERSION,
            },
            json={"properties": {"Done": {"checkbox": False}}},
            timeout=30,
        )
        if response.status_code == 200:
            print(f"✅ Task unmarked in Notion: {title}")
            update_project_progress(chat_id, page_id)
            return True
        print(f"❌ Failed to unmark task in Notion: {response.text}")
        return False
    except Exception as e:
        print(f"❌ Error unmarking task in Notion: {e}")
        return False


def _query_all_pages(headers: dict, db_id: str, filter_body: dict = None) -> list | None:
    """Query a Notion database with pagination, returning all results.
    Returns None if any API call fails (so callers can skip the update safely)."""
    results = []
    payload = filter_body or {}
    while True:
        r = requests.post(
            f"https://api.notion.com/v1/databases/{db_id}/query",
            headers=headers,
            json=payload,
            timeout=30,
        )
        if r.status_code != 200:
            print(f"❌ Notion query failed ({r.status_code}): {r.text[:200]}")
            return None
        data = r.json()
        results.extend(data.get("results", []))
        if data.get("has_more"):
            payload = {**payload, "start_cursor": data["next_cursor"]}
        else:
            break
    return results


def _set_progress_bar(headers: dict, project_page_id: str, done: int, total: int) -> None:
    progress = round(done / total * 100) if total > 0 else 0
    props = {"Progress Bar": {"number": progress}}
    if progress == 100:
        props["Status"] = {"select": {"name": "Completed"}}
    r = requests.patch(
        f"https://api.notion.com/v1/pages/{project_page_id}",
        headers=headers,
        json={"properties": props},
        timeout=30,
    )
    if r.status_code == 200:
        print(f"✅ Progress Bar: {done}/{total} = {progress}%")
    else:
        print(f"❌ Failed to set Progress Bar: {r.text[:200]}")


def update_project_progress(chat_id: str, task_page_id: str) -> None:
    """Recalculate and update Progress Bar on any Master Projects linked to this task."""
    from assistant_backend_1.helpers import load_users

    token, _ = get_user_notion_credentials(chat_id)
    if not token:
        return

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Notion-Version": NOTION_VERSION,
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
            results = _query_all_pages(
                headers, tasks_db_id,
                {"filter": {"property": "Parent Project", "relation": {"contains": project_page_id}}}
            )
            if results is None:
                # API call failed — skip to avoid overwriting with 0
                continue
            total = len(results)
            done = sum(1 for t in results if t.get("properties", {}).get("Done", {}).get("checkbox", False))
            _set_progress_bar(headers, project_page_id, done, total)
            try:
                from assistant_backend_1.features_services.notion_project_details import populate_project_page
                populate_project_page(token, chat_id, project_page_id)
            except Exception as e:
                print(f"⚠️ Could not refresh project page callout: {e}")
        except Exception as e:
            print(f"❌ Error updating progress for project {project_page_id}: {e}")


def sync_all_project_progress(chat_id: str) -> None:
    """
    Recalculate Progress Bar for every project in Master Projects DB.
    Runs on a schedule so manual Notion changes are picked up automatically.
    """
    from assistant_backend_1.helpers import load_users

    token, _ = get_user_notion_credentials(chat_id)
    if not token:
        return

    users = load_users()
    second_brain = users.get(str(chat_id), {}).get("second_brain", {})
    tasks_db_id = second_brain.get("databases", {}).get("tasks_todos")
    master_db_id = second_brain.get("databases", {}).get("master_projects")
    if not tasks_db_id or not master_db_id:
        return

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Notion-Version": NOTION_VERSION,
    }

    try:
        projects = _query_all_pages(headers, master_db_id)
    except Exception as e:
        print(f"❌ Could not fetch projects for progress sync: {e}")
        return

    for project in projects:
        project_page_id = project["id"]
        try:
            results = _query_all_pages(
                headers, tasks_db_id,
                {"filter": {"property": "Parent Project", "relation": {"contains": project_page_id}}}
            )
            if not results and results != []:
                # Failed query — skip, don't overwrite with 0
                continue
            total = len(results)
            done = sum(1 for t in results if t.get("properties", {}).get("Done", {}).get("checkbox", False))
            _set_progress_bar(headers, project_page_id, done, total)
            try:
                from assistant_backend_1.features_services.notion_project_details import populate_project_page
                populate_project_page(token, chat_id, project_page_id)
            except Exception as e:
                print(f"⚠️ Could not refresh project page callout during sync: {e}")
        except Exception as e:
            print(f"❌ Progress sync error for project {project_page_id}: {e}")


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
                "Notion-Version": NOTION_VERSION,
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
            criticality_select = props.get("Criticality", {}).get("select")
            criticality = criticality_select.get("name") if criticality_select else None
            tasks.append({"page_id": page["id"], "title": title, "due": due, "criticality": criticality})
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
                "Notion-Version": NOTION_VERSION,
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
                "Notion-Version": NOTION_VERSION,
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


def update_project_in_notion(chat_id: str, project_name: str, new_deadline: str = None, new_status: str = None) -> bool:
    """Find a project in Master Projects DB by name and update its deadline and/or status."""
    from assistant_backend_1.helpers import load_users
    users = load_users()
    user_data = users.get(str(chat_id), {})
    token = user_data.get("notion", {}).get("token")
    master_db_id = user_data.get("second_brain", {}).get("databases", {}).get("master_projects")

    if not token or not master_db_id:
        print(f"⚠️ No Master Projects DB credentials for {chat_id}")
        return False

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Notion-Version": NOTION_VERSION,
    }

    results = _query_all_pages(headers, master_db_id, {})
    if results is None:
        return False

    project_page_id = None
    for page in results:
        for prop in page.get("properties", {}).values():
            if prop.get("type") == "title":
                title_parts = prop.get("title", [])
                name = "".join(t.get("plain_text", "") for t in title_parts).strip()
                if project_name.lower() in name.lower() or name.lower() in project_name.lower():
                    project_page_id = page["id"]
                    break
        if project_page_id:
            break

    if not project_page_id:
        print(f"⚠️ Project '{project_name}' not found in Master Projects DB")
        return False

    props = {}
    if new_deadline:
        props["Target Deadline"] = {"date": {"start": new_deadline}}
    valid_statuses = {"Proposed", "Active", "Paused", "Completed"}
    if new_status and new_status in valid_statuses:
        props["Status"] = {"select": {"name": new_status}}

    if not props:
        return True

    r = requests.patch(
        f"https://api.notion.com/v1/pages/{project_page_id}",
        headers=headers,
        json={"properties": props},
        timeout=30,
    )
    if r.status_code == 200:
        print(f"✅ Project '{project_name}' updated in Notion")
        try:
            from assistant_backend_1.features_services.notion_project_details import populate_project_page
            populate_project_page(token, chat_id, project_page_id)
        except Exception as e:
            print(f"⚠️ Could not refresh project page callout after update: {e}")
        return True
    print(f"❌ Failed to update project '{project_name}': {r.json()}")
    return False


def update_task_in_notion(chat_id: str, title: str, new_title: str = None, new_due: str = None, new_criticality: str = None) -> bool:
    """Update title, due date, and/or priority of a matching task page in Notion."""
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
    valid_criticalities = {"P1 - Critical", "P2 - Important", "P3 - Minor"}
    if new_criticality in valid_criticalities:
        props["Criticality"] = {"select": {"name": new_criticality}}

    if not props:
        return True

    try:
        response = requests.patch(
            f"https://api.notion.com/v1/pages/{page_id}",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Notion-Version": NOTION_VERSION,
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
        "Notion-Version": NOTION_VERSION
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