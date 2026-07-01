# assistant_backend_1/features_services/reminders.py
"""
Reminders Service
-----------------
CRUD operations for reminders stored in Neo4j.
Scheduler jobs (check_and_remind, etc.) live in backgroundjobs.py.
"""


def create_reminder(chat_id: str, text: str, remind_at: str = None) -> bool:
    """Create a new reminder in Neo4j."""
    from assistant_backend_1.features_services.memory_journal import save_reminder
    try:
        save_reminder(chat_id, text, remind_at)
        return True
    except Exception as e:
        print(f"❌ Error creating reminder: {e}")
        return False


def get_all_reminders(chat_id: str) -> list:
    """Fetch all reminders for a user from Neo4j."""
    from assistant_backend_1.features_services.memory_journal import get_local_reminders
    try:
        return get_local_reminders(chat_id)
    except Exception as e:
        print(f"❌ Error fetching reminders: {e}")
        return []


def update_reminder(chat_id: str, page_id: str, text: str = None, remind_at: str = None) -> bool:
    """Update an existing reminder in Neo4j."""
    from assistant_backend_1.features_services.memory_journal import update_local_reminder
    try:
        return update_local_reminder(chat_id, page_id, text, remind_at)
    except Exception as e:
        print(f"❌ Error updating reminder: {e}")
        return False


def delete_reminder(chat_id: str, page_id: str) -> bool:
    """Delete a reminder from Neo4j."""
    from assistant_backend_1.features_services.memory_journal import delete_local_reminder
    try:
        return delete_local_reminder(chat_id, page_id)
    except Exception as e:
        print(f"❌ Error deleting reminder: {e}")
        return False
