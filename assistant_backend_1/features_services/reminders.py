# assistant_backend_1/features_services/reminders.py
"""
Reminders Service
-----------------
This module handles the core functionality for managing and dispatching reminders.
It is divided into two main parts:
1. A background scheduler (`check_and_remind`) that periodically polls Notion for due tasks and sends alerts via Telegram.
2. CRUD operations to programmatically Create, Read, Update, and Delete Notion-based reminders.
"""

import requests
import json
import os
from datetime import datetime
import pytz
# pyrefly: ignore [missing-import]
import schedule
import time

# ============================================
# CONFIGURATION
# ============================================
USERS_FILE = "user.json"
CHECK_INTERVAL_MINUTES = 5
REMINDER_BEFORE_MINUTES = 15

# In-memory tracker to avoid duplicate reminders
# Format: {"chat_id_taskname_datetime": True}
sent_reminders = {}


# ============================================
# HELPERS
# ============================================

def load_users():
    if os.path.exists(USERS_FILE):
        with open(USERS_FILE, "r") as f:
            content = f.read().strip()
            if not content:
                return {}
            return json.loads(content)
    return {}


def send_telegram(chat_id: str, message: str):
    from assistant_backend_1.config import TELEGRAM_BOT_TOKEN
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "Markdown"
    }
    try:
        response = requests.post(url, json=payload)
        response.raise_for_status()
        print(f"✅ Reminder sent to {chat_id}")
    except Exception as e:
        print(f"❌ Error sending to {chat_id}: {e}")


def get_notion_tasks(token: str, database_id: str):
    url = f"https://api.notion.com/v1/databases/{database_id}/query"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Notion-Version": "2022-06-28"
    }
    try:
        response = requests.post(url, headers=headers, json={})  # ← no filter

        if response.status_code == 429:
            retry_after = int(response.headers.get("Retry-After", 60))
            print(f"⚠️ Rate limited! Waiting {retry_after} seconds...")
            time.sleep(retry_after)
            return get_notion_tasks(token, database_id)

        response.raise_for_status()
        return response.json().get("results", [])

    except Exception as e:
        print(f"❌ Error fetching tasks: {e}")
        return []


def extract_tasks(results, schema: dict = {}):
    """Extract tasks using dynamic column names from schema"""
    tasks = []

    # Find column names from schema
    title_col = next((k for k, v in schema.items() if v == "title"), None)
    date_col = next((k for k, v in schema.items() if v == "date"), None)

    # Fallback column names if schema not available
    title_candidates = [title_col] if title_col else ["Task name", "Name", "Title", "Task"]
    date_candidates = [date_col] if date_col else ["Due date", "Due", "Date", "Deadline"]

    for page in results:
        page_id = page["id"]
        props = page["properties"]

        # Get task name
        name = None
        for col in title_candidates:
            try:
                name = props[col]["title"][0]["text"]["content"]
                break
            except:
                continue
        if not name:
            name = "Unnamed Task"

        # Get due date
        due_str = None
        for col in date_candidates:
            try:
                due_str = props[col]["date"]["start"]
                break
            except:
                continue

        if not due_str:
            continue

        if "T" in due_str:
            due_datetime = datetime.fromisoformat(due_str)
            if due_datetime.tzinfo is None:
                due_datetime = due_datetime.astimezone()
            has_time = True
        else:
            due_datetime = datetime.strptime(due_str, "%Y-%m-%d").date()
            has_time = False

        tasks.append({
            "id": page_id,
            "name": name,
            "due_datetime": due_datetime,
            "has_time": has_time
        })

    return tasks


def check_and_remind():
    """
    Core background job that scans every registered user's Notion database for upcoming tasks.
    It checks if tasks are due soon (e.g., within 15 minutes) or due today without a specific time.
    If a task meets the criteria, it dispatches a Telegram notification and marks the task as reminded
    in the in-memory `sent_reminders` dictionary to prevent duplicate alerts.
    """
    print(f"\n🔍 Checking all users at {datetime.now().strftime('%Y-%m-%d %H:%M')}")

    users = load_users()

    if not users:
        print("No users found")
        return

    for chat_id, user_data in users.items():
        notion = user_data.get("notion", {})
        token = notion.get("token")
        database_id = notion.get("active_database_id")

        if not token or not database_id:
            print(f"⚠️ Skipping {chat_id} — no token or database")
            continue

        # Get schema for this user's active database
        active_schema = {}
        for db in notion.get("database_ids", []):
            if db["id"] == database_id:
                active_schema = db.get("schema", {})
                break

        print(f"👤 Checking tasks for: {chat_id} | Schema: {active_schema}")

        results = get_notion_tasks(token, database_id)
        tasks = extract_tasks(results, active_schema)

        now = datetime.now(pytz.utc)

        for task in tasks:
            due = task["due_datetime"]
            name = task["name"]

            if task["has_time"]:
                # Convert to UTC for comparison
                if hasattr(due, 'tzinfo') and due.tzinfo is not None:
                    due_utc = due.astimezone(pytz.utc)
                else:
                    due_utc = pytz.utc.localize(due)

                minutes_until_due = (due_utc - now).total_seconds() / 60

                lower = REMINDER_BEFORE_MINUTES - CHECK_INTERVAL_MINUTES
                upper = REMINDER_BEFORE_MINUTES + CHECK_INTERVAL_MINUTES

                # 15 min warning
                if lower <= minutes_until_due <= upper:
                    reminder_key = get_reminder_key(chat_id, name, due)
                    if reminder_key not in sent_reminders:
                        local_time = due.strftime('%I:%M %p')
                        tz_name = due.strftime('%Z')
                        message = (
                            f"⏰ *Upcoming Task!*\n\n"
                            f"📌 *{name}*\n"
                            f"🕒 Due at: *{local_time} {tz_name}*\n"
                            f"⚡ Starting in *~{int(minutes_until_due)} minutes!*"
                        )
                        send_telegram(chat_id, message)
                        sent_reminders[reminder_key] = True
                        print(f"✅ Time reminder sent: {name}")
                    else:
                        print(f"⏭ Already reminded: {name}")

                # Due now
                elif -CHECK_INTERVAL_MINUTES <= minutes_until_due <= 0:
                    reminder_key = get_reminder_key(chat_id, name, due) + "_now"
                    if reminder_key not in sent_reminders:
                        message = (
                            f"🔔 *It's Time!*\n\n"
                            f"📌 *{name}*\n"
                            f"🕒 Due NOW: *{due.strftime('%I:%M %p')}*"
                        )
                        send_telegram(chat_id, message)
                        sent_reminders[reminder_key] = True
                        print(f"✅ Due now reminder sent: {name}")

                # Catch tasks due very soon (startup edge case)
                elif 0 < minutes_until_due < lower:
                    reminder_key = get_reminder_key(chat_id, name, due)
                    if reminder_key not in sent_reminders:
                        message = (
                            f"⚡ *Due Very Soon!*\n\n"
                            f"📌 *{name}*\n"
                            f"🕒 Due in *{int(minutes_until_due)} minutes!*"
                        )
                        send_telegram(chat_id, message)
                        sent_reminders[reminder_key] = True

            else:
                # Date only → remind at midnight
                now_local = datetime.now()
                is_midnight = now_local.hour == 0 and now_local.minute < CHECK_INTERVAL_MINUTES
                is_due_today = due == now_local.date()

                if is_due_today and is_midnight:
                    reminder_key = get_reminder_key(chat_id, name, due)
                    if reminder_key not in sent_reminders:
                        message = (
                            f"📅 *Due Today!*\n\n"
                            f"📌 *{name}*\n"
                            f"🗓 *{due.strftime('%B %d, %Y')}*"
                        )
                        send_telegram(chat_id, message)
                        sent_reminders[reminder_key] = True
                        print(f"✅ Date reminder sent: {name}")

    print(f"✅ Check complete")


def get_reminder_key(chat_id: str, task_name: str, due) -> str:
    """Unique key per user+task+due to prevent duplicate reminders"""
    if isinstance(due, datetime):
        due_str = due.strftime('%Y-%m-%d-%H-%M')
    else:
        due_str = str(due)
    return f"{chat_id}_{task_name}_{due_str}"



# ============================================
# CRUD OPERATIONS FOR REMINDERS
# ============================================
# These functions provide an interface to interact with reminders directly.
# Since reminders are backed by Notion, these functions communicate with the Notion API
# to synchronize the data state.

def create_reminder(chat_id: str, text: str, remind_at: str = None) -> bool:
    """Create a new reminder in Notion"""
    from assistant_backend_1.features_services.notion import save_reminder_to_notion
    return save_reminder_to_notion(chat_id, text, remind_at)


def get_all_reminders(chat_id: str) -> list:
    """Read all reminders from Notion for this user"""
    from assistant_backend_1.features_services.notion import get_user_notion_credentials, get_active_database_schema
    token, database_id = get_user_notion_credentials(chat_id)
    if not token or not database_id:
        print(f"⚠️ No Notion credentials for {chat_id}")
        return []

    # Get schema for this user's active database
    schema = get_active_database_schema(chat_id)
    results = get_notion_tasks(token, database_id)
    return extract_tasks(results, schema)


def update_reminder(chat_id: str, page_id: str, text: str = None, remind_at: str = None) -> bool:
    """
    Update an existing reminder in Notion.
    Dynamically identifies the correct title and date columns based on the user's active database schema,
    formats the new data appropriately, and sends a PATCH request to update the Notion page properties.
    """
    from assistant_backend_1.features_services.notion import get_user_notion_credentials, get_active_database_schema, get_column_name, format_due_date_for_notion
    token, database_id = get_user_notion_credentials(chat_id)
    if not token or not database_id:
        return False
        
    schema = get_active_database_schema(chat_id)
    title_col = get_column_name(schema, "title") or "Task name"
    date_col = get_column_name(schema, "date") or "Due date"
    
    url = f"https://api.notion.com/v1/pages/{page_id}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Notion-Version": "2022-06-28"
    }
    
    props = {}
    if text is not None:
        props[title_col] = {"title": [{"text": {"content": str(text)}}]}
    if remind_at is not None:
        formatted_due = format_due_date_for_notion(remind_at, token, database_id)
        if formatted_due:
            props[date_col] = {"date": {"start": formatted_due}}
            
    if not props:
        return True
        
    try:
        response = requests.patch(url, headers=headers, json={"properties": props})
        return response.status_code == 200
    except Exception as e:
        print(f"❌ Error updating reminder: {e}")
        return False


def delete_reminder(chat_id: str, page_id: str) -> bool:
    """
    Delete a reminder in Notion.
    Note: The Notion API does not support hard-deleting pages directly via standard endpoints.
    Instead, this function "archives" the page by setting its 'archived' property to True.
    """
    from assistant_backend_1.features_services.notion import get_user_notion_credentials
    token, _ = get_user_notion_credentials(chat_id)
    if not token:
        return False
        
    url = f"https://api.notion.com/v1/pages/{page_id}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Notion-Version": "2022-06-28"
    }
    
    try:
        response = requests.patch(url, headers=headers, json={"archived": True})
        return response.status_code == 200
    except Exception as e:
        print(f"❌ Error deleting reminder: {e}")
        return False


# ============================================
# SCHEDULER
# ============================================

def start_reminder_scheduler():
    """Call this from main.py to start scheduler in background"""
    print(f"🚀 Reminder scheduler starting...")
    print(f"⏱ Checking every {CHECK_INTERVAL_MINUTES} minutes")

    check_and_remind()  # run once immediately

    schedule.every(CHECK_INTERVAL_MINUTES).minutes.do(check_and_remind)

    while True:
        schedule.run_pending()
        time.sleep(30)