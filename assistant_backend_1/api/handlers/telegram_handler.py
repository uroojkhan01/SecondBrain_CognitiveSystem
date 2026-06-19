from fastapi import Request
from assistant_backend_1.features_services.telegram import send_message
# from assistant_backend_1.helpers import save_user, get_oauth_url, load_users, is_notion_connected

# NEW
from assistant_backend_1.models.db_helpers import save_user, get_oauth_url, load_users, is_notion_connected
from assistant_backend_1.models.db_hooks import hook_upsert_user, hook_save_message, hook_save_capture

from assistant_backend_1.features_services.telegram import (
    send_message,
    process_voice_message
)
from assistant_backend_1.features_services.voice_to_text import transcribe_audio_file
import asyncio
from assistant_backend_1.features_services.llm_conversation import process_user_input


async def telegram_webhook(request: Request):

    data = await request.json()

    print("Telegram Update:", data)

    message = data.get("message")

    if not message:
        return {"status": "ignored"}

    if "voice" in message:

        voice = message["voice"]
        voice_file_id = voice["file_id"]
        voice_duration = voice["duration"]

        print(f"Voice message received! Duration: {voice_duration} seconds.")

        # process voice in service
        audio_path = await process_voice_message(file_id=voice_file_id)
        transcript = await asyncio.to_thread(
            transcribe_audio_file,
            audio_path
        )

        user_input = transcript
        print("this is reply", user_input)

    else:

        text = message.get("text", "")
        print(f"Text message received: {text}")
        user_input = text

    chat_id = str(message["chat"]["id"])

    # mirror into Supabase
    hook_upsert_user(chat_id, first_name=message["chat"].get("first_name"), username=message["chat"].get("username"))
    hook_save_capture(chat_id, user_input)

    ### process user input through llm model ###
    reply = process_user_input(chat_id, user_input)
    hook_save_message(chat_id, user_input, intent=None, input_type="voice" if "voice" in message else "text")

    first_name = message["chat"].get("first_name")
    username = message["chat"].get("username")
    text = message.get("text", "")

    # Save user to JSON
    save_user(chat_id, first_name, username)
    print(f"Current users: {load_users()}")

    if not is_notion_connected(chat_id):
        oauth_url = get_oauth_url(chat_id)
        await send_message(
            chat_id,
            f"👋 Welcome! Please connect your Notion account to get started:\n\n"
            f"🔗 {oauth_url}"
        )
        return {"status": "ok"}

    # Notion is connected — handle message normally

    print("sending message back to user")
    await send_message(chat_id, reply)
    return {"status": "ok"}
