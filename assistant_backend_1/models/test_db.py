import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))

from db import (
    upsert_user,
    get_user_by_chat_id,
    set_notion_connected,
    save_notion_database,
    get_notion_databases,
    delete_notion_database,
    save_message,
    get_recent_messages,
    save_voice_message,
    update_voice_transcription,
    get_voice_message,
    save_memory,
    get_memories,
    get_memories_by_date,
    search_memories,
    delete_memory,
    update_memory_neo4j_id,
    save_task,
    get_tasks,
    update_task,
    update_task_status,
    update_task_notion_id,
    delete_task,
    save_reminder,
    get_reminders_for_user,
    get_next_reminder,
    get_due_reminders,
    mark_reminder_sent,
    update_reminder,
    delete_reminder,
)


def run():
    print("starting db tests...\n")

    # users


    user = upsert_user(chat_id="test_001", first_name="Noza", username="nozatest")
    assert user["chat_id"] == "test_001"
    print(f"upsert_user: {user['id']}")

    fetched = get_user_by_chat_id("test_001")
    assert fetched["id"] == user["id"]
    print(f"get_user_by_chat_id: ok")

    updated = set_notion_connected(user["id"], True)
    assert updated["notion_connected"] == True
    print(f"set_notion_connected: ok")

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
        intent="log_memory"
    )
    assert msg["user_id"] == user["id"]
    print(f"save_message: {msg['id']}")

    voice_msg_raw = save_message(
        user_id=user["id"],
        raw_input=None,
        input_type="voice",
        intent="log_memory"
    )
    print(f"save_message (voice): {voice_msg_raw['id']}")

    recent = get_recent_messages(user["id"], limit=5)
    assert len(recent) >= 1
    print(f"get_recent_messages: {len(recent)} found")

    # voice_messages


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

    fetched_voice = get_voice_message(voice_msg_raw["id"])
    assert fetched_voice["id"] == voice["id"]
    print(f"get_voice_message: ok")

    # memories


    memory = save_memory(
        user_id=user["id"],
        message_id=msg["id"],
        summary="Visited the doctor on Monday",
        category="health",
        event_date="2026-05-26"
    )
    print(f"save_memory: {memory['id']}")

    memory2 = save_memory(
        user_id=user["id"],
        summary="Called mom in the evening",
        category="family",
        event_date="2026-05-26"
    )
    print(f"save_memory 2: {memory2['id']}")

    memories = get_memories(user["id"])
    assert len(memories) >= 2
    print(f"get_memories: {len(memories)} found")

    memories_by_cat = get_memories(user["id"], category="health")
    assert any(m["id"] == memory["id"] for m in memories_by_cat)
    print(f"get_memories by category: ok")

    memories_by_date = get_memories_by_date(user["id"], "2026-05-26")
    assert len(memories_by_date) >= 2
    print(f"get_memories_by_date: {len(memories_by_date)} found")

    search_results = search_memories(user["id"], "doctor")
    assert any(m["id"] == memory["id"] for m in search_results)
    print(f"search_memories: {len(search_results)} found")

    updated_mem = update_memory_neo4j_id(memory["id"], "neo4j_node_abc")
    assert updated_mem["neo4j_node_id"] == "neo4j_node_abc"
    print(f"update_memory_neo4j_id: ok")

    delete_memory(memory2["id"])
    remaining = get_memories(user["id"])
    assert not any(m["id"] == memory2["id"] for m in remaining)
    print(f"delete_memory: ok")

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

    updated_notion = update_task_notion_id(task["id"], "notion_page_xyz")
    assert updated_notion["notion_page_id"] == "notion_page_xyz"
    print(f"update_task_notion_id: ok")

    # reminders


    reminder = save_reminder(
        user_id=user["id"],
        text="Call doctor office",
        remind_at="2026-06-01T09:00:00+00:00",
        message_id=msg["id"],
        task_id=task["id"]
    )
    print(f"save_reminder: {reminder['id']}")

    standalone_reminder = save_reminder(
        user_id=user["id"],
        text="Drink water",
        remind_at="2026-06-01T10:00:00+00:00"
    )
    print(f"save_reminder (standalone): {standalone_reminder['id']}")

    reminders = get_reminders_for_user(user["id"])
    assert len(reminders) >= 2
    print(f"get_reminders_for_user: {len(reminders)} found")

    next_r = get_next_reminder(user["id"])
    assert next_r is not None
    print(f"get_next_reminder: {next_r['text']}")

    updated_r = update_reminder(reminder["id"], text="Call doctor office urgently", remind_at="2026-06-01T08:00:00+00:00")
    assert updated_r["text"] == "Call doctor office urgently"
    print(f"update_reminder: ok")

    sent = mark_reminder_sent(reminder["id"])
    assert sent["is_sent"] == True
    print(f"mark_reminder_sent: ok")

    due = get_due_reminders()
    print(f"get_due_reminders: {len(due)} found")

    delete_reminder(standalone_reminder["id"])
    remaining_r = get_reminders_for_user(user["id"], include_sent=True)
    assert not any(r["id"] == standalone_reminder["id"] for r in remaining_r)
    print(f"delete_reminder: ok")

    # cleanup test user

    from db import db as supabase_client
    supabase_client.table("users").delete().eq("chat_id", "test_001").execute()
    print(f"\ncleanup: test user deleted")

    print("\nall tests passed.")


if __name__ == "__main__":
    run()