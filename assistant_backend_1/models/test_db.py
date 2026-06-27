# test_db.py — tests for SQLAlchemy db layer

from assistant_backend_1.models.db import (
    upsert_user,
    get_user_by_chat_id,
    set_notion_connected,
    save_notion_token,
    save_notion_database,
    get_notion_databases,
    delete_notion_database,
    save_message,
    get_recent_messages,
    save_voice_message,
    update_voice_transcription,
    save_capture,
    mark_capture_processed,
    save_task,
    get_tasks,
    update_task,
    update_task_status,
    delete_task,
    save_reminder,
    get_reminders_for_user,
    get_due_reminders,
    mark_reminder_sent,
    update_reminder,
    delete_reminder,
)
from assistant_backend_1.models.database import User
from assistant_backend_1.models.db import get_session


def cleanup(chat_id: str):
    with get_session() as session:
        user = session.query(User).filter_by(chat_id=chat_id).first()
        if user:
            session.delete(user)
            session.commit()


def run():
    print("starting db tests...\n")
    chat_id = "test_sqlalchemy_001"
    cleanup(chat_id)

    # users
    user = upsert_user(chat_id=chat_id, first_name="Noza", username="nozatest")
    assert user["chat_id"] == chat_id
    print(f"upsert_user: {user['id']}")

    fetched = get_user_by_chat_id(chat_id)
    assert fetched["id"] == user["id"]
    print(f"get_user_by_chat_id: ok")

    updated = set_notion_connected(user["id"], True)
    assert updated["notion_connected"] == True
    print(f"set_notion_connected: ok")

    save_notion_token(user["id"], "notion_token_xyz")
    fetched2 = get_user_by_chat_id(chat_id)
    assert fetched2["notion_access_token"] == "notion_token_xyz"
    print(f"save_notion_token: ok")

    # notion_databases
    notion_db = save_notion_database(user["id"], "notion_abc_123", name="Tasks DB")
    assert notion_db["notion_db_id"] == "notion_abc_123"
    print(f"save_notion_database: {notion_db['id']}")

    notion_dbs = get_notion_databases(user["id"])
    assert len(notion_dbs) >= 1
    print(f"get_notion_databases: {len(notion_dbs)} found")

    # messages
    msg = save_message(
        user_id=user["id"],
        raw_input="I visited the doctor on Monday",
        input_type="text",
        intent="save_memory"
    )
    assert msg["user_id"] == user["id"]
    print(f"save_message: {msg['id']}")

    recent = get_recent_messages(user["id"], limit=5)
    assert len(recent) >= 1
    print(f"get_recent_messages: {len(recent)} found")

    # voice messages
    voice_msg_raw = save_message(user_id=user["id"], raw_input=None, input_type="voice")
    voice = save_voice_message(
        message_id=voice_msg_raw["id"],
        user_id=user["id"],
        telegram_file_id="tg_file_xyz",
        transcription=None
    )
    print(f"save_voice_message: {voice['id']}")

    updated_voice = update_voice_transcription(voice["id"], "remind me to call mom")
    assert updated_voice["transcription"] == "remind me to call mom"
    print(f"update_voice_transcription: ok")

    # captures
    capture = save_capture(user_id=user["id"], raw_text="hey remind me to buy milk", source="telegram")
    print(f"save_capture: {capture['id']}")

    mark_capture_processed(capture["id"])
    print(f"mark_capture_processed: ok")

    # tasks
    task = save_task(
        user_id=user["id"],
        title="Follow up with doctor",
        message_id=msg["id"],
        notion_database_id=notion_db["id"],
        due_date="2026-06-01"
    )
    print(f"save_task: {task['id']}")

    tasks = get_tasks(user["id"])
    assert any(t["id"] == task["id"] for t in tasks)
    print(f"get_tasks: {len(tasks)} found")

    tasks_pending = get_tasks(user["id"], status="pending")
    assert any(t["id"] == task["id"] for t in tasks_pending)
    print(f"get_tasks by status: ok")

    updated_task = update_task(task["id"], title="Follow up with doctor asap", due_date="2026-06-02")
    assert updated_task["title"] == "Follow up with doctor asap"
    print(f"update_task: ok")

    updated_status = update_task_status(task["id"], "done")
    assert updated_status["status"] == "done"
    print(f"update_task_status: ok")

    # reminders
    reminder = save_reminder(
        user_id=user["id"],
        text="Call doctor office",
        remind_at="2026-06-01T09:00:00+00:00",
        message_id=msg["id"],
        task_id=task["id"]
    )
    print(f"save_reminder: {reminder['id']}")

    standalone = save_reminder(
        user_id=user["id"],
        text="Drink water",
        remind_at="2026-06-01T10:00:00+00:00"
    )
    print(f"save_reminder standalone: {standalone['id']}")

    reminders = get_reminders_for_user(user["id"])
    assert len(reminders) >= 2
    print(f"get_reminders_for_user: {len(reminders)} found")

    updated_r = update_reminder(reminder["id"], text="Call doctor urgently")
    assert updated_r["text"] == "Call doctor urgently"
    print(f"update_reminder: ok")

    sent = mark_reminder_sent(reminder["id"])
    assert sent["is_sent"] == "True"
    print(f"mark_reminder_sent: ok")

    due = get_due_reminders()
    print(f"get_due_reminders: {len(due)} found")

    delete_reminder(standalone["id"])
    print(f"delete_reminder: ok")

    delete_task(task["id"])
    print(f"delete_task: ok")

    # cleanup
    cleanup(chat_id)
    print(f"\ncleanup: test user deleted")
    print("\nall tests passed.")


if __name__ == "__main__":
    run()