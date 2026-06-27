import requests
from assistant_backend_1.helpers import load_users, save_users

NOTION_API = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"

AREA_DATABASES = [
    "Health & Fitness",
    "Finance & Wealth",
    "Career & Professional",
    "Personal Growth & Learning",
    "Home & Lifestyle",
]

# Flat schema format (column_name → type string) — matches what fetch_database_schema produces
# and what the rest of the system reads via get_active_database_schema / get_column_name.
AREA_DB_FLAT_SCHEMA = {
    "Name": "title",
    "Date Logged": "date",
    "AI Executive Summary": "rich_text",
}

MASTER_PROJECTS_FLAT_SCHEMA = {
    "Project Name": "title",
    "Status": "select",
    "Target Deadline": "date",
    "Progress Bar": "number",
}

TASKS_FLAT_SCHEMA = {
    "Task Name": "title",
    "Execution Date": "date",
    "Criticality": "select",
    "Parent Project": "relation",
}

# Full Notion API property definitions used when creating databases
AREA_DB_PROPERTIES = {
    "Name": {"title": {}},
    "Date Logged": {"date": {}},
    "AI Executive Summary": {"rich_text": {}},
}

MASTER_PROJECTS_PROPERTIES = {
    "Project Name": {"title": {}},
    "Status": {
        "select": {
            "options": [
                {"name": "Proposed", "color": "gray"},
                {"name": "Active", "color": "green"},
                {"name": "Paused", "color": "yellow"},
                {"name": "Completed", "color": "blue"},
            ]
        }
    },
    "Target Deadline": {"date": {}},
    "Progress Bar": {"number": {"format": "percent"}},
}


def _headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Notion-Version": NOTION_VERSION,
    }


def _create_page(token: str) -> str:
    """Create the top-level 'Second Brain' page in the workspace."""
    response = requests.post(
        f"{NOTION_API}/pages",
        headers=_headers(token),
        json={
            "parent": {"type": "workspace", "workspace": True},
            "properties": {
                "title": {
                    "title": [{"type": "text", "text": {"content": "Second Brain"}}]
                }
            },
        },
    )
    data = response.json()
    if response.status_code != 200:
        raise Exception(f"Failed to create Second Brain page: {data}")
    return data["id"]


def _create_database(token: str, page_id: str, title: str, properties: dict) -> str:
    """Create a database as a child of page_id. Returns the new database id."""
    response = requests.post(
        f"{NOTION_API}/databases",
        headers=_headers(token),
        json={
            "parent": {"type": "page_id", "page_id": page_id},
            "title": [{"type": "text", "text": {"content": title}}],
            "properties": properties,
        },
    )
    data = response.json()
    if response.status_code != 200:
        raise Exception(f"Failed to create database '{title}': {data}")
    return data["id"]


def _area_key(name: str) -> str:
    """'Health & Fitness' → 'health_fitness'"""
    return name.lower().replace(" & ", "_").replace(" ", "_")


def setup_second_brain(chat_id: str, token: str) -> bool:
    """
    Creates the Second Brain page and 7 databases beneath it.

    On success:
      - user.json["notion"]["database_ids"]   → replaced with the 7 Second Brain databases
      - user.json["notion"]["active_database_id"] → Tasks & To Dos
      - user.json["second_brain"]             → page_id + keyed db ids

    Returns True on success, False on failure.
    """
    print(f"🧠 Setting up Second Brain for user {chat_id}...")

    # 1. Top-level page
    try:
        page_id = _create_page(token)
        print(f"✅ Second Brain page: {page_id}")
    except Exception as e:
        print(f"❌ Could not create Second Brain page: {e}")
        return False

    # Will hold {"key": db_id} for second_brain block
    keyed_db_ids = {}
    # Will hold the database_ids list in the format the rest of the system expects
    database_list = []

    # 2. Five area databases
    for area_name in AREA_DATABASES:
        try:
            db_id = _create_database(token, page_id, area_name, AREA_DB_PROPERTIES)
            keyed_db_ids[_area_key(area_name)] = db_id
            database_list.append({
                "id": db_id,
                "name": area_name,
                "type": "database",
                "schema": AREA_DB_FLAT_SCHEMA,
            })
            print(f"✅ Area DB '{area_name}': {db_id}")
        except Exception as e:
            print(f"❌ Failed to create area DB '{area_name}': {e}")
            return False

    # 3. Master Projects DB
    try:
        master_id = _create_database(token, page_id, "Master Projects DB", MASTER_PROJECTS_PROPERTIES)
        keyed_db_ids["master_projects"] = master_id
        database_list.append({
            "id": master_id,
            "name": "Master Projects DB",
            "type": "database",
            "schema": MASTER_PROJECTS_FLAT_SCHEMA,
        })
        print(f"✅ Master Projects DB: {master_id}")
    except Exception as e:
        print(f"❌ Failed to create Master Projects DB: {e}")
        return False

    # 4. Tasks & To Dos — relation to Master Projects DB
    tasks_properties = {
        "Task Name": {"title": {}},
        "Execution Date": {"date": {}},
        "Criticality": {
            "select": {
                "options": [
                    {"name": "P1 - Critical", "color": "red"},
                    {"name": "P2 - Important", "color": "yellow"},
                    {"name": "P3 - Minor", "color": "blue"},
                ]
            }
        },
        "Parent Project": {
            "relation": {"database_id": master_id}
        },
    }
    try:
        tasks_id = _create_database(token, page_id, "☑️ Tasks and To Dos", tasks_properties)
        keyed_db_ids["tasks_todos"] = tasks_id
        database_list.append({
            "id": tasks_id,
            "name": "☑️ Tasks and To Dos",
            "type": "database",
            "schema": TASKS_FLAT_SCHEMA,
        })
        print(f"✅ Tasks & To Dos DB: {tasks_id}")
    except Exception as e:
        print(f"❌ Failed to create Tasks DB: {e}")
        return False

    # 5. Write everything to user.json in one shot
    users = load_users()
    users.setdefault(str(chat_id), {})

    # Append Second Brain databases to the OAuth-discovered list
    existing = users[str(chat_id)]["notion"].get("database_ids", [])
    users[str(chat_id)]["notion"]["database_ids"] = existing + database_list
    users[str(chat_id)]["notion"]["active_database_id"] = tasks_id

    # Store keyed ids + page for easy lookup
    users[str(chat_id)]["second_brain"] = {
        "page_id": page_id,
        "databases": keyed_db_ids,
    }

    save_users(users)
    print(f"🎉 Second Brain setup complete and saved for {chat_id}")
    return True