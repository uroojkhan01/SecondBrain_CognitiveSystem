import json
from datetime import date
import requests
from groq import Groq
import anthropic
from assistant_backend_1.helpers import load_users, save_users
from assistant_backend_1.config import GROQ_API_KEYS, ANTHROPIC_API_KEY
from assistant_backend_1.features_services.notion_schema import (
    AREA_DATABASES, AREA_NAME_TO_KEY,
    AREA_DB_FLAT_SCHEMA, MASTER_PROJECTS_FLAT_SCHEMA, TASKS_FLAT_SCHEMA,
    AREA_DB_PROPERTIES, MASTER_PROJECTS_PROPERTIES,
    TASK_AGENT_PROMPT,
)

NOTION_API = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"


# ── Telegram helper ───────────────────────────────────────────────────────────

def _notify_telegram(chat_id: str, message: str):
    """Send a Telegram message from within notion_agent (no async context needed)."""
    from assistant_backend_1.config import TELEGRAM_BOT_TOKEN
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={"chat_id": chat_id, "text": message, "parse_mode": "Markdown"},
            timeout=10,
        )
    except Exception as e:
        print(f"❌ Telegram notify failed: {e}")


# ── Notion API primitives ──────────────────────────────────────────────────────

def _headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Notion-Version": NOTION_VERSION,
    }


def _area_key(name: str) -> str:
    return name.lower().replace(" & ", "_").replace(" ", "_")


def _create_root_page(token: str, title: str, emoji: str) -> str:
    response = requests.post(
        f"{NOTION_API}/pages",
        headers=_headers(token),
        json={
            "parent": {"type": "workspace", "workspace": True},
            "icon": {"type": "emoji", "emoji": emoji},
            "properties": {
                "title": {"title": [{"type": "text", "text": {"content": title}}]}
            },
        },
        timeout=30,
    )
    data = response.json()
    if response.status_code != 200:
        raise Exception(f"Failed to create root page '{title}': {data}")
    return data["id"]


def _create_child_page(token: str, parent_page_id: str, title: str, emoji: str) -> str:
    response = requests.post(
        f"{NOTION_API}/pages",
        headers=_headers(token),
        json={
            "parent": {"type": "page_id", "page_id": parent_page_id},
            "icon": {"type": "emoji", "emoji": emoji},
            "properties": {
                "title": {"title": [{"type": "text", "text": {"content": title}}]}
            },
        },
        timeout=30,
    )
    data = response.json()
    if response.status_code != 200:
        raise Exception(f"Failed to create child page '{title}': {data}")
    return data["id"]


def _create_database(token: str, parent_page_id: str, title: str, emoji: str, properties: dict) -> str:
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


# ── Existence checks ───────────────────────────────────────────────────────────

def _db_exists(token: str, db_id: str) -> bool:
    r = requests.get(f"{NOTION_API}/databases/{db_id}", headers=_headers(token), timeout=30)
    data = r.json()
    return r.status_code == 200 and not data.get("archived", False)


def _page_exists(token: str, page_id: str) -> bool:
    r = requests.get(f"{NOTION_API}/pages/{page_id}", headers=_headers(token), timeout=30)
    data = r.json()
    return r.status_code == 200 and not data.get("archived", False)


# ── Schema patching ────────────────────────────────────────────────────────────

def _patch_task_link(token: str, area_db_id: str, tasks_db_id: str) -> bool:
    """Add 'Parent Task Link' relation to an existing area database."""
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
    Patches all existing area databases with the 'Parent Task Link' relation.
    Safe to call multiple times — Notion ignores duplicate property names.
    """
    users = load_users()
    dbs = users.get(str(chat_id), {}).get("second_brain", {}).get("databases", {})
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

    if success:
        users[str(chat_id)].setdefault(
            "notion", {"token": None, "active_database_id": None, "database_ids": []})
        database_ids = users[str(chat_id)]["notion"].get("database_ids", [])
        area_db_ids = set(dbs.get(k) for k in area_keys)
        for db in database_ids:
            if db["id"] in area_db_ids:
                db["schema"]["Parent Task Link"] = "relation"
        users[str(chat_id)]["notion"]["database_ids"] = database_ids
        save_users(users)
        print("✅ user.json schemas updated with Parent Task Link")

    return success


def patch_missing_area_dbs(chat_id: str, token: str) -> bool:
    """
    Creates any area databases that exist in AREA_DATABASES but are missing
    from Notion. Safe to call on every /organize run — skips areas that
    already exist and are accessible. Handles the case where a DB was deleted
    from Notion but its ID is still in user.json.
    """
    users = load_users()
    second_brain = users.get(str(chat_id), {}).get("second_brain", {})
    dbs = second_brain.get("databases", {})

    areas_page_id = second_brain.get("areas_page_id")
    tasks_db_id = dbs.get("tasks_todos")

    if not areas_page_id:
        print("❌ patch_missing_area_dbs: areas_page_id not found in user.json")
        return False

    added_any = False
    for area_name, emoji in AREA_DATABASES:
        key = _area_key(area_name)
        existing_id = dbs.get(key)
        if existing_id and _db_exists(token, existing_id):
            continue  # already exists and is accessible in Notion

        print(f"➕ Creating missing area DB: '{area_name}'")
        try:
            db_id = _create_database(token, areas_page_id, area_name, emoji, AREA_DB_PROPERTIES)
        except Exception as e:
            print(f"❌ Failed to create '{area_name}': {e}")
            return False

        if tasks_db_id:
            ok = _patch_task_link(token, db_id, tasks_db_id)
            print(f"{'✅' if ok else '❌'} Parent Task Link patch: {area_name}")

        users[str(chat_id)]["second_brain"]["databases"][key] = db_id

        notion = users[str(chat_id)].setdefault("notion", {
            "token": token, "active_database_id": None, "database_ids": []
        })
        schema = dict(AREA_DB_FLAT_SCHEMA)
        if tasks_db_id:
            schema["Parent Task Link"] = "relation"
        notion["database_ids"].append({
            "id": db_id, "name": area_name, "type": "database", "schema": schema,
        })

        print(f"✅ Area DB created and saved: '{area_name}' ({db_id})")
        added_any = True

    if added_any:
        save_users(users)
        print("✅ user.json updated with new area databases")
    else:
        print("ℹ️ All area databases already exist — nothing to create")

    return True


def patch_master_projects_schema(token: str, master_db_id: str) -> bool:
    """Ensure Master Projects DB has all required properties (idempotent — Notion ignores duplicates)."""
    r = requests.patch(
        f"{NOTION_API}/databases/{master_db_id}",
        headers=_headers(token),
        json={"properties": {
            "Progress Bar": {"number": {"format": "bar"}},
            "Created Date":  {"date": {}},
            "Comments":      {"rich_text": {}},
        }},
        timeout=30,
    )
    if r.status_code != 200:
        print(f"❌ Failed to patch Master Projects schema: {r.json()}")
        return False
    print("✅ Master Projects schema up to date")
    return True


def patch_tasks_organized_field(token: str, tasks_db_id: str) -> bool:
    """Add the 'Organized' checkbox to the Tasks & To Dos database."""
    response = requests.patch(
        f"{NOTION_API}/databases/{tasks_db_id}",
        headers=_headers(token),
        json={"properties": {"Organized": {"checkbox": {}}}},
        timeout=30,
    )
    if response.status_code == 200:
        print("✅ 'Organized' checkbox added to Tasks & To Dos DB")
        return True
    print(f"❌ Failed to patch Tasks DB with Organized field: {response.json()}")
    return False


def patch_done_and_rollups(token: str, tasks_db_id: str, master_db_id: str) -> bool:
    """
    Adds the Done checkbox to the Tasks DB.
    Safe to call on every run — Notion ignores already-existing properties.
    """
    r = requests.patch(
        f"{NOTION_API}/databases/{tasks_db_id}",
        headers=_headers(token),
        json={"properties": {"Done": {"checkbox": {}}}},
        timeout=30,
    )
    if r.status_code != 200:
        print(f"❌ Failed to add Done field: {r.json()}")
        return False
    print("✅ Done checkbox ready on Tasks DB")
    return True


# ── Setup / discovery ──────────────────────────────────────────────────────────

def _get_notion_title(obj: dict) -> str:
    if obj.get("object") == "database":
        title_list = obj.get("title", [])
        return title_list[0].get("plain_text", "").strip() if title_list else ""
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
    """Search Notion for an existing Second Brain and return its structure, or None."""
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
      │   ├── 💪 Health & Fitness
      │   ├── 💰 Finance & Wealth
      │   ├── 💼 Career & Professional
      │   ├── 🌱 Personal Growth & Learning
      │   ├── 🏠 Home & Lifestyle
      │   └── 🤝 Family & Friends
      ├── 🚀 Project Directory  (sub-page)
      │   └── 📋 Master Projects DB
      └── ✅ Tasks and To Dos

    Returns "created", "exists", or "failed".
    """
    print(f"🧠 Setting up Second Brain for user {chat_id}...")

    # ── 0a. Fast path: already recorded in user.json ─────────────────
    users = load_users()
    existing = users.get(str(chat_id), {}).get("second_brain", {})
    if existing.get("page_id") and _page_exists(token, existing["page_id"]):
        users.setdefault(str(chat_id), {})
        users[str(chat_id)].setdefault(
            "notion", {"token": token, "active_database_id": None, "database_ids": []})
        users[str(chat_id)]["notion"]["token"] = token
        save_users(users)
        print(f"ℹ️ Second Brain already recorded in user.json for {chat_id}, skipping.")
        patch_missing_area_dbs(chat_id, token)
        return "exists"

    # ── 0b. Search Notion for an existing Second Brain ────────────────
    found = _search_notion_for_second_brain(token)
    if found:
        print(f"ℹ️ Existing Second Brain found in Notion — reconstructing user.json...")
        keyed_db_ids = found["keyed_db_ids"]

        sb_database_list = []
        for name, _ in AREA_DATABASES:
            key = _area_key(name)
            if key in keyed_db_ids:
                sb_database_list.append({
                    "id": keyed_db_ids[key], "name": name,
                    "type": "database", "schema": AREA_DB_FLAT_SCHEMA,
                })
        if "master_projects" in keyed_db_ids:
            sb_database_list.append({
                "id": keyed_db_ids["master_projects"], "name": "Master Projects DB",
                "type": "database", "schema": MASTER_PROJECTS_FLAT_SCHEMA,
            })
        if "tasks_todos" in keyed_db_ids:
            sb_database_list.append({
                "id": keyed_db_ids["tasks_todos"], "name": "Tasks and To Dos",
                "type": "database", "schema": TASKS_FLAT_SCHEMA,
            })

        users.setdefault(str(chat_id), {})
        users[str(chat_id)].setdefault("notion", {
            "token": token, "active_database_id": None, "database_ids": []
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

    # ── 1. Root page ──────────────────────────────────────────────────
    try:
        root_id = _create_root_page(token, "Second Brain", "🧠")
        print(f"✅ Second Brain page: {root_id}")
    except Exception as e:
        print(f"❌ {e}")
        return "failed"

    keyed_db_ids = {}
    database_list = []

    # ── 2. Areas Boards sub-page + area databases ─────────────────────
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
                "id": db_id, "name": area_name,
                "type": "database", "schema": AREA_DB_FLAT_SCHEMA,
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
            token, projects_page_id, "Master Projects DB", "📋", MASTER_PROJECTS_PROPERTIES)
        keyed_db_ids["master_projects"] = master_id
        database_list.append({
            "id": master_id, "name": "Master Projects DB",
            "type": "database", "schema": MASTER_PROJECTS_FLAT_SCHEMA,
        })
        print(f"✅ Master Projects DB: {master_id}")
    except Exception as e:
        print(f"❌ {e}")
        return "failed"

    # ── 4. Tasks & To Dos (relation → Master Projects) ────────────────
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
        "Organized": {"checkbox": {}},
        "Done": {"checkbox": {}},
    }
    try:
        tasks_id = _create_database(token, root_id, "Tasks and To Dos", "✅", tasks_properties)
        keyed_db_ids["tasks_todos"] = tasks_id
        database_list.append({
            "id": tasks_id, "name": "Tasks and To Dos",
            "type": "database", "schema": TASKS_FLAT_SCHEMA,
        })
        print(f"✅ Tasks & To Dos DB: {tasks_id}")
    except Exception as e:
        print(f"❌ {e}")
        return "failed"

    # ── 5. Patch area DBs with Parent Task Link → Tasks & To Dos ─────
    for area_name, _ in AREA_DATABASES:
        area_db_id = keyed_db_ids[_area_key(area_name)]
        ok = _patch_task_link(token, area_db_id, tasks_id)
        print(f"{'✅' if ok else '❌'} Parent Task Link patch: {area_name}")

    # ── 6. Save to user.json ──────────────────────────────────────────
    users = load_users()
    users.setdefault(str(chat_id), {})
    users[str(chat_id)].setdefault("notion", {
        "token": token, "active_database_id": None, "database_ids": []
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


# ── Task moving agent ──────────────────────────────────────────────────────────

def _fetch_tasks(token: str, tasks_db_id: str) -> list:
    """Fetch all unorganized, non-archived tasks from the Tasks & To Dos database."""
    tasks = []
    payload = {"filter": {"property": "Organized", "checkbox": {"equals": False}}}
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


def _fetch_existing_projects(token: str, master_db_id: str) -> list:
    """Return list of {name, page_id} dicts from Master Projects DB."""
    try:
        r = requests.post(
            f"{NOTION_API}/databases/{master_db_id}/query",
            headers=_headers(token),
            json={},
            timeout=30,
        )
        names = []
        for page in r.json().get("results", []):
            props = page.get("properties", {})
            for prop in props.values():
                if prop.get("type") == "title":
                    title_parts = prop.get("title", [])
                    name = "".join(t.get("plain_text", "") for t in title_parts).strip()
                    if name:
                        names.append({"name": name, "page_id": page["id"]})
                    break
        return names
    except Exception as e:
        print(f"⚠️ Could not fetch existing projects: {e}")
        return []


def _call_task_agent(tasks: list, existing_projects: list = None) -> dict | None:
    """Send tasks to Groq (Claude fallback) for area + project categorization."""
    payload = {
        "tasks": tasks,
        "existing_projects": [p["name"] for p in (existing_projects or [])]
    }
    user_prompt = f"Analyse these tasks and return the JSON:\n{json.dumps(payload, indent=2)}"
    raw = None

    for api_key in GROQ_API_KEYS:
        try:
            client = Groq(api_key=api_key)
            response = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                response_format={"type": "json_object"},
                temperature=0,
                max_tokens=2048,
                messages=[
                    {"role": "system", "content": TASK_AGENT_PROMPT},
                    {"role": "user",   "content": user_prompt},
                ],
            )
            raw = response.choices[0].message.content
            print("[TaskAgent] Groq succeeded.")
            break
        except Exception as e:
            print(f"[TaskAgent] Groq key failed: {e}")
            continue

    if raw is None:
        try:
            if not ANTHROPIC_API_KEY:
                raise Exception("ANTHROPIC_API_KEY not set.")
            client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
            resp = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=2048,
                temperature=0,
                system=TASK_AGENT_PROMPT,
                messages=[{"role": "user", "content": user_prompt}],
            )
            raw = resp.content[0].text
            print("[TaskAgent] Claude fallback succeeded.")
        except Exception as e:
            print(f"[TaskAgent] Claude fallback failed: {e}")
            return None

    try:
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
                "Name":                 {"title": [{"text": {"content": task["title"]}}]},
                "Date Logged":          {"date": {"start": date.today().isoformat()}},
                "AI Executive Summary": {"rich_text": [{"text": {"content": ai_summary}}]},
                "Parent Task Link":     {"relation": [{"id": task["id"]}]},
            },
        },
        timeout=30,
    )
    if response.status_code == 200:
        return response.json()["id"]
    print(f"❌ Failed to create area entry: {response.text}")
    return None


def _create_project_entry(token: str, master_db_id: str, project: dict) -> str | None:
    """Create a new project entry in Master Projects DB."""
    props = {
        "Project Name": {"title": [{"text": {"content": project["name"]}}]},
        "Status":       {"select": {"name": project.get("status", "Active")}},
        "Created Date": {"date": {"start": date.today().isoformat()}},
    }
    description = project.get("description", "")
    if description:
        props["Comments"] = {"rich_text": [{"text": {"content": description}}]}
    deadline = project.get("suggested_deadline")
    if deadline:
        props["Target Deadline"] = {"date": {"start": deadline}}

    response = requests.post(
        f"{NOTION_API}/pages",
        headers=_headers(token),
        json={"parent": {"database_id": master_db_id}, "properties": props},
        timeout=30,
    )
    if response.status_code == 200:
        return response.json()["id"]
    print(f"❌ Failed to create project entry: {response.text}")
    return None


def _mark_task_organized(token: str, task_id: str):
    """Set Organized = True on a task so it is skipped in future runs."""
    response = requests.patch(
        f"{NOTION_API}/pages/{task_id}",
        headers=_headers(token),
        json={"properties": {"Organized": {"checkbox": True}}},
        timeout=30,
    )
    if response.status_code != 200:
        print(f"❌ Failed to mark task {task_id} as organized: {response.text}")


def _link_task_to_project(token: str, task_id: str, project_page_id: str):
    """Patch a task's Parent Project relation to point to a project page."""
    response = requests.patch(
        f"{NOTION_API}/pages/{task_id}",
        headers=_headers(token),
        json={"properties": {"Parent Project": {"relation": [{"id": project_page_id}]}}},
        timeout=30,
    )
    if response.status_code != 200:
        print(f"❌ Failed to link task {task_id} to project: {response.text}")


def run_notion_task_moving(chat_id: str, token: str) -> bool:
    """
    AI-powered task organisation agent.

    1. Ensures all area DBs exist and schema is up to date.
    2. Fetches unorganized tasks from Tasks & To Dos.
    3. Sends them to Groq (Claude fallback) for area + project categorization.
    4. Creates area entries with Parent Task Link.
    5. Creates/links projects in Master Projects DB.
    """
    users = load_users()
    second_brain = users.get(str(chat_id), {}).get("second_brain", {})
    dbs = second_brain.get("databases", {})

    tasks_db_id = dbs.get("tasks_todos")
    master_db_id = dbs.get("master_projects")

    if not tasks_db_id or not master_db_id:
        print("❌ Second Brain databases not found in user.json. Run setup first.")
        return False

    # ── 0. Ensure all area DBs and schema fields are in place ─────────
    patch_missing_area_dbs(chat_id, token)
    # Reload dbs so any newly created area DB IDs are available
    dbs = load_users().get(str(chat_id), {}).get("second_brain", {}).get("databases", {})
    patch_tasks_organized_field(token, tasks_db_id)
    patch_done_and_rollups(token, tasks_db_id, master_db_id)
    patch_master_projects_schema(token, master_db_id)

    # ── 1. Fetch unorganized tasks ────────────────────────────────────
    tasks = _fetch_tasks(token, tasks_db_id)
    if not tasks:
        print("ℹ️ No tasks found in Tasks & To Dos.")
        return True

    print(f"📋 Fetched {len(tasks)} tasks for analysis.")

    # ── 2. Fetch existing projects for context ───────────────────────
    existing_projects = _fetch_existing_projects(token, master_db_id)
    existing_project_map = {p["name"]: p["page_id"] for p in existing_projects}
    print(f"📁 Existing projects: {[p['name'] for p in existing_projects]}")

    # ── 3. LLM analysis ──────────────────────────────────────────────
    result = _call_task_agent(tasks, existing_projects)
    if not result:
        print("❌ Task agent returned no result.")
        return False

    # ── 4. Create area entries ────────────────────────────────────────
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
            _mark_task_organized(token, task_id)

    # ── 5. Link tasks to projects ─────────────────────────────────────
    users = load_users()
    pending = users.get(str(chat_id), {}).get("pending_projects", {})

    for project in result.get("projects", []):
        project_name = project.get("name", "")
        is_existing = project.get("is_existing", False)
        new_task_ids = project.get("task_ids", [])
        project_page_id = None
        task_ids_to_link = []

        if is_existing and project_name in existing_project_map:
            # Existing project — link immediately, no threshold
            project_page_id = existing_project_map[project_name]
            task_ids_to_link = new_task_ids
            print(f"🔗 Linking to existing project: '{project_name}'")
        else:
            # New project — accumulate until 5 tasks
            prior = pending.get(project_name, {})
            accumulated_ids = list(dict.fromkeys(prior.get("task_ids", []) + new_task_ids))

            if len(accumulated_ids) < 5:
                pending[project_name] = {
                    "task_ids": accumulated_ids,
                    "description": project.get("description") or prior.get("description", ""),
                    "suggested_deadline": project.get("suggested_deadline") or prior.get("suggested_deadline"),
                }
                print(f"ℹ️ Project '{project_name}' pending ({len(accumulated_ids)}/5 tasks)")
                continue

            # Hit threshold — create the project
            project["task_ids"] = accumulated_ids
            project_page_id = _create_project_entry(token, master_db_id, project)
            if not project_page_id:
                continue
            task_ids_to_link = accumulated_ids
            pending.pop(project_name, None)

            deadline_display = project.get("suggested_deadline") or "no deadline set"
            _notify_telegram(
                chat_id,
                f"🚀 *New Project Created!*\n\n"
                f"*{project_name}* is taking shape — created with suggested deadline *{deadline_display}*.\n"
                f"Change it in Notion anytime if it doesn't work for you!"
            )
            print(f"✅ Project created at 5-task threshold: '{project_name}'")

        for task_id in task_ids_to_link:
            _link_task_to_project(token, task_id, project_page_id)
            task = task_map.get(task_id, {})
            print(f"   🔗 Linked task: '{task.get('title', task_id)}'")

        if task_ids_to_link:
            from assistant_backend_1.features_services.notion import update_project_progress
            update_project_progress(chat_id, task_ids_to_link[0])

        from assistant_backend_1.features_services.notion_project_details import populate_project_page
        populate_project_page(token, chat_id, project_page_id)

    # Save pending projects back to user.json
    users = load_users()
    users.setdefault(str(chat_id), {})["pending_projects"] = pending
    save_users(users)

    print("🎉 Task moving agent complete.")
    return True
