from fastapi import Request
from assistant_backend_1.features_services.telegram import send_message
from assistant_backend_1.helpers import load_users, save_users
from assistant_backend_1.features_services.notion_agent import setup_second_brain, patch_area_task_links
import asyncio
from assistant_backend_1.models.db_helpers import save_notion_user_token, save_notion_user_database
import requests
from assistant_backend_1.config import NOTION_CLIENT_ID, NOTION_CLIENT_SECRET, NOTION_REDIRECT_URI, NOTION_VERSION
from fastapi.responses import HTMLResponse
from assistant_backend_1.api.handlers.telegram_handler import _pending_db_selection


# ============================================
# NOTION OAUTH CALLBACK
# ============================================

def fetch_database_schema(token: str, database_id: str) -> dict:
    """Fetch column names and types from a Notion database"""
    url = f"https://api.notion.com/v1/databases/{database_id}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Notion-Version": NOTION_VERSION
    }
    try:
        response = requests.get(url, headers=headers)
        data = response.json()
        
        schema = {}
        for col_name, col_data in data.get("properties", {}).items():
            schema[col_name] = col_data.get("type")
        
        print(f"📋 Schema fetched: {schema}")
        return schema
    except Exception as e:
        print(f"❌ Error fetching schema: {e}")
        return {}

def get_title_from_search_result(item: dict) -> str:
    if item.get("object") == "database":
        title_list = item.get("title", [])
        if title_list:
            return title_list[0].get("plain_text", "").strip() or title_list[0].get("text", {}).get("content", "").strip() or "Untitled Database"
        return "Untitled Database"
    elif item.get("object") == "page":
        properties = item.get("properties", {})
        for prop_name, prop_data in properties.items():
            if prop_data.get("type") == "title":
                title_list = prop_data.get("title", [])
                if title_list:
                    return title_list[0].get("plain_text", "").strip() or title_list[0].get("text", {}).get("content", "").strip() or "Untitled Page"
        return "Untitled Page"
    return "Untitled"

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

    # Fetch all pages and databases user gave access to
    db_response = requests.post(
        "https://api.notion.com/v1/search",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "Notion-Version": NOTION_VERSION
        }
    )

    databases = db_response.json().get("results", [])
    print(f"Found {len(databases)} pages/databases")

    # Build database/page list — skip rows inside databases (e.g. task entries)
    database_list = []
    for db in databases:
        parent_type = db.get("parent", {}).get("type", "")
        if parent_type == "database_id":
            continue  # this is a row inside a database, not a page or db

        obj_type = db.get("object", "database")
        db_name = get_title_from_search_result(db)

        schema = {}
        if obj_type == "database":
            schema = fetch_database_schema(access_token, db["id"])

        database_list.append({
            "id": db["id"],
            "name": db_name,
            "type": obj_type,
            "schema": schema
        })

    # # Save token and databases
    # users = load_users()
    # if str(chat_id) not in users:
    #     users[str(chat_id)] = {}

    # users[str(chat_id)]["notion"] = {
    #     "token": access_token,
    #     "active_database_id": database_list[0]["id"] if database_list else None,
    #     "database_ids": database_list
    # }
    # save_users(users)
    save_notion_user_token(chat_id, access_token)
    for db in database_list:
        save_notion_user_database(chat_id, db["id"], db["name"])

    # Let the user know setup is in progress
    await send_message(chat_id, "✅ Notion connected! Please wait, we are setting things up for you... 🛠️")

    # Build Second Brain structure
    status = await asyncio.to_thread(setup_second_brain, chat_id, access_token)

    if status == "failed":
        await send_message(chat_id, "⚠️ Second Brain setup failed. Please try reconnecting.")
        return HTMLResponse("""
            <html>
            <body style="font-family: sans-serif; text-align: center; padding: 50px;">
                <h2>⚠️ Setup Failed</h2>
                <p>Go back to Telegram and try reconnecting.</p>
            </body>
            </html>
        """)

    # Merge full OAuth database list into user.json — setup_second_brain only
    # writes Second Brain databases, so extras like "Brainstorm Session" get lost.
    users = load_users()
    existing_ids = {db["id"] for db in users[str(chat_id)]["notion"].get("database_ids", [])}
    for db in database_list:
        if db["id"] not in existing_ids:
            users[str(chat_id)]["notion"]["database_ids"].append(db)
            existing_ids.add(db["id"])
    save_users(users)

    # Reload users — only show databases (not pages) as selectable options
    users = load_users()
    full_db_list = users[str(chat_id)]["notion"]["database_ids"]
    active_id = users[str(chat_id)]["notion"]["active_database_id"]
    active_name = next((db["name"] for db in full_db_list if db["id"] == active_id), "Tasks and To Dos")

    selectable = [db for db in full_db_list if db["type"] == "database"]
    _pending_db_selection[str(chat_id)] = selectable
    db_options = "\n".join([
        f"{i+1}. {db['name']}" for i, db in enumerate(selectable)
    ])

    if status == "exists":
        # Still patch area DBs in case new fields were added since last setup
        await asyncio.to_thread(patch_area_task_links, chat_id, access_token)
        header = "🧠 Your Second Brain is already set up!\n\n"
    else:
        header = "🧠 Your Second Brain is ready!\n\n"

    await send_message(
        chat_id,
        f"{header}"
        f"📚 Available pages/databases:\n\n"
        f"{db_options}\n\n"
        f"Reply with the number to switch.\n"
        f"Currently using: *{active_name}*"
    )

    return HTMLResponse("""
        <html>
        <body style="font-family: sans-serif; text-align: center; padding: 50px;">
            <h2>✅ Notion Connected!</h2>
            <p>Go back to Telegram to select your page/database.</p>
        </body>
        </html>
    """)


