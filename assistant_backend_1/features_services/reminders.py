# assistant_backend_1/features_services/reminders.py

import requests
import json
import os
from datetime import datetime
import pytz
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
    """Fetch all tasks from Notion database"""
    url = f"https://api.notion.com/v1/databases/{database_id}/query"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Notion-Version": "2022-06-28"
    }

    # Only fetch tasks that are not done
    payload = {
        "filter": {
            "property": "Status",
            "status": {
                "does_not_equal": "Done"
            }
        }
    }

    try:
        response = requests.post(url, headers=headers, json=payload)

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


def extract_tasks(results):
    """Extract tasks with due date/time from Notion results"""
    tasks = []

    for page in results:
        props = page["properties"]

        # Get task name
        try:
            name = props["Task name"]["title"][0]["text"]["content"]
        except:
            name = "Unnamed Task"

        # Get due date
        try:
            due_str = props["Due date"]["date"]["start"]
        except:
            continue  # skip tasks with no due date

        # Check if it has time component
        if "T" in due_str:
            # Has time e.g. "2026-05-26T15:00:00+02:00"
            due_datetime = datetime.fromisoformat(due_str)

            # Use timezone from Notion's date string directly
            if due_datetime.tzinfo is None:
                # No timezone in string — assume UTC
                due_datetime = pytz.utc.localize(due_datetime)

            tasks.append({
                "name": name,
                "due_datetime": due_datetime,
                "has_time": True
            })

        else:
            # Date only e.g. "2026-05-26"
            due_date = datetime.strptime(due_str, "%Y-%m-%d").date()

            tasks.append({
                "name": name,
                "due_datetime": due_date,
                "has_time": False
            })

    return tasks


def get_reminder_key(chat_id: str, task_name: str, due) -> str:
    """Unique key per user+task+due to prevent duplicate reminders"""
    if isinstance(due, datetime):
        due_str = due.strftime('%Y-%m-%d-%H-%M')
    else:
        due_str = str(due)
    return f"{chat_id}_{task_name}_{due_str}"


# ============================================
# MAIN CHECK FUNCTION
# ============================================

def check_and_remind():
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

        print(f"👤 Checking tasks for: {chat_id}")

        results = get_notion_tasks(token, database_id)
        tasks = extract_tasks(results)

        # Use UTC now for comparison — Notion dates have their own tz offset
        now = datetime.now(pytz.utc)

        for task in tasks:
            due = task["due_datetime"]
            name = task["name"]

            if task["has_time"]:
                # Convert both to UTC for accurate comparison
                due_utc = due.astimezone(pytz.utc)
                minutes_until_due = (due_utc - now).total_seconds() / 60

                lower = REMINDER_BEFORE_MINUTES - CHECK_INTERVAL_MINUTES
                upper = REMINDER_BEFORE_MINUTES + CHECK_INTERVAL_MINUTES

                if lower <= minutes_until_due <= upper:
                    reminder_key = get_reminder_key(chat_id, name, due)

                    if reminder_key not in sent_reminders:
                        # Show time in Notion's original timezone
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

            else:
                # Date only — remind at midnight (00:00)
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
                    else:
                        print(f"⏭ Already reminded: {name}")

    print(f"✅ Check complete")


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