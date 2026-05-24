from fastapi import Request
from assistant_backend_1.features_services.telegram import send_message


async def telegram_webhook(request: Request):

    data = await request.json()

    print("Telegram Update:", data)

    message = data.get("message")

    if not message:
        return {"status": "ignored"}

    chat_id = message["chat"]["id"]
    text = message.get("text", "")

    reply = f"You said: {text}"

    await send_message(chat_id, reply)

    return {"status": "ok"}
