import os
import httpx

from assistant_backend_1.config import TELEGRAM_BOT_TOKEN


# -----------------------------------
# SEND TEXT MESSAGE
# -----------------------------------
async def send_message(chat_id: int, text: str):

    token = os.getenv("TELEGRAM_BOT_TOKEN") or TELEGRAM_BOT_TOKEN

    url = f"https://api.telegram.org/bot{token}/sendMessage"

    payload = {
        "chat_id": chat_id,
        "text": text
    }

    async with httpx.AsyncClient() as client:
        await client.post(url, json=payload)


# -----------------------------------
# PROCESS VOICE MESSAGE
# -----------------------------------
async def process_voice_message(file_id: str):

    token = os.getenv("TELEGRAM_BOT_TOKEN") or TELEGRAM_BOT_TOKEN

    # Step 1 → Get file path from Telegram
    get_file_url = f"https://api.telegram.org/bot{token}/getFile"

    payload = {
        "file_id": file_id
    }

    async with httpx.AsyncClient() as client:

        response = await client.post(get_file_url, json=payload)

        data = response.json()

        print("Get File Response:", data)

        file_path = data["result"]["file_path"]

        # Step 2 → Build downloadable file URL
        download_url = (
            f"https://api.telegram.org/file/bot{token}/{file_path}"
        )

        print("Download URL:", download_url)

        # Step 3 → Download voice file
        audio_response = await client.get(download_url)

        # create temp folder if not exists
        os.makedirs("temp", exist_ok=True)

        local_file_path = f"temp/{file_id}.ogg"

        with open(local_file_path, "wb") as f:
            f.write(audio_response.content)

        print(f"Voice file saved at: {local_file_path}")

    return local_file_path
