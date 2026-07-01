"""
backgroundjobs.py

All scheduled background jobs for the Second Brain assistant.
Started once from app.py lifespan via start_reminder_scheduler().

Schedule:
  - Reminders check:    every 5 min
  - Overdue task mark:  every 12 hours
  - Task moving agent:  every 30 min
  - Progress bar sync:  every 10 min
"""

import time
import pytz
import schedule
import requests
from datetime import datetime
from assistant_backend_1.helpers import load_users

CHECK_INTERVAL_MINUTES = 5
TASK_MOVING_INTERVAL_MINUTES = 30


# ── Helpers ────────────────────────────────────────────────────────────────────

def _send_telegram(chat_id: str, message: str):
    """Synchronous Telegram send for use in background threads (no async context)."""
    from assistant_backend_1.config import TELEGRAM_BOT_TOKEN
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        response = requests.post(url, json={
            "chat_id": chat_id, "text": message, "parse_mode": "Markdown"
        })
        response.raise_for_status()
        print(f"✅ Reminder sent to {chat_id}")
    except Exception as e:
        print(f"❌ Error sending to {chat_id}: {e}")


# ── Jobs ───────────────────────────────────────────────────────────────────────

def check_and_remind():
    """Poll Neo4j for due reminders and fire Telegram alerts."""
    print(
        f"\n🔍 Checking reminders at {datetime.now().strftime('%Y-%m-%d %H:%M')}")

    from assistant_backend_1.features_services.memory_journal import get_due_reminders, mark_reminder_sent

    try:
        reminders = get_due_reminders()
    except Exception as e:
        print(f"❌ Error fetching reminders from Neo4j: {e}")
        return

    if not reminders:
        print("No pending reminders.")
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
            remind_at = datetime.fromisoformat(remind_at_str)
            if remind_at.tzinfo is None:
                remind_at = pytz.timezone("Europe/Berlin").localize(remind_at)

            if now >= remind_at.astimezone(pytz.utc):
                _send_telegram(chat_id, f"⏰ *Reminder!*\n\n📌 {text}")
                mark_reminder_sent(node_id)
                print(f"✅ Reminder sent: {text} (ID: {node_id})")
        except Exception as e:
            print(f"❌ Error processing reminder {node_id}: {e}")

    print("✅ Reminder check complete")


def mark_overdue_tasks_done():
    """Auto-mark tasks as done in Neo4j/Notion if their execution date has passed."""
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
                        print(
                            f"✅ Auto-marked overdue task done: '{title}' for {chat_id}")
                except Exception as e:
                    print(
                        f"❌ Error parsing due date for task '{task.get('title')}': {e}")
        except Exception as e:
            print(f"❌ Error auto-marking tasks for {chat_id}: {e}")


def sync_progress_bars_for_all_users():
    """Recalculate Progress Bar for every project for every user."""
    from assistant_backend_1.features_services.notion import sync_all_project_progress

    users = load_users()
    for chat_id, user_data in users.items():
        if not user_data.get("second_brain", {}).get("databases", {}).get("master_projects"):
            continue
        try:
            sync_all_project_progress(chat_id)
        except Exception as e:
            print(f"❌ Progress sync failed for {chat_id}: {e}")


def run_task_moving_for_all_users():
    """Run the AI organize agent for every user who has a Second Brain set up."""
    from assistant_backend_1.config import ENABLE_LLM_API
    if not ENABLE_LLM_API:
        print("⏭️ Task moving skipped — ENABLE_LLM_API is False.")
        return

    from assistant_backend_1.features_services.notion_agent import run_notion_task_moving

    users = load_users()
    for chat_id, user_data in users.items():
        token = user_data.get("notion", {}).get("token")
        if not token or not user_data.get("second_brain", {}).get("databases", {}).get("tasks_todos"):
            continue
        print(f"🤖 Running task moving agent for user {chat_id}...")
        try:
            run_notion_task_moving(chat_id, token)
        except Exception as e:
            print(f"❌ Task moving failed for user {chat_id}: {e}")


# ── Scheduler entry point ──────────────────────────────────────────────────────

def start_reminder_scheduler():
    """Start all background jobs. Call once from app.py lifespan in a background thread."""
    print(f"🚀 Background scheduler starting...")
    print(
        f"⏱  Reminders: every {CHECK_INTERVAL_MINUTES} min | "
        f"Overdue: every 12 h | "
        f"Task moving: every {TASK_MOVING_INTERVAL_MINUTES} min | "
        f"Progress sync: every 10 min"
    )

    # Run all jobs once immediately on startup
    check_and_remind()
    mark_overdue_tasks_done()
    run_task_moving_for_all_users()
    sync_progress_bars_for_all_users()

    schedule.every(CHECK_INTERVAL_MINUTES).minutes.do(check_and_remind)
    schedule.every(12).hours.do(mark_overdue_tasks_done)
    schedule.every(TASK_MOVING_INTERVAL_MINUTES).minutes.do(
        run_task_moving_for_all_users)
    schedule.every(10).minutes.do(sync_progress_bars_for_all_users)

    while True:
        schedule.run_pending()
        time.sleep(30)
