from fastapi import Request
from assistant_backend_1.features_services.telegram import send_message
from assistant_backend_1.helpers import save_user, get_oauth_url, load_users, is_notion_connected

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

    ### process user input through llm model ###
    from assistant_backend_1.config import ENABLE_LLM_API
    if ENABLE_LLM_API:
        reply = process_user_input(chat_id, user_input)
    else:
        reply = f"[LLM API Disabled] You said: {user_input}"

    first_name = message["chat"].get("first_name")
    username = message["chat"].get("username")
    text = message.get("text", "")

    # Save user to JSON
    save_user(chat_id, first_name, username)
    current_users = load_users()
    print(f"Current users: {current_users}")

    # Check Notion credentials and attachment status
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

    # Notion is connected and active — handle message normally

    print("sending message back to user")
    await send_message(chat_id, reply)
    return {"status": "ok"}
