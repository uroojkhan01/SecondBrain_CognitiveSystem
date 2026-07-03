"""
notion_schema.py

Single source of truth for all Second Brain data definitions:
area list, flat schemas, Notion API property specs, and the task-agent prompt.
Both notion_agent.py and notion_project_details.py import from here so that
adding a new area (or changing a property) only requires editing this file.
"""

# ── Area registry ──────────────────────────────────────────────────────────────

AREA_DATABASES = [
    ("Health & Fitness",           "💪"),
    ("Finance & Wealth",           "💰"),
    ("Career & Professional",      "💼"),
    ("Personal Growth & Learning", "🌱"),
    ("Home & Lifestyle",           "🏠"),
    ("Family & Friends",           "🤝"),
]

AREA_NAME_TO_KEY = {
    "Health & Fitness":           "health_fitness",
    "Finance & Wealth":           "finance_wealth",
    "Career & Professional":      "career_professional",
    "Personal Growth & Learning": "personal_growth_learning",
    "Home & Lifestyle":           "home_lifestyle",
    "Family & Friends":           "family_friends",
}

# ── Flat schemas (column_name → type string, used by notion.database_ids) ─────

AREA_DB_FLAT_SCHEMA = {
    "Name":                 "title",
    "Date Logged":          "date",
    "AI Executive Summary": "rich_text",
    "Parent Task Link":     "relation",
}

MASTER_PROJECTS_FLAT_SCHEMA = {
    "Project Name":    "title",
    "Status":          "select",
    "Target Deadline": "date",
    "Progress Bar":    "number",
    "Created Date":    "date",
    "Comments":        "rich_text",
}

TASKS_FLAT_SCHEMA = {
    "Task Name":      "title",
    "Execution Date": "date",
    "Criticality":    "select",
    "Parent Project": "relation",
    "Organized":      "checkbox",
    "Done":           "checkbox",
}

# ── Full Notion API property definitions (used when creating databases) ────────

AREA_DB_PROPERTIES = {
    "Name":                 {"title": {}},
    "Date Logged":          {"date": {}},
    "AI Executive Summary": {"rich_text": {}},
    # Parent Task Link is patched in separately after Tasks DB exists
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
    "Progress Bar":    {"number": {"format": "bar"}},
    "Created Date":    {"date": {}},
    "Comments":        {"rich_text": {}},
}

# ── Task agent prompt ──────────────────────────────────────────────────────────

TASK_AGENT_PROMPT = """You are a Second Brain task organization agent.

You will receive a JSON object with:
- "tasks": list of new tasks to organise (each with id and title)
- "existing_projects": list of project names already in the user's Master Projects DB

Your job is to:

1. AREA CATEGORIZATION — assign each task to one of these areas (or null if unclear):
   - "Health & Fitness": health, medical, exercise, diet, mental health, wellness, doctor, gym, pregnancy, checkups
   - "Finance & Wealth": money, bills, payments, investments, banking, budget, salary, tax, expenses, savings
   - "Career & Professional": work, job, meetings, deadlines, clients, presentations, professional development, projects
   - "Personal Growth & Learning": learning, books, courses, skills, self-improvement, studying, reading, travel, trips, flights, hotels, booking holidays, experiences, visiting places
   - "Home & Lifestyle": home, household, cleaning, repairs, groceries, shopping, cooking, furniture, renovation, errands
   - "Family & Friends": family, friends, relationships, birthdays, anniversaries, gifts, celebrations, social plans, catching up, kids, parenting, partner, parents, siblings, relatives, weddings, gatherings

2. PROJECT DETECTION — identify which project each task belongs to.
   - FIRST check if the task fits an existing project from "existing_projects". If it does, use that EXACT project name.
   - ONLY create a NEW project name if no existing project fits AND 5 or more new tasks clearly share one overarching goal.
   - A single task can be linked to an existing project even on its own.
   - For NEW projects, suggest a realistic deadline (ISO date YYYY-MM-DD) based on the complexity and nature of the tasks.
   - Name new projects concisely with the current year (e.g. "Home Renovation 2026", "Job Search 2026").

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
      "name": "<Project Name — use exact existing name if applicable>",
      "is_existing": true,
      "status": "Active",
      "description": "<one sentence describing what this project is about>",
      "suggested_deadline": "<YYYY-MM-DD for new projects, null for existing>",
      "task_ids": ["<task_page_id>"]
    }
  ]
}"""
