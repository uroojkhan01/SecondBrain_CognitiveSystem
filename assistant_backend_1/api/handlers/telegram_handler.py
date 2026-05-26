from fastapi import Request
from assistant_backend_1.features_services.telegram import send_message
from assistant_backend_1.helpers import save_user,get_oauth_url, load_users, save_users,is_notion_connected 
import requests
from assistant_backend_1.config import NOTION_CLIENT_ID, NOTION_CLIENT_SECRET, NOTION_REDIRECT_URI
from fastapi.responses import HTMLResponse



async def telegram_webhook(request: Request):

    data = await request.json()

    print("Telegram Update:", data)

    message = data.get("message")

    if not message:
        return {"status": "ignored"}


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
    await send_message(chat_id, f"You said: {text}")
    return {"status": "ok"}
   
# ============================================
# NOTION OAUTH CALLBACK
# ============================================

async def notion_oauth_callback(request: Request):
    code = request.query_params.get("code")
    state = request.query_params.get("state")
    chat_id = state.replace("tg_", "") if state else None

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

    # Fetch all databases user gave access to
    db_response = requests.post(
        "https://api.notion.com/v1/search",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "Notion-Version": "2022-06-28"
        },
        json={"filter": {"value": "database", "property": "object"}}
    )

    databases = db_response.json().get("results", [])
    print(f"Found {len(databases)} databases")

    # Build database list
    database_list = []
    for db in databases:
        try:
            db_name = db["title"][0]["text"]["content"]
        except:
            db_name = "Untitled"
        database_list.append({
            "id": db["id"],
            "name": db_name
        })

    # Save token and databases
    users = load_users()
    if str(chat_id) not in users:
        users[str(chat_id)] = {}

    users[str(chat_id)]["notion"] = {
        "token": access_token,
        "active_database_id": database_list[0]["id"] if database_list else None,
        "database_ids": database_list
    }
    save_users(users)

    # Notify user
    if len(database_list) > 1:
        db_options = "\n".join([
            f"{i+1}. {db['name']}" for i, db in enumerate(database_list)
        ])
        await send_message(
            chat_id,
            f"✅ Notion connected!\n\n"
            f"📚 Found {len(database_list)} databases:\n\n"
            f"{db_options}\n\n"
            f"Reply with the number to select one.\n"
            f"Currently using: *{database_list[0]['name']}*"
        )
    else:
        await send_message(
            chat_id,
            f"✅ Notion connected!\n\n"
            f"📚 Using: *{database_list[0]['name'] if database_list else 'No database found'}*\n\n"
            f"You can now send me tasks!"
        )

    return HTMLResponse("""
        <html>
        <body style="font-family: sans-serif; text-align: center; padding: 50px;">
            <h2>✅ Notion Connected!</h2>
            <p>Go back to Telegram to select your database.</p>
        </body>
        </html>
    """)

