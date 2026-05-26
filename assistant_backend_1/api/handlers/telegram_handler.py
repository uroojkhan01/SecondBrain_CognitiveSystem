from fastapi import Request
from assistant_backend_1.features_services.telegram import send_message
from assistant_backend_1.helpers import save_user,get_notion_oauth_url, load_users, save_users,is_notion_connected 
import requests
from assistant_backend_1.config import NOTION_CLIENT_ID, NOTION_CLIENT_SECRET, NOTION_REDIRECT_URI
from fastapi.responses import HTMLResponse



async def telegram_webhook(request: Request):

    data = await request.json()

    print("Telegram Update:", data)

    message = data.get("message")

    if not message:
        return {"status": "ignored"}


    chat_id = message["chat"]["id"]
    first_name = message["chat"].get("first_name")
    username = message["chat"].get("username")
    text = message.get("text", "")

    # Save user to JSON
    save_user(chat_id, first_name, username)

    if not is_notion_connected(chat_id):
        oauth_url = get_notion_oauth_url(chat_id)
        await send_message(
            chat_id,
            f"👋 Welcome! Please connect your Notion account to get started:\n\n"
            f"🔗 {oauth_url}"
        )
        return {"status": "ok"}

    # Notion is connected — handle message normally
    await send_message(chat_id, f"You said: {text}")
    return {"status": "ok"}
   
# ============================================
# NOTION OAUTH CALLBACK
# ============================================

async def notion_oauth_callback(request: Request):
    code = request.query_params.get("code")
    chat_id = request.query_params.get("state")

    if not code or not chat_id:
        return {"error": "Missing code or state"}

    # Exchange code for token
    token_response = requests.post(
        "https://api.notion.com/v1/oauth/token",
        auth=(NOTION_CLIENT_ID, NOTION_CLIENT_SECRET),
        json={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": NOTION_REDIRECT_URI
        }
    )

    token_data = token_response.json()
    access_token = token_data.get("access_token")

    if not access_token:
        print(f"❌ Token error: {token_data}")
        await send_message(chat_id, "❌ Failed to connect Notion. Please try again.")
        return {"error": "Failed to get token"}

    # Save token to users.json
    users = load_users()
    if str(chat_id) not in users:
        users[str(chat_id)] = {}
    users[str(chat_id)]["notion"] = {"token": access_token}
    save_users(users)

    # Notify user
    await send_message(
        chat_id,
        "✅ Notion connected successfully!\n\nYou can now send me tasks!"
    )

    return HTMLResponse("""
        <html>
        <body style="font-family: sans-serif; text-align: center; padding: 50px;">
            <h2>✅ Notion Connected!</h2>
            <p>Go back to Telegram and start sending tasks!</p>
        </body>
        </html>
    """)


