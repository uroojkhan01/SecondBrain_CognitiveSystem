# assistant_backend_1/features_services/reminders.py
"""
Reminders Service
-----------------
This module handles the core functionality for managing and dispatching reminders.
It is backed by the local Neo4j graph database, making reminders completely independent of Notion.
1. A background scheduler (`check_and_remind`) that periodically polls Neo4j for due reminders and sends alerts via Telegram.
2. CRUD operations to programmatically Create, Read, Update, and Delete local reminders in Neo4j.
"""

import os
import json
import time
import pytz
from datetime import datetime
import requests
import schedule

# ============================================
# CONFIGURATION
# ============================================
USERS_FILE = "user.json"
CHECK_INTERVAL_MINUTES = 5
TASK_MOVING_INTERVAL_MINUTES = 5

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




def check_and_remind():
    """
    Core background job that scans Neo4j for unsent due reminders.
    If a reminder's time is reached, it dispatches a Telegram notification
    and marks the reminder as sent in Neo4j.
    """
    print(f"\n🔍 Checking local reminders at {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    
    from assistant_backend_1.features_services.memory_journal import get_due_reminders, mark_reminder_sent
    
    try:
        reminders = get_due_reminders()
    except Exception as e:
        print(f"❌ Error fetching local reminders from Neo4j: {e}")
        return
        
    if not reminders:
        print("No pending local reminders.")
        return
        
    now = datetime.now(pytz.utc)
    
    for r in reminders:
        chat_id = r.get("chat_id")
        node_id = r.get("node_id")
        text = r.get("text")
        remind_at_str = r.get("remind_at")
        
        if not remind_at_str:
            continue
            
        try:
            # Parse remind_at ISO-8601 string
            remind_at = datetime.fromisoformat(remind_at_str)
            if remind_at.tzinfo is None:
                # Default fallback to Europe/Berlin
                tz = pytz.timezone("Europe/Berlin")
                remind_at = tz.localize(remind_at)
                
            remind_at_utc = remind_at.astimezone(pytz.utc)
            
            if now >= remind_at_utc:
                message = (
                    f"⏰ *Reminder!*\n\n"
                    f"📌 {text}"
                )
                send_telegram(chat_id, message)
                mark_reminder_sent(node_id)
                print(f"✅ Local reminder sent: {text} (ID: {node_id})")
        except Exception as e:
            print(f"❌ Error processing local reminder {node_id}: {e}")
            
    print("✅ Check complete")


# ============================================
# CRUD OPERATIONS FOR REMINDERS
# ============================================

def create_reminder(chat_id: str, text: str, remind_at: str = None) -> bool:
    """Create a new reminder in local Neo4j database"""
    from assistant_backend_1.features_services.memory_journal import save_reminder
    try:
        save_reminder(chat_id, text, remind_at)
        return True
    except Exception as e:
        print(f"❌ Error creating local reminder: {e}")
        return False


def get_all_reminders(chat_id: str) -> list:
    """Read all reminders from local Neo4j database for this user"""
    from assistant_backend_1.features_services.memory_journal import get_local_reminders
    try:
        return get_local_reminders(chat_id)
    except Exception as e:
        print(f"❌ Error fetching local reminders: {e}")
        return []


def update_reminder(chat_id: str, page_id: str, text: str = None, remind_at: str = None) -> bool:
    """Update an existing reminder in local Neo4j database"""
    from assistant_backend_1.features_services.memory_journal import update_local_reminder
    try:
        return update_local_reminder(chat_id, page_id, text, remind_at)
    except Exception as e:
        print(f"❌ Error updating local reminder: {e}")
        return False


def delete_reminder(chat_id: str, page_id: str) -> bool:
    """Delete a reminder in local Neo4j database"""
    from assistant_backend_1.features_services.memory_journal import delete_local_reminder
    try:
        return delete_local_reminder(chat_id, page_id)
    except Exception as e:
        print(f"❌ Error deleting local reminder: {e}")
        return False


# ============================================
# OVERDUE TASK AUTO-COMPLETION
# ============================================

def mark_overdue_tasks_done():
    """
    Auto-marks tasks as done if their Execution Date has passed.
    Runs alongside the reminder check on every scheduler tick.
    """
    from assistant_backend_1.features_services.memory_journal import get_all_tasks, mark_task_done, mark_reminder_done
    from assistant_backend_1.models.db_hooks import hook_mark_task_done
    from assistant_backend_1.features_services.notion import mark_task_done_in_notion

    users = load_users()
    now = datetime.now(pytz.utc)

    for chat_id in users:
        try:
            tasks = get_all_tasks(chat_id)
            for task in tasks:
                due_str = task.get("due")
                if not due_str:
                    continue
                try:
                    due = datetime.fromisoformat(due_str)
                    if due.tzinfo is None:
                        due = pytz.timezone("Europe/Berlin").localize(due)
                    if now >= due.astimezone(pytz.utc):
                        title = task.get("title")
                        mark_task_done(chat_id, title)
                        mark_reminder_done(chat_id, title)
                        hook_mark_task_done(chat_id, title)
                        mark_task_done_in_notion(chat_id, title)
                        print(f"✅ Auto-marked overdue task done: '{title}' for {chat_id}")
                except Exception as e:
                    print(f"❌ Error parsing due date for task '{task.get('title')}': {e}")
        except Exception as e:
            print(f"❌ Error auto-marking tasks for {chat_id}: {e}")


# ============================================
# TASK MOVING AGENT JOB
# ============================================

def run_task_moving_for_all_users():
    """
    Runs the AI task-moving agent for every user who has a Second Brain set up.
    Only executes when ENABLE_LLM_API is True — skips silently otherwise.
    """
    from assistant_backend_1.config import ENABLE_LLM_API
    if not ENABLE_LLM_API:
        print("⏭️ Task moving skipped — ENABLE_LLM_API is False.")
        return

    from assistant_backend_1.features_services.notion_agent import run_notion_task_moving

    users = load_users()
    for chat_id, user_data in users.items():
        token = user_data.get("notion", {}).get("token")
        second_brain = user_data.get("second_brain", {})
        if not token or not second_brain.get("databases", {}).get("tasks_todos"):
            continue
        print(f"🤖 Running task moving agent for user {chat_id}...")
        try:
            run_notion_task_moving(chat_id, token)
        except Exception as e:
            print(f"❌ Task moving failed for user {chat_id}: {e}")


# ============================================
# SCHEDULER
# ============================================

def start_reminder_scheduler():
    """Call this from app.py / lifespan to start scheduler in background."""
    print(f"🚀 Reminder scheduler starting...")
    print(f"⏱ Reminders: every {CHECK_INTERVAL_MINUTES} min | Task moving: every {TASK_MOVING_INTERVAL_MINUTES} min")

    check_and_remind()
    mark_overdue_tasks_done()
    run_task_moving_for_all_users()

    schedule.every(CHECK_INTERVAL_MINUTES).minutes.do(check_and_remind)
    schedule.every(CHECK_INTERVAL_MINUTES).minutes.do(mark_overdue_tasks_done)
    schedule.every(TASK_MOVING_INTERVAL_MINUTES).minutes.do(run_task_moving_for_all_users)

    while True:
        schedule.run_pending()
        time.sleep(30)