#!/usr/bin/env python3
import os
import sys
import re
import json
import asyncio
import urllib.parse
import webbrowser
from datetime import datetime

# =====================================================================
# 1. PRE-IMPORT MOCKS (Preventing DB connection crashes)
# =====================================================================
from unittest.mock import MagicMock

class MockRecord:
    def __init__(self, data):
        self._data = data
    def __getitem__(self, key):
        return self._data.get(key)
    def get(self, key, default=None):
        return self._data.get(key, default)
    def __repr__(self):
        return repr(self._data)

class MockResult:
    def __init__(self, records):
        self.records = [MockRecord(r) if isinstance(r, dict) else r for r in records]
    def __iter__(self):
        return iter(self.records)
    def single(self):
        if self.records:
            return self.records[0]
        return MockRecord({"node_id": "mock_node_id", "deleted_count": 1})

# Intercept and mock neo4j library before importing memory_journal
mock_neo4j = MagicMock()
mock_driver = MagicMock()
mock_session = MagicMock()

# Setup default dummy returns for Neo4j queries
dummy_responses = {
    "MATCH (u:User {chat_id: $chat_id})-[:REMEMBERS]->(m:Memory)": [],
    "MATCH (u:User {chat_id: $chat_id})-[:KNOWS]->(e:Entity": [],
    "MATCH (u:User {chat_id: $chat_id})-[:CREATED]->(t:Task": [],
    "MATCH (u:User {chat_id: $chat_id})-[:SET]->(r:Reminder)": [],
    "MATCH (u:User {chat_id: $chat_id})-[:TRACKED]->(log:HabitLog)": [],
}

def mock_run(query, *args, **kwargs):
    # Match basic queries to return empty lists so context generation doesn't fail
    for q_prefix, response in dummy_responses.items():
        if q_prefix in query:
            return MockResult(response)
    return MockResult([])

mock_session.run = mock_run
mock_session.__enter__.return_value = mock_session
mock_driver.session.return_value = mock_session
mock_neo4j.GraphDatabase.driver.return_value = mock_driver

sys.modules['neo4j'] = mock_neo4j

# =====================================================================
# 2. ENVIROMENT & CONFIGURATION INITIALIZATION
# =====================================================================
# Load .env
env_file = ".env"
if not os.path.exists(env_file):
    if os.path.exists(".env.example"):
        print("📝 Creating .env from .env.example...")
        with open(".env.example", "r") as src:
            content = src.read()
        with open(".env", "w") as dest:
            dest.write(content)
    else:
        print("⚠️ Warning: .env and .env.example not found.")

# Add current directory to path
sys.path.insert(0, os.path.abspath(os.path.dirname(os.path.dirname(__file__))))

# Setup Groq and Notion environment check
import assistant_backend_1.config as config
from assistant_backend_1.helpers import load_users, save_users, is_notion_connected, get_oauth_url

# Intercept Telegram send_message to prevent outgoing web calls
import assistant_backend_1.features_services.telegram as telegram_module
captured_replies = []

async def mock_send_message(chat_id: int, text: str):
    captured_replies.append(text)
    print(f"\n💬 [System Output to Telegram]: {text}")

telegram_module.send_message = mock_send_message

# =====================================================================
# 3. INTERACTIVE AUTHENTICATION HELPERS
# =====================================================================
def get_valid_groq_key():
    if config.GROQ_API_KEYS:
        return config.GROQ_API_KEYS[0]
    
    print("\n🔑 --- Groq API Key Required ---")
    print("We did not find any GROQ_API_KEY_x or GROQ_API_KEY in your environment.")
    key = input("Enter your Groq API Key: ").strip()
    if key:
        config.GROQ_API_KEYS = [key]
        os.environ["GROQ_API_KEY"] = key
        return key
    else:
        print("❌ Error: Groq API Key is required to run the cognitive reasoning loops.")
        sys.exit(1)

import requests

def setup_notion_oauth(chat_id: str):
    users = load_users()
    user = users.get(str(chat_id), {})
    notion_data = user.get("notion", {})
    
    if notion_data and notion_data.get("token"):
        print(f"\n✅ Notion is already connected for test chat ID '{chat_id}'.")
        print(f"Token: {notion_data.get('token')[:10]}...")
        print(f"Active Database ID: {notion_data.get('active_database_id')}")
        return notion_data.get("token"), notion_data.get("active_database_id")
    
    print("\n📂 --- Connect Notion Workspace ---")
    client_id = os.getenv("NOTION_CLIENT_ID") or config.NOTION_CLIENT_ID
    client_secret = os.getenv("NOTION_CLIENT_SECRET") or config.NOTION_CLIENT_SECRET
    redirect_uri = os.getenv("NOTION_REDIRECT_URI") or config.NOTION_REDIRECT_URI
    
    if not client_id or not client_secret:
        print("❌ Error: Notion client credentials missing in config/environment.")
        print("Please check your .env file.")
        sys.exit(1)
        
    oauth_url = (
        f"https://api.notion.com/v1/oauth/authorize"
        f"?client_id={client_id}"
        f"&response_type=code"
        f"&owner=user"
        f"&redirect_uri={urllib.parse.quote(redirect_uri)}"
        f"&state=tg_{chat_id}"
    )
    
    print(f"\nOpening Notion Authorization Page in your default browser...")
    print(f"URL: {oauth_url}\n")
    
    try:
        webbrowser.open(oauth_url)
    except Exception as e:
        print(f"Could not open browser automatically: {e}")
        
    print("👉 ACTION REQUIRED:")
    print("1. Select the Notion workspace and pages you want to share.")
    print("2. Click 'Allow access'.")
    print("3. After redirecting (even if it shows a loading/network error), copy the full URL from your browser's address bar.")
    print("4. Paste it below:")
    
    redirected_url = input("\nPaste Redirected URL: ").strip()
    
    # Extract code and state
    parsed_url = urllib.parse.urlparse(redirected_url)
    query_params = urllib.parse.parse_qs(parsed_url.query)
    
    code = query_params.get("code", [None])[0]
    if not code and "code=" in redirected_url:
        match = re.search(r"code=([^&]+)", redirected_url)
        if match:
            code = match.group(1)
            
    if not code:
        print("❌ Error: Could not extract Notion authorization code from input.")
        return None, None
        
    print("\nExchanging code for integration access token...")
    try:
        token_response = requests.post(
            "https://api.notion.com/v1/oauth/token",
            auth=(client_id, client_secret),
            json={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri
            }
        )
        token_data = token_response.json()
    except Exception as e:
        print(f"❌ Network error exchanging code: {e}")
        return None, None
        
    access_token = token_data.get("access_token")
    if not access_token:
        print(f"❌ Token exchange failed. Notion response: {token_data}")
        return None, None
        
    print("✅ Notion access token received successfully.")
    
    # Fetch database ids
    print("Scanning Notion workspace for databases...")
    try:
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
    except Exception as e:
        print(f"❌ Failed to fetch database list: {e}")
        databases = []
        
    database_list = []
    for db in databases:
        try:
            db_name = db["title"][0]["text"]["content"]
        except Exception:
            db_name = "Untitled Database"
        database_list.append({
            "id": db["id"],
            "name": db_name
        })
        
    if not database_list:
        print("⚠️ Warning: No databases found in workspace. The system requires at least one database.")
        print("Please create a Notion database on your authorized page and run this setup again.")
        return None, None
        
    print(f"Found {len(database_list)} database(s):")
    for idx, db in enumerate(database_list):
        print(f"  [{idx + 1}] {db['name']} ({db['id']})")
        
    active_database = database_list[0]["id"]
    
    # Save user credentials locally
    users = load_users()
    users[str(chat_id)] = {
        "user": {
            "chat_id": chat_id,
            "first_name": "TestUser",
            "username": "test_simulation_user",
            "joined_at": str(datetime.now())
        },
        "notion": {
            "token": access_token,
            "active_database_id": active_database,
            "database_ids": database_list
        }
    }
    save_users(users)
    print(f"✅ Credentials successfully saved to user.json under chat_id '{chat_id}'.")
    return access_token, active_database

# =====================================================================
# 4. SIMULATIONS.MD MARKDOWN PARSER
# =====================================================================
def parse_simulations(filepath):
    stories = []
    if not os.path.exists(filepath):
        print(f"❌ Error: File {filepath} not found.")
        return stories
        
    with open(filepath, 'r', encoding='utf-8') as f:
        for line in f:
            if line.strip().startswith('|'):
                parts = [p.strip() for p in line.split('|')[1:-1]]
                if not parts or len(parts) < 7:
                    continue
                # Skip headers & lines containing only table formatting
                if parts[0].startswith('**ID**') or parts[0].startswith('---') or parts[0] == 'ID':
                    continue
                
                us_id = parts[0].replace('**', '').strip()
                theme = parts[1].replace('**', '').strip()
                scenario = parts[2].strip()
                um1 = parts[3].strip()
                ar1 = parts[4].strip()
                um2 = parts[5].strip()
                ar2 = parts[6].strip()
                
                stories.append({
                    "id": us_id,
                    "theme": theme,
                    "scenario": scenario,
                    "um1": um1,
                    "ar1": ar1,
                    "um2": um2,
                    "ar2": ar2
                })
    return stories

def clean_user_message(msg: str) -> str:
    """Extracts transcription from markdown/voice notations."""
    msg = msg.strip()
    # If the user message is a voice note representation, pull the text inside quotes
    if "Voice note:" in msg or "🎤" in msg:
        match = re.search(r'"([^"]+)"', msg)
        if match:
            return match.group(1)
        # Fallback regex replacing voice indicators
        cleaned = re.sub(r'^.*?Voice note:\s*', '', msg, flags=re.IGNORECASE)
        return cleaned.strip('* "')
    return msg

# =====================================================================
# 5. CORE TEST EXECUTION RUNNER
# =====================================================================
async def run_story(story: dict, chat_id: str):
    print("\n" + "=" * 60)
    print(f"🚀 Running Story {story['id']} - Theme: {story['theme']}")
    print(f"Scenario: {story['scenario']}")
    print("=" * 60)
    
    from assistant_backend_1.features_services.llm_conversation import process_user_input
    
    # --- Turn 1 ---
    input_1 = clean_user_message(story["um1"])
    print(f"\n👤 [User Message 1]: {story['um1']}")
    print(f"🤖 [Expected Response 1]: {story['ar1']}")
    
    # Process turn 1
    captured_replies.clear()
    loop = asyncio.get_running_loop()
    # Simulate turn 1 direct call
    reply_1 = await loop.run_in_executor(None, process_user_input, chat_id, input_1)
    
    print(f"🧠 [Actual System Response 1]: {reply_1}")
    
    # --- Turn 2 ---
    input_2 = clean_user_message(story["um2"])
    print(f"\n👤 [User Message 2]: {story['um2']}")
    print(f"🤖 [Expected Response 2]: {story['ar2']}")
    
    # Process turn 2
    captured_replies.clear()
    reply_2 = await loop.run_in_executor(None, process_user_input, chat_id, input_2)
    
    print(f"🧠 [Actual System Response 2]: {reply_2}")
    print("=" * 60)

# =====================================================================
# 6. MAIN CLI MENU
# =====================================================================
async def main():
    chat_id = "test_simulation_user_123"
    
    # Ensure Groq API Key
    get_valid_groq_key()
    
    # Ensure Notion Connected
    token, db_id = setup_notion_oauth(chat_id)
    if not token:
        print("❌ Cannot proceed without Notion connection.")
        return
        
    # Enable LLM API for test
    import assistant_backend_1.config as config_mod
    config_mod.ENABLE_LLM_API = True
    
    # Parse simulations.md
    simulations_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "Simulations.md")
    stories = parse_simulations(simulations_path)
    
    if not stories:
        print(f"⚠️ No user stories parsed from {simulations_path}.")
        return
        
    print(f"\n✅ Parsed {len(stories)} User Stories successfully.")
    
    while True:
        print("\n--- SECOND BRAIN ARCHITECTURE TEST MENU ---")
        print("1. Run a single User Story (US1 - US25)")
        print("2. Run all User Stories sequentially")
        print("3. Run custom user input conversation")
        print("4. Exit")
        
        choice = input("Select an option (1-4): ").strip()
        
        if choice == "1":
            us_id = input(f"Enter User Story ID (e.g. US1 to US{len(stories)}): ").strip().upper()
            selected = None
            for s in stories:
                if s["id"] == us_id:
                    selected = s
                    break
            if selected:
                await run_story(selected, chat_id)
            else:
                print("❌ Invalid User Story ID.")
                
        elif choice == "2":
            print(f"\nStarting sequential run of all {len(stories)} user stories...")
            for s in stories:
                await run_story(s, chat_id)
                print("\nPress Enter to continue to the next story, or 'q' to abort...")
                cont = input().strip().lower()
                if cont == 'q':
                    break
                    
        elif choice == "3":
            print("\nEntering Custom Conversation mode. Type 'exit' to quit.")
            from assistant_backend_1.features_services.llm_conversation import process_user_input
            loop = asyncio.get_running_loop()
            while True:
                user_msg = input("\n👤 You: ").strip()
                if user_msg.lower() in ["exit", "quit"]:
                    break
                if not user_msg:
                    continue
                reply = await loop.run_in_executor(None, process_user_input, chat_id, user_msg)
                print(f"🧠 Assistant: {reply}")
                
        elif choice == "4":
            print("Goodbye!")
            break
        else:
            print("❌ Invalid option. Try again.")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nAborted.")
