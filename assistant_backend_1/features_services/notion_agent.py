import json
import requests
from groq import Groq
import anthropic
from assistant_backend_1.helpers import load_users, save_users
from assistant_backend_1.config import GROQ_API_KEYS, ANTHROPIC_API_KEY

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
    "Parent Task Link": "relation",
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
        timeout=30,
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
        timeout=30,
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
        timeout=30,
    )
    data = response.json()
    if response.status_code != 200:
        raise Exception(f"Failed to create database '{title}': {data}")
    return data["id"]


def _area_key(name: str) -> str:
    """'Health & Fitness' → 'health_fitness'"""
    return name.lower().replace(" & ", "_").replace(" ", "_")


def _patch_task_link(token: str, area_db_id: str, tasks_db_id: str) -> bool:
    """Add 'Parent Task Link' relation property to an existing area database."""
    response = requests.patch(
        f"{NOTION_API}/databases/{area_db_id}",
        headers=_headers(token),
        json={
            "properties": {
                "Parent Task Link": {
                    "relation": {
                        "database_id": tasks_db_id,
                        "type": "single_property",
                        "single_property": {},
                    }
                }
            }
        },
        timeout=30,
    )
    if response.status_code != 200:
        print(f"❌ Failed to patch area DB {area_db_id}: {response.json()}")
        return False
    return True


def patch_area_task_links(chat_id: str, token: str) -> bool:
    """
    Patches existing area databases with the 'Parent Task Link' relation.
    Safe to call if the relation already exists — Notion ignores duplicate property names.
    """
    users = load_users()
    second_brain = users.get(str(chat_id), {}).get("second_brain", {})
    dbs = second_brain.get("databases", {})
    tasks_id = dbs.get("tasks_todos")

    if not tasks_id:
        print("❌ tasks_todos ID not found in user.json")
        return False

    area_keys = [_area_key(name) for name, _ in AREA_DATABASES]
    success = True
    for key in area_keys:
        db_id = dbs.get(key)
        if not db_id:
            print(f"⚠️ No DB id found for area key: {key}")
            continue
        ok = _patch_task_link(token, db_id, tasks_id)
        print(f"{'✅' if ok else '❌'} Parent Task Link patch: {key}")
        if not ok:
            success = False

    # Update flat schemas in notion.database_ids
    if success:
        users[str(chat_id)].setdefault("notion", {"token": None, "active_database_id": None, "database_ids": []})
        database_ids = users[str(chat_id)]["notion"].get("database_ids", [])
        area_db_ids = set(dbs.get(k) for k in area_keys)
        for db in database_ids:
            if db["id"] in area_db_ids:
                db["schema"]["Parent Task Link"] = "relation"
        users[str(chat_id)]["notion"]["database_ids"] = database_ids
        save_users(users)
        print("✅ user.json schemas updated with Parent Task Link")

    return success


def _page_exists(token: str, page_id: str) -> bool:
    """Check whether a Notion page still exists and is accessible."""
    response = requests.get(
        f"{NOTION_API}/pages/{page_id}",
        headers=_headers(token),
        timeout=30,
    )
    data = response.json()
    return response.status_code == 200 and not data.get("archived", False)


def _get_notion_title(obj: dict) -> str:
    """Extract plain text title from a Notion page or database search result."""
    if obj.get("object") == "database":
        title_list = obj.get("title", [])
        return title_list[0].get("plain_text", "").strip() if title_list else ""
    else:
        for prop in obj.get("properties", {}).values():
            if prop.get("type") == "title":
                title_list = prop.get("title", [])
                return title_list[0].get("plain_text", "").strip() if title_list else ""
    return ""


def _notion_search(token: str, query: str, filter_type: str) -> list:
    response = requests.post(
        f"{NOTION_API}/search",
        headers=_headers(token),
        json={"query": query, "filter": {"property": "object", "value": filter_type}},
        timeout=30,
    )
    return response.json().get("results", [])


def _find_by_title(results: list, title: str) -> str | None:
    for r in results:
        if not r.get("archived", False) and _get_notion_title(r) == title:
            return r["id"]
    return None


def _search_notion_for_second_brain(token: str) -> dict | None:
    """
    Search Notion for an existing Second Brain page and its databases.
    Returns a reconstruction dict on success, None if not found.
    """
    root_id = _find_by_title(_notion_search(token, "Second Brain", "page"), "Second Brain")
    if not root_id:
        return None

    print(f"🔍 Found existing Second Brain page: {root_id}")

    areas_page_id = _find_by_title(_notion_search(token, "Areas Boards", "page"), "Areas Boards")
    projects_page_id = _find_by_title(_notion_search(token, "Project Directory", "page"), "Project Directory")

    keyed_db_ids = {}
    for name, _ in AREA_DATABASES:
        db_id = _find_by_title(_notion_search(token, name, "database"), name)
        if db_id:
            keyed_db_ids[_area_key(name)] = db_id

    master_id = _find_by_title(_notion_search(token, "Master Projects DB", "database"), "Master Projects DB")
    if master_id:
        keyed_db_ids["master_projects"] = master_id

    tasks_id = _find_by_title(_notion_search(token, "Tasks and To Dos", "database"), "Tasks and To Dos")
    if tasks_id:
        keyed_db_ids["tasks_todos"] = tasks_id

    return {
        "root_id": root_id,
        "areas_page_id": areas_page_id,
        "projects_page_id": projects_page_id,
        "keyed_db_ids": keyed_db_ids,
    }


def setup_second_brain(chat_id: str, token: str) -> str:
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

    Returns:
      "created"  — freshly built and saved
      "exists"   — already set up, skipped
      "failed"   — something went wrong
    """
    print(f"🧠 Setting up Second Brain for user {chat_id}...")

    # ── 0a. Fast path: check user.json ───────────────────────────────
    users = load_users()
    existing = users.get(str(chat_id), {}).get("second_brain", {})
    if existing.get("page_id") and _page_exists(token, existing["page_id"]):
        # Refresh token in user.json so it stays in sync with Postgres
        users.setdefault(str(chat_id), {})
        users[str(chat_id)].setdefault("notion", {"token": token, "active_database_id": None, "database_ids": []})
        users[str(chat_id)]["notion"]["token"] = token
        save_users(users)
        print(f"ℹ️ Second Brain already recorded in user.json for {chat_id}, skipping.")
        return "exists"

    # ── 0b. Search Notion for an existing Second Brain page ──────────
    found = _search_notion_for_second_brain(token)
    if found:
        print(f"ℹ️ Existing Second Brain found in Notion — reconstructing user.json...")
        keyed_db_ids = found["keyed_db_ids"]

        # Build Second Brain database list
        sb_database_list = []
        for name, _ in AREA_DATABASES:
            key = _area_key(name)
            if key in keyed_db_ids:
                sb_database_list.append({"id": keyed_db_ids[key], "name": name, "type": "database", "schema": AREA_DB_FLAT_SCHEMA})
        if "master_projects" in keyed_db_ids:
            sb_database_list.append({"id": keyed_db_ids["master_projects"], "name": "Master Projects DB", "type": "database", "schema": MASTER_PROJECTS_FLAT_SCHEMA})
        if "tasks_todos" in keyed_db_ids:
            sb_database_list.append({"id": keyed_db_ids["tasks_todos"], "name": "Tasks and To Dos", "type": "database", "schema": TASKS_FLAT_SCHEMA})

        # Merge with existing OAuth database list (avoid duplicates)
        users.setdefault(str(chat_id), {})
        users[str(chat_id)].setdefault("notion", {
            "token": token,
            "active_database_id": None,
            "database_ids": []
        })
        existing_list = users[str(chat_id)]["notion"].get("database_ids", [])
        existing_ids = {db["id"] for db in existing_list}
        merged = existing_list + [db for db in sb_database_list if db["id"] not in existing_ids]

        users[str(chat_id)]["notion"]["database_ids"] = merged
        users[str(chat_id)]["notion"]["active_database_id"] = keyed_db_ids.get("tasks_todos")
        users[str(chat_id)]["second_brain"] = {
            "page_id": found["root_id"],
            "areas_page_id": found["areas_page_id"],
            "projects_page_id": found["projects_page_id"],
            "databases": keyed_db_ids,
        }
        save_users(users)
        print(f"✅ user.json reconstructed from existing Notion Second Brain for {chat_id}")
        return "exists"

    # ── 1. Root page ─────────────────────────────────────────────────
    try:
        root_id = _create_root_page(token, "Second Brain", "🧠")
        print(f"✅ Second Brain page: {root_id}")
    except Exception as e:
        print(f"❌ {e}")
        return "failed"

    keyed_db_ids = {}
    database_list = []

    # ── 2. Areas Boards sub-page + 5 area databases ───────────────────
    try:
        areas_page_id = _create_child_page(token, root_id, "Areas Boards", "🗂️")
        print(f"✅ Areas Boards page: {areas_page_id}")
    except Exception as e:
        print(f"❌ {e}")
        return "failed"

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
            return "failed"

    # ── 3. Project Directory sub-page + Master Projects DB ───────────
    try:
        projects_page_id = _create_child_page(token, root_id, "Project Directory", "🚀")
        print(f"✅ Project Directory page: {projects_page_id}")
    except Exception as e:
        print(f"❌ {e}")
        return "failed"

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
        return "failed"

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
        return "failed"

    # ── 5. Patch area DBs with Parent Task Link → Tasks & To Dos ─────
    area_db_ids_list = [keyed_db_ids[_area_key(name)] for name, _ in AREA_DATABASES]
    for area_db_id in area_db_ids_list:
        ok = _patch_task_link(token, area_db_id, tasks_id)
        print(f"{'✅' if ok else '❌'} Parent Task Link patch: {area_db_id}")

    # ── 6. Update user.json ──────────────────────────────────────────
    users = load_users()
    users.setdefault(str(chat_id), {})
    users[str(chat_id)].setdefault("notion", {
        "token": token,
        "active_database_id": None,
        "database_ids": []
    })

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
    return "created"


# =====================================================================
# TASK MOVING AGENT
# =====================================================================

AREA_NAME_TO_KEY = {
    "Health & Fitness":           "health_fitness",
    "Finance & Wealth":           "finance_wealth",
    "Career & Professional":      "career_professional",
    "Personal Growth & Learning": "personal_growth_learning",
    "Home & Lifestyle":           "home_lifestyle",
}

_TASK_AGENT_PROMPT = """You are a Second Brain task organization agent.

You will receive a JSON list of tasks (each with an id and title).
Your job is to:

1. AREA CATEGORIZATION — assign each task to one of these areas (or null if unclear):
   - "Health & Fitness": health, medical, exercise, diet, mental health, wellness, doctor, gym
   - "Finance & Wealth": money, bills, payments, investments, banking, budget, salary, tax, expenses
   - "Career & Professional": work, job, meetings, deadlines, clients, presentations, professional development
   - "Personal Growth & Learning": learning, books, courses, skills, self-improvement, studying, reading
   - "Home & Lifestyle": home, household, cleaning, repairs, groceries, errands, family, shopping, cooking, furniture

2. PROJECT DETECTION — identify groups of 2 or more tasks that together form a larger project.
   Only create a project when you are confident multiple tasks clearly share one overarching goal.
   Name projects concisely with the current year (e.g. "Home Renovation 2026", "Job Search 2026").

Return ONLY valid JSON — no markdown, no explanation:
{
  "task_categorizations": [
    {
      "task_id": "<notion_page_id>",
      "task_title": "<task title>",
      "area": "<area name or null>",
      "ai_summary": "<one sentence describing this task in context of the area>"
    }
  ],
  "projects": [
    {
      "name": "<Project Name Year>",
      "status": "Proposed",
      "task_ids": ["<task_page_id>", "<task_page_id>"]
    }
  ]
}"""


def _fetch_tasks(token: str, tasks_db_id: str) -> list:
    """Fetch all non-archived tasks from the Tasks & To Dos database (handles pagination)."""
    tasks = []
    payload = {}
    while True:
        response = requests.post(
            f"{NOTION_API}/databases/{tasks_db_id}/query",
            headers=_headers(token),
            json=payload,
            timeout=30,
        )
        data = response.json()
        for r in data.get("results", []):
            if r.get("archived"):
                continue
            props = r.get("properties", {})
            title = ""
            for prop_data in props.values():
                if prop_data.get("type") == "title":
                    tl = prop_data.get("title", [])
                    title = tl[0].get("plain_text", "").strip() if tl else ""
                    break
            tasks.append({"id": r["id"], "title": title})
        if data.get("has_more"):
            payload["start_cursor"] = data["next_cursor"]
        else:
            break
    return tasks


def _call_task_agent(tasks: list) -> dict | None:
    """
    Send tasks to Groq (with Claude fallback) for area categorization and project detection.
    Returns parsed JSON dict or None on failure.
    """
    user_prompt = f"Analyze these tasks and return the JSON:\n{json.dumps(tasks, indent=2)}"
    raw = None

    # Try Groq keys
    for api_key in GROQ_API_KEYS:
        try:
            client = Groq(api_key=api_key)
            response = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                response_format={"type": "json_object"},
                temperature=0,
                max_tokens=2048,
                messages=[
                    {"role": "system", "content": _TASK_AGENT_PROMPT},
                    {"role": "user",   "content": user_prompt},
                ],
            )
            raw = response.choices[0].message.content
            print("[TaskAgent] Groq succeeded.")
            break
        except Exception as e:
            print(f"[TaskAgent] Groq key failed: {e}")
            continue

    # Claude fallback
    if raw is None:
        try:
            if not ANTHROPIC_API_KEY:
                raise Exception("ANTHROPIC_API_KEY not set.")
            client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
            resp = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=2048,
                temperature=0,
                system=_TASK_AGENT_PROMPT,
                messages=[{"role": "user", "content": user_prompt}],
            )
            raw = resp.content[0].text
            print("[TaskAgent] Claude fallback succeeded.")
        except Exception as e:
            print(f"[TaskAgent] Claude fallback failed: {e}")
            return None

    try:
        # Strip markdown code fences Claude sometimes adds despite instructions
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("```", 2)[1]
            if cleaned.startswith("json"):
                cleaned = cleaned[4:]
            cleaned = cleaned.rsplit("```", 1)[0].strip()
        return json.loads(cleaned)
    except Exception as e:
        print(f"[TaskAgent] JSON parse error: {e}")
        print(f"[TaskAgent] Raw response was: {repr(raw)}")
        return None


def _create_area_entry(token: str, area_db_id: str, task: dict, ai_summary: str) -> str | None:
    """Create an entry in an area database linked back to the original task."""
    response = requests.post(
        f"{NOTION_API}/pages",
        headers=_headers(token),
        json={
            "parent": {"database_id": area_db_id},
            "properties": {
                "Name": {
                    "title": [{"text": {"content": task["title"]}}]
                },
                "AI Executive Summary": {
                    "rich_text": [{"text": {"content": ai_summary}}]
                },
                "Parent Task Link": {
                    "relation": [{"id": task["id"]}]
                },
            },
        },
        timeout=30,
    )
    if response.status_code == 200:
        return response.json()["id"]
    print(f"❌ Failed to create area entry: {response.text}")
    return None


def _create_project_entry(token: str, master_db_id: str, project: dict) -> str | None:
    """Create a project entry in Master Projects DB."""
    response = requests.post(
        f"{NOTION_API}/pages",
        headers=_headers(token),
        json={
            "parent": {"database_id": master_db_id},
            "properties": {
                "Project Name": {
                    "title": [{"text": {"content": project["name"]}}]
                },
                "Status": {
                    "select": {"name": project.get("status", "Proposed")}
                },
            },
        },
        timeout=30,
    )
    if response.status_code == 200:
        return response.json()["id"]
    print(f"❌ Failed to create project entry: {response.text}")
    return None


def _link_task_to_project(token: str, task_id: str, project_page_id: str):
    """Patch a task's Parent Project relation to point to a project page."""
    response = requests.patch(
        f"{NOTION_API}/pages/{task_id}",
        headers=_headers(token),
        json={
            "properties": {
                "Parent Project": {
                    "relation": [{"id": project_page_id}]
                }
            }
        },
        timeout=30,
    )
    if response.status_code != 200:
        print(f"❌ Failed to link task {task_id} to project: {response.text}")


def run_notion_task_moving(chat_id: str, token: str) -> bool:
    """
    AI-powered task organisation agent.

    1. Fetches all tasks from Tasks & To Dos DB.
    2. Sends them to Groq (Claude fallback) for area categorization + project detection.
    3. Creates entries in the relevant area board databases with Parent Task Link.
    4. Creates project entries in Master Projects DB and links related tasks via Parent Project.

    Tasks remain in the Tasks & To Dos database — area entries are reference copies.
    Returns True on success, False on failure.
    """
    users = load_users()
    second_brain = users.get(str(chat_id), {}).get("second_brain", {})
    dbs = second_brain.get("databases", {})

    tasks_db_id   = dbs.get("tasks_todos")
    master_db_id  = dbs.get("master_projects")

    if not tasks_db_id or not master_db_id:
        print("❌ Second Brain databases not found in user.json. Run setup first.")
        return False

    # ── 1. Fetch tasks ────────────────────────────────────────────────
    tasks = _fetch_tasks(token, tasks_db_id)
    if not tasks:
        print("ℹ️ No tasks found in Tasks & To Dos.")
        return True

    print(f"📋 Fetched {len(tasks)} tasks for analysis.")

    # ── 2. LLM analysis ──────────────────────────────────────────────
    result = _call_task_agent(tasks)
    if not result:
        print("❌ Task agent returned no result.")
        return False

    # ── 3. Create area entries ────────────────────────────────────────
    categorizations = result.get("task_categorizations", [])
    task_map = {t["id"]: t for t in tasks}

    for item in categorizations:
        area = item.get("area")
        task_id = item.get("task_id")
        ai_summary = item.get("ai_summary", "")

        if not area or area not in AREA_NAME_TO_KEY:
            continue

        area_key = AREA_NAME_TO_KEY[area]
        area_db_id = dbs.get(area_key)
        if not area_db_id:
            print(f"⚠️ No DB id for area '{area}' in user.json")
            continue

        task = task_map.get(task_id)
        if not task:
            continue

        entry_id = _create_area_entry(token, area_db_id, task, ai_summary)
        if entry_id:
            print(f"✅ Area entry created: '{task['title']}' → {area}")

    # ── 4. Create projects + link tasks ──────────────────────────────
    for project in result.get("projects", []):
        project_page_id = _create_project_entry(token, master_db_id, project)
        if not project_page_id:
            continue

        print(f"✅ Project created: '{project['name']}'")

        for task_id in project.get("task_ids", []):
            _link_task_to_project(token, task_id, project_page_id)
            task = task_map.get(task_id, {})
            print(f"   🔗 Linked task: '{task.get('title', task_id)}'")

    print("🎉 Task moving agent complete.")
    return True