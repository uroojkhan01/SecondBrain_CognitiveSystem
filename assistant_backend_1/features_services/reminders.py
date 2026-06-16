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
# SCHEDULER
# ============================================

def start_reminder_scheduler():
    """Call this from app.py / lifespan to start scheduler in background"""
    print(f"🚀 Reminder scheduler starting...")
    print(f"⏱ Checking every {CHECK_INTERVAL_MINUTES} minutes")

    check_and_remind()  # run once immediately

    schedule.every(CHECK_INTERVAL_MINUTES).minutes.do(check_and_remind)

    while True:
        schedule.run_pending()
        time.sleep(30)