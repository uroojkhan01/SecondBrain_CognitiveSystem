from fastapi import Request
from assistant_backend_1.helpers import load_users, save_users
from assistant_backend_1.models.db_helpers import save_user, get_oauth_url, is_notion_connected
from assistant_backend_1.models.db_hooks import hook_upsert_user, hook_save_message, hook_save_capture, hook_save_voice_message, hook_mark_task_done
from assistant_backend_1.features_services.telegram import send_message, process_voice_message
from assistant_backend_1.features_services.voice_to_text import transcribe_audio_file
import asyncio
from assistant_backend_1.features_services.llm_conversation import process_user_input
from assistant_backend_1.config import ENABLE_LLM_API

# In-memory state for /done selection flow (chat_id → pending task list)
_pending_done_tasks: dict[str, list] = {}

# In-memory state for database selection flow (chat_id → selectable db list)
_pending_db_selection: dict[str, list] = {}

_DB_KEYWORDS = (
    "database", "databases", "available db", "notion db", "which db",
    "list db", "show db", "change db", "switch db", "my dbs",
    "which database", "list databases", "show databases", "change database",
    "switch database", "available databases", "what database",
)


def _build_db_list_message(selectable: list, active_id: str) -> str:
    lines = []
    for i, db in enumerate(selectable):
        active_marker = " ✅ *(active)*" if db["id"] == active_id else ""
        lines.append(f"{i+1}. {db['name']}{active_marker}")
    return "Here are your connected Notion databases. Reply with a number to switch:\n\n" + "\n".join(lines)


async def telegram_webhook(request: Request):

    # ── 1. Parse request — ignore anything malformed ──────────────────
    try:
        data = await request.json()
    except Exception:
        return {"status": "ignored"}

    print("Telegram Update:", data)

    message = data.get("message")
    if not message:
        return {"status": "ignored"}

    # Extract chat_id early so we can send error replies if anything below fails
    try:
        chat_id = str(message["chat"]["id"])
        first_name = message["chat"].get("first_name")
        username = message["chat"].get("username")
    except (KeyError, TypeError):
        return {"status": "ignored"}

    # ── 2. Everything else wrapped — user always gets a reply ──────────
    try:
        # ── Voice vs text input ───────────────────────────────────────
        voice_file_id = None
        transcript = None

        if "voice" in message:
            try:
                voice = message["voice"]
                voice_file_id = voice["file_id"]
                voice_duration = voice["duration"]
                print(f"Voice message received! Duration: {voice_duration} seconds.")
                audio_path = await process_voice_message(file_id=voice_file_id)
                transcript = await asyncio.to_thread(transcribe_audio_file, audio_path)
                user_input = transcript
                print("Transcript:", user_input)
            except Exception as e:
                print(f"❌ Voice processing failed: {e}")
                await send_message(chat_id, "Sorry, I couldn't process your voice message. Please try sending it as text!")
                return {"status": "ok"}
        else:
            text = message.get("text", "")
            print(f"Text message received: {text}")
            user_input = text

        # ── Postgres hooks ────────────────────────────────────────────
        try:
            hook_upsert_user(chat_id, first_name=first_name, username=username)
            hook_save_capture(chat_id, user_input)
            saved_msg = hook_save_message(
                chat_id, user_input, input_type="voice" if "voice" in message else "text")
            if "voice" in message and voice_file_id:
                msg_id = saved_msg["id"] if saved_msg else None
                hook_save_voice_message(
                    chat_id, message_id=msg_id, telegram_file_id=voice_file_id, transcription=transcript)
        except Exception as e:
            print(f"⚠️ Postgres hook error (non-fatal): {e}")

        save_user(chat_id, first_name, username)

        # ── /organize command ─────────────────────────────────────────
        if user_input.strip().lower() in ("/organize", "/organize@secondbrainbot", "/organise", "/organise@secondbrainbot"):
            if not ENABLE_LLM_API:
                await send_message(chat_id, "⏭️ Task organizer is disabled (LLM API is off).")
                return {"status": "ok"}
            current_users = load_users()
            user_data = current_users.get(str(chat_id), {})
            token = user_data.get("notion", {}).get("token")
            tasks_db = user_data.get("second_brain", {}).get("databases", {}).get("tasks_todos")
            if not token or not tasks_db:
                await send_message(chat_id, "⚠️ Second Brain is not set up yet. Please connect Notion first.")
                return {"status": "ok"}
            await send_message(chat_id, "🤖 Running task organizer — this may take a moment...")
            try:
                from assistant_backend_1.features_services.notion_agent import run_notion_task_moving
                success = await asyncio.to_thread(run_notion_task_moving, chat_id, token)
                if success:
                    await send_message(chat_id, "✅ Tasks have been organized and categorized in your Second Brain!")
                else:
                    await send_message(chat_id, "Hmm, nothing new to organize right now — all your tasks may already be sorted!")
            except Exception as e:
                print(f"❌ /organize failed: {e}")
                await send_message(chat_id, "Couldn't organize tasks right now — Notion may be temporarily unavailable. Try again in a moment!")
            return {"status": "ok"}

        # ── /refresh_projects command ─────────────────────────────────
        if user_input.strip().lower() in ("/refresh_projects", "/refresh_projects@secondbrainbot"):
            current_users = load_users()
            token = current_users.get(str(chat_id), {}).get("notion", {}).get("token")
            if not token:
                await send_message(chat_id, "⚠️ Second Brain is not set up yet. Please connect Notion first.")
                return {"status": "ok"}
            await send_message(chat_id, "🔄 Refreshing project pages — this may take a moment...")
            try:
                from assistant_backend_1.features_services.notion_project_details import populate_all_projects
                await asyncio.to_thread(populate_all_projects, token, chat_id)
                await send_message(chat_id, "✅ All project pages have been updated with their areas and tasks!")
            except Exception as e:
                print(f"❌ /refresh_projects failed: {e}")
                await send_message(chat_id, "Couldn't refresh project pages right now. Try again in a moment!")
            return {"status": "ok"}

        # ── /databases command ────────────────────────────────────────
        if user_input.strip().lower() in ("/databases", "/databases@secondbrainbot", "/dbs", "/dbs@secondbrainbot"):
            current_users = load_users()
            notion_data = current_users.get(str(chat_id), {}).get("notion", {})
            active_id = notion_data.get("active_database_id", "")
            selectable = [db for db in notion_data.get("database_ids", []) if db.get("type") == "database"]
            if not selectable:
                await send_message(chat_id, "⚠️ No databases found. Please reconnect Notion.")
                return {"status": "ok"}
            _pending_db_selection[str(chat_id)] = selectable
            await send_message(chat_id, _build_db_list_message(selectable, active_id))
            return {"status": "ok"}

        # ── /done command ─────────────────────────────────────────────
        if user_input.strip().lower() in ("/done", "/done@secondbrainbot", "/complete", "/complete@secondbrainbot"):
            try:
                from assistant_backend_1.features_services.notion import get_tasks_from_notion
                tasks = await asyncio.to_thread(get_tasks_from_notion, str(chat_id))
                if not tasks:
                    await send_message(chat_id, "✅ You have no pending tasks!")
                    return {"status": "ok"}
                _pending_done_tasks[str(chat_id)] = tasks
                lines = "\n".join([
                    f"{i+1}. {t['title']}" +
                    (f"  _(due {t['due'][:10]})_" if t.get("due") else "")
                    for i, t in enumerate(tasks)
                ])
                await send_message(chat_id, f"Which task did you complete? Reply with the number:\n\n{lines}")
            except Exception as e:
                print(f"❌ /done fetch failed: {e}")
                await send_message(chat_id, "Couldn't fetch your tasks right now — Notion may be temporarily unavailable. Try again in a moment!")
            return {"status": "ok"}

        # ── Digit selection ───────────────────────────────────────────
        if user_input.strip().isdigit():
            index = int(user_input.strip()) - 1

            if str(chat_id) in _pending_done_tasks:
                tasks = _pending_done_tasks[str(chat_id)]
                if 0 <= index < len(tasks):
                    task = tasks[index]
                    del _pending_done_tasks[str(chat_id)]
                    try:
                        from assistant_backend_1.features_services.memory_journal import mark_task_done, mark_reminder_done
                        from assistant_backend_1.features_services.notion import mark_task_done_by_page_id, get_user_notion_credentials, update_project_progress
                        token, _ = get_user_notion_credentials(str(chat_id))
                        if token and task.get("page_id"):
                            await asyncio.to_thread(mark_task_done_by_page_id, token, task["page_id"])
                            await asyncio.to_thread(update_project_progress, str(chat_id), task["page_id"])
                        mark_task_done(str(chat_id), task["title"])
                        mark_reminder_done(str(chat_id), task["title"])
                        hook_mark_task_done(str(chat_id), task["title"])
                        await send_message(chat_id, f"✅ *{task['title']}* marked as done! Great work!")
                    except Exception as e:
                        print(f"❌ mark done via /done failed: {e}")
                        await send_message(chat_id, "I had trouble marking that as done — please try again!")
                    return {"status": "ok"}

            if str(chat_id) in _pending_db_selection:
                selectable = _pending_db_selection[str(chat_id)]
                if 0 <= index < len(selectable):
                    selected_db = selectable[index]
                    del _pending_db_selection[str(chat_id)]
                    try:
                        current_users = load_users()
                        current_users[str(chat_id)]["notion"]["active_database_id"] = selected_db["id"]
                        save_users(current_users)
                        await send_message(chat_id, f"✅ Active database switched to: *{selected_db['name']}*")
                    except Exception as e:
                        print(f"❌ DB switch failed: {e}")
                        await send_message(chat_id, "Couldn't switch database right now. Try again!")
                    return {"status": "ok"}

        # ── Natural language DB query ─────────────────────────────────
        if any(kw in user_input.lower() for kw in _DB_KEYWORDS):
            current_users = load_users()
            notion_data = current_users.get(str(chat_id), {}).get("notion", {})
            active_id = notion_data.get("active_database_id", "")
            selectable = [db for db in notion_data.get("database_ids", []) if db.get("type") == "database"]
            if selectable:
                _pending_db_selection[str(chat_id)] = selectable
                await send_message(chat_id, _build_db_list_message(selectable, active_id))
                return {"status": "ok"}

        # ── Notion credentials check ──────────────────────────────────
        current_users = load_users()
        print(f"Current users: {current_users}")
        user_data = current_users.get(str(chat_id), {})
        notion_data = user_data.get("notion", {})
        token = notion_data.get("token")
        active_database_id = notion_data.get("active_database_id")

        if not token:
            oauth_url = get_oauth_url(chat_id)
            await send_message(
                chat_id,
                f"👋 Welcome! Please connect your Notion account to get started:\n\n"
                f"🔗 {oauth_url}"
            )
            return {"status": "ok"}

        if not active_database_id:
            oauth_url = get_oauth_url(chat_id)
            await send_message(
                chat_id,
                f"⚠️ Notion is connected, but no pages or databases are attached to the integration.\n\n"
                f"Please click the link below to reconnect and ensure you select the pages/databases you want to share with the assistant:\n\n"
                f"🔗 {oauth_url}"
            )
            return {"status": "ok"}

        # ── LLM processing ────────────────────────────────────────────
        if ENABLE_LLM_API:
            reply = process_user_input(chat_id, user_input, first_name, username)
        else:
            reply = f"[LLM API Disabled] You said: {user_input}"

        # Sentinel: LLM classified intent as switch_database
        if reply == "__SHOW_DB_LIST__":
            current_users = load_users()
            notion_data = current_users.get(str(chat_id), {}).get("notion", {})
            active_id = notion_data.get("active_database_id", "")
            selectable = [db for db in notion_data.get("database_ids", []) if db.get("type") == "database"]
            if selectable:
                _pending_db_selection[str(chat_id)] = selectable
                reply = _build_db_list_message(selectable, active_id)
            else:
                reply = "⚠️ No databases found. Please reconnect Notion."

        print("sending message back to user")
        await send_message(chat_id, reply)
        return {"status": "ok"}

    except Exception as e:
        print(f"❌ Webhook handler crashed for {chat_id}: {e}")
        try:
            await send_message(chat_id, "Something went wrong on my end. Please try again!")
        except Exception:
            pass
        return {"status": "error"}