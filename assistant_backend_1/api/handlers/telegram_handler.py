from fastapi import Request
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

    chat_id = message["chat"]["id"]

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

    await send_message(chat_id, reply)

    return {"status": "ok"}
