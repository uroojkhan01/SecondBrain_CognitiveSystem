"""
notion_project_details.py

Populates the body of a Master Projects DB page with a managed toggle section
showing associated areas, tasks (with criticality + done status), and an
overview callout (status / progress bar / deadline).

The toggle titled "📋  Areas & Tasks" is the ONLY thing this module touches —
all other content the user has written on the project page is left intact.
On every refresh we wipe only the toggle's children and rewrite them.
"""

import requests
from assistant_backend_1.helpers import load_users
from assistant_backend_1.features_services.notion_schema import AREA_DATABASES

NOTION_API = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"

_AREA_EMOJI_MAP = {name: emoji for name, emoji in AREA_DATABASES}

MANAGED_TOGGLE_TITLE = "📋  Areas & Tasks"

_CRITICALITY_LABEL = {
    "P1 - Critical":  "🔴 P1",
    "P2 - Important": "🟡 P2",
    "P3 - Minor":     "🔵 P3",
}


# ── Shared helpers ────────────────────────────────────────────────────────────

def _headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Notion-Version": NOTION_VERSION,
    }


def _area_key(name: str) -> str:
    return name.lower().replace(" & ", "_").replace(" ", "_")


# ── Block-level helpers ───────────────────────────────────────────────────────

def _find_managed_toggle(token: str, page_id: str) -> str | None:
    """Return the block ID of the managed toggle on this project page, or None."""
    cursor = None
    while True:
        params = {"start_cursor": cursor} if cursor else {}
        r = requests.get(
            f"{NOTION_API}/blocks/{page_id}/children",
            headers=_headers(token),
            params=params,
            timeout=30,
        )
        if r.status_code != 200:
            return None
        data = r.json()
        for block in data.get("results", []):
            if block.get("type") == "toggle":
                text = "".join(
                    t.get("plain_text", "")
                    for t in block.get("toggle", {}).get("rich_text", [])
                )
                if MANAGED_TOGGLE_TITLE in text:
                    return block["id"]
        if data.get("has_more"):
            cursor = data["next_cursor"]
        else:
            return None


def _clear_block_children(token: str, block_id: str) -> None:
    """Delete every child of a block, handling pagination."""
    cursor = None
    while True:
        params = {"start_cursor": cursor} if cursor else {}
        r = requests.get(
            f"{NOTION_API}/blocks/{block_id}/children",
            headers=_headers(token),
            params=params,
            timeout=30,
        )
        if r.status_code != 200:
            break
        data = r.json()
        for child in data.get("results", []):
            requests.delete(
                f"{NOTION_API}/blocks/{child['id']}",
                headers=_headers(token),
                timeout=30,
            )
        if data.get("has_more"):
            cursor = data["next_cursor"]
        else:
            break


def _append_blocks(token: str, block_id: str, children: list) -> bool:
    """Append blocks as children, chunked at 100 per request (Notion API limit)."""
    for i in range(0, len(children), 100):
        r = requests.patch(
            f"{NOTION_API}/blocks/{block_id}/children",
            headers=_headers(token),
            json={"children": children[i:i + 100]},
            timeout=30,
        )
        if r.status_code != 200:
            print(f"❌ Block append failed: {r.text}")
            return False
    return True


# ── Data fetching ─────────────────────────────────────────────────────────────

def _fetch_project_tasks_with_areas(
    token: str,
    tasks_db_id: str,
    area_dbs: dict,
    project_page_id: str,
) -> dict:
    """
    Fetch all tasks linked to a project and bucket them by area name.
    Tasks with no area match land under the '_uncategorized' key.

    Returns:
        {
            "Health & Fitness":  [{"title": ..., "done": ..., "criticality": ...}, ...],
            "_uncategorized":    [...],
        }
    """
    r = requests.post(
        f"{NOTION_API}/databases/{tasks_db_id}/query",
        headers=_headers(token),
        json={"filter": {"property": "Parent Project", "relation": {"contains": project_page_id}}},
        timeout=30,
    )
    if r.status_code != 200:
        return {}

    task_map: dict = {}
    for page in r.json().get("results", []):
        if page.get("archived"):
            continue
        props = page.get("properties", {})
        title = "".join(
            t.get("plain_text", "")
            for t in props.get("Task Name", {}).get("title", [])
        ).strip()
        done        = props.get("Done", {}).get("checkbox", False)
        criticality = (props.get("Criticality", {}).get("select") or {}).get("name", "")
        task_map[page["id"]] = {
            "id": page["id"],
            "title": title,
            "done": done,
            "criticality": criticality,
        }

    if not task_map:
        return {}

    # Normalize IDs once for O(1) lookup (Notion API is inconsistent with dashes)
    norm_to_real = {tid.replace("-", ""): tid for tid in task_map}

    tasks_by_area: dict = {}
    assigned: set = set()

    for area_name, _ in AREA_DATABASES:
        area_db_id = area_dbs.get(_area_key(area_name))
        if not area_db_id:
            continue
        try:
            ar = requests.post(
                f"{NOTION_API}/databases/{area_db_id}/query",
                headers=_headers(token),
                json={},
                timeout=30,
            )
            for entry in ar.json().get("results", []):
                if entry.get("archived"):
                    continue
                for ref in (
                    entry.get("properties", {})
                         .get("Parent Task Link", {})
                         .get("relation", [])
                ):
                    real_id = norm_to_real.get(ref["id"].replace("-", ""))
                    if real_id and real_id not in assigned:
                        tasks_by_area.setdefault(area_name, []).append(task_map[real_id])
                        assigned.add(real_id)
        except Exception as e:
            print(f"⚠️ Area query error ({area_name}): {e}")

    uncategorized = [t for tid, t in task_map.items() if tid not in assigned]
    if uncategorized:
        tasks_by_area["_uncategorized"] = uncategorized

    return tasks_by_area


# ── Block building ────────────────────────────────────────────────────────────

def _build_inner_blocks(
    tasks_by_area: dict,
    status: str | None,
    progress,
    deadline: str | None,
) -> list:
    """Return the list of blocks that live inside the managed toggle."""
    blocks = []

    # Overview callout
    lines = []
    if status:
        lines.append(f"Status:    {status}")
    if progress is not None:
        filled = int(progress) // 10
        bar = "█" * filled + "░" * (10 - filled)
        lines.append(f"Progress:  {bar}  {int(progress)}%")
    if deadline:
        lines.append(f"Deadline:  {deadline}")

    if lines:
        blocks.append({
            "object": "block",
            "type": "callout",
            "callout": {
                "rich_text": [{"type": "text", "text": {"content": "\n".join(lines)}}],
                "icon": {"type": "emoji", "emoji": "📊"},
                "color": "blue_background",
            },
        })
        blocks.append({"object": "block", "type": "divider", "divider": {}})

    if not tasks_by_area:
        blocks.append({
            "object": "block",
            "type": "paragraph",
            "paragraph": {
                "rich_text": [{
                    "type": "text",
                    "text": {"content": "No tasks linked to this project yet."},
                    "annotations": {"italic": True, "color": "gray"},
                }],
            },
        })
        return blocks

    for area_name, tasks in tasks_by_area.items():
        label = (
            "📁  Uncategorized"
            if area_name == "_uncategorized"
            else f"{_AREA_EMOJI_MAP.get(area_name, '📌')}  {area_name}"
        )
        blocks.append({
            "object": "block",
            "type": "heading_3",
            "heading_3": {
                "rich_text": [{"type": "text", "text": {"content": label}}],
            },
        })
        for task in tasks:
            crit  = _CRITICALITY_LABEL.get(task.get("criticality", ""), "")
            label_text = f"{task['title']}  {crit}".strip()
            blocks.append({
                "object": "block",
                "type": "to_do",
                "to_do": {
                    "rich_text": [{"type": "text", "text": {"content": label_text}}],
                    "checked": bool(task.get("done")),
                },
            })
        blocks.append({"object": "block", "type": "divider", "divider": {}})

    return blocks


# ── Public API ────────────────────────────────────────────────────────────────

def populate_all_projects(token: str, chat_id: str) -> None:
    """
    Backfill / refresh the '📋 Areas & Tasks' toggle for every project in
    Master Projects DB.  Run this once to populate existing projects, or
    call it any time to force a full refresh across all projects.
    """
    users      = load_users()
    dbs        = users.get(str(chat_id), {}).get("second_brain", {}).get("databases", {})
    master_db_id = dbs.get("master_projects")
    if not master_db_id:
        print(f"❌ populate_all_projects: master_projects DB not found for {chat_id}")
        return

    r = requests.post(
        f"{NOTION_API}/databases/{master_db_id}/query",
        headers=_headers(token),
        json={},
        timeout=30,
    )
    if r.status_code != 200:
        print(f"❌ populate_all_projects: could not query Master Projects DB")
        return

    projects = [p for p in r.json().get("results", []) if not p.get("archived")]
    print(f"📁 Refreshing {len(projects)} project(s)...")

    for project in projects:
        populate_project_page(token, chat_id, project["id"])


def populate_project_page(token: str, chat_id: str, project_page_id: str) -> bool:
    """
    Write or refresh the '📋 Areas & Tasks' managed toggle on a project page.

    - First call: appends the toggle to the bottom of the page.
    - Subsequent calls: wipes only the toggle's children and rewrites them.
    - Everything else the user has added to the page is left completely untouched.
    """
    users    = load_users()
    dbs      = users.get(str(chat_id), {}).get("second_brain", {}).get("databases", {})
    tasks_db_id = dbs.get("tasks_todos")
    if not tasks_db_id:
        print(f"❌ populate_project_page: tasks_todos DB not found for {chat_id}")
        return False

    # Fetch project properties (name, status, progress, deadline)
    r = requests.get(
        f"{NOTION_API}/pages/{project_page_id}",
        headers=_headers(token),
        timeout=30,
    )
    if r.status_code != 200:
        print(f"❌ populate_project_page: could not fetch page {project_page_id}")
        return False

    props        = r.json().get("properties", {})
    project_name = "".join(
        t.get("plain_text", "")
        for t in props.get("Project Name", {}).get("title", [])
    ).strip()
    status   = (props.get("Status", {}).get("select") or {}).get("name")
    progress = props.get("Progress Bar", {}).get("number")
    deadline = (props.get("Target Deadline", {}).get("date") or {}).get("start")

    tasks_by_area = _fetch_project_tasks_with_areas(token, tasks_db_id, dbs, project_page_id)
    inner_blocks  = _build_inner_blocks(tasks_by_area, status, progress, deadline)

    toggle_id = _find_managed_toggle(token, project_page_id)

    if toggle_id:
        # Refresh path — touch only the managed toggle
        _clear_block_children(token, toggle_id)
        ok = _append_blocks(token, toggle_id, inner_blocks)
    else:
        # First-run path — create the toggle then fill it
        r2 = requests.patch(
            f"{NOTION_API}/blocks/{project_page_id}/children",
            headers=_headers(token),
            json={"children": [{
                "object": "block",
                "type": "toggle",
                "toggle": {
                    "rich_text": [{
                        "type": "text",
                        "text": {"content": MANAGED_TOGGLE_TITLE},
                        "annotations": {"bold": True},
                    }],
                },
            }]},
            timeout=30,
        )
        if r2.status_code != 200:
            print(f"❌ Failed to create managed toggle: {r2.text}")
            return False
        toggle_id = r2.json()["results"][0]["id"]
        ok = _append_blocks(token, toggle_id, inner_blocks)

    if ok:
        print(f"✅ Project page updated: '{project_name}'")
    return ok
