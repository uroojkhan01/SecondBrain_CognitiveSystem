from fastapi import Request
from assistant_backend_1.features_services.telegram import send_message
from assistant_backend_1.helpers import save_user,get_oauth_url, load_users,is_notion_connected 

from assistant_backend_1.features_services.telegram import (
    send_message,
    process_voice_message
)
from assistant_backend_1.features_services.voice_to_text import transcribe_audio_file
import asyncio


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

        reply = f"You said (voice): {transcript}"

    else:

        text = message.get("text", "")

        print(f"Text message received: {text}")

        reply = f"You said: {text}"

    chat_id = str(message["chat"]["id"])
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
    await send_message(chat_id, reply)
    return {"status": "ok"}
   
