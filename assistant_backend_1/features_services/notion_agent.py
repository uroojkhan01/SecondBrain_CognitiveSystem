import requests
from assistant_backend_1.helpers import load_users, save_users

NOTION_API = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"

# Area databases: (display name, emoji, flat-schema key)
AREA_DATABASES = [
    ("Health & Fitness",           "💪"),
    ("Finance & Wealth",           "💰"),
    ("Career & Professional",      "💼"),
    ("Personal Growth & Learning", "🌱"),
    ("Home & Lifestyle",           "🏠"),
]

# Flat schema format (column_name → type string) used by get_active_database_schema / get_column_name
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

# Full Notion API property definitions
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
                {"name": "Proposed",  "color": "gray"},
                {"name": "Active",    "color": "green"},
                {"name": "Paused",    "color": "yellow"},
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


def _create_root_page(token: str, title: str, emoji: str) -> str:
    """Create a top-level page in the workspace."""
    response = requests.post(
        f"{NOTION_API}/pages",
        headers=_headers(token),
        json={
            "parent": {"type": "workspace", "workspace": True},
            "icon": {"type": "emoji", "emoji": emoji},
            "properties": {
                "title": {
                    "title": [{"type": "text", "text": {"content": title}}]
                }
            },
        },
    )
    data = response.json()
    if response.status_code != 200:
        raise Exception(f"Failed to create root page '{title}': {data}")
    return data["id"]


def _create_child_page(token: str, parent_page_id: str, title: str, emoji: str) -> str:
    """Create a sub-page under an existing page."""
    response = requests.post(
        f"{NOTION_API}/pages",
        headers=_headers(token),
        json={
            "parent": {"type": "page_id", "page_id": parent_page_id},
            "icon": {"type": "emoji", "emoji": emoji},
            "properties": {
                "title": {
                    "title": [{"type": "text", "text": {"content": title}}]
                }
            },
        },
    )
    data = response.json()
    if response.status_code != 200:
        raise Exception(f"Failed to create child page '{title}': {data}")
    return data["id"]


def _create_database(token: str, parent_page_id: str, title: str, emoji: str, properties: dict) -> str:
    """Create a database under a page."""
    response = requests.post(
        f"{NOTION_API}/databases",
        headers=_headers(token),
        json={
            "parent": {"type": "page_id", "page_id": parent_page_id},
            "icon": {"type": "emoji", "emoji": emoji},
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
    Creates the full Second Brain structure in Notion:

      🧠 Second Brain  (workspace root page)
      ├── 🗂️ Areas Boards  (sub-page)
      │   ├── 💪 Health & Fitness        (database)
      │   ├── 💰 Finance & Wealth        (database)
      │   ├── 💼 Career & Professional   (database)
      │   ├── 🌱 Personal Growth & Learning (database)
      │   └── 🏠 Home & Lifestyle        (database)
      ├── 🚀 Project Directory  (sub-page)
      │   └── 📋 Master Projects DB      (database)
      └── ✅ Tasks and To Dos            (database)

    On success appends all 7 databases to notion.database_ids, sets
    active_database_id → Tasks & To Dos, and writes second_brain block.

    Returns True on success, False on failure.
    """
    print(f"🧠 Setting up Second Brain for user {chat_id}...")

    # ── 1. Root page ─────────────────────────────────────────────────
    try:
        root_id = _create_root_page(token, "Second Brain", "🧠")
        print(f"✅ Second Brain page: {root_id}")
    except Exception as e:
        print(f"❌ {e}")
        return False

    keyed_db_ids = {}
    database_list = []

    # ── 2. Areas Boards sub-page + 5 area databases ───────────────────
    try:
        areas_page_id = _create_child_page(token, root_id, "Areas Boards", "🗂️")
        print(f"✅ Areas Boards page: {areas_page_id}")
    except Exception as e:
        print(f"❌ {e}")
        return False

    for area_name, emoji in AREA_DATABASES:
        try:
            db_id = _create_database(token, areas_page_id, area_name, emoji, AREA_DB_PROPERTIES)
            keyed_db_ids[_area_key(area_name)] = db_id
            database_list.append({
                "id": db_id,
                "name": area_name,
                "type": "database",
                "schema": AREA_DB_FLAT_SCHEMA,
            })
            print(f"✅ Area DB '{area_name}': {db_id}")
        except Exception as e:
            print(f"❌ {e}")
            return False

    # ── 3. Project Directory sub-page + Master Projects DB ───────────
    try:
        projects_page_id = _create_child_page(token, root_id, "Project Directory", "🚀")
        print(f"✅ Project Directory page: {projects_page_id}")
    except Exception as e:
        print(f"❌ {e}")
        return False

    try:
        master_id = _create_database(
            token, projects_page_id, "Master Projects DB", "📋", MASTER_PROJECTS_PROPERTIES
        )
        keyed_db_ids["master_projects"] = master_id
        database_list.append({
            "id": master_id,
            "name": "Master Projects DB",
            "type": "database",
            "schema": MASTER_PROJECTS_FLAT_SCHEMA,
        })
        print(f"✅ Master Projects DB: {master_id}")
    except Exception as e:
        print(f"❌ {e}")
        return False

    # ── 4. Tasks & To Dos (directly under root, relation → Master Projects) ──
    tasks_properties = {
        "Task Name": {"title": {}},
        "Execution Date": {"date": {}},
        "Criticality": {
            "select": {
                "options": [
                    {"name": "P1 - Critical",  "color": "red"},
                    {"name": "P2 - Important", "color": "yellow"},
                    {"name": "P3 - Minor",     "color": "blue"},
                ]
            }
        },
        "Parent Project": {
            "relation": {
                "database_id": master_id,
                "type": "single_property",
                "single_property": {},
            }
        },
    }
    try:
        tasks_id = _create_database(token, root_id, "Tasks and To Dos", "✅", tasks_properties)
        keyed_db_ids["tasks_todos"] = tasks_id
        database_list.append({
            "id": tasks_id,
            "name": "Tasks and To Dos",
            "type": "database",
            "schema": TASKS_FLAT_SCHEMA,
        })
        print(f"✅ Tasks & To Dos DB: {tasks_id}")
    except Exception as e:
        print(f"❌ {e}")
        return False

    # ── 5. Update user.json ──────────────────────────────────────────
    users = load_users()
    users.setdefault(str(chat_id), {})

    existing = users[str(chat_id)]["notion"].get("database_ids", [])
    users[str(chat_id)]["notion"]["database_ids"] = existing + database_list
    users[str(chat_id)]["notion"]["active_database_id"] = tasks_id
    users[str(chat_id)]["second_brain"] = {
        "page_id": root_id,
        "areas_page_id": areas_page_id,
        "projects_page_id": projects_page_id,
        "databases": keyed_db_ids,
    }

    save_users(users)
    print(f"🎉 Second Brain setup complete for {chat_id}")
    return True