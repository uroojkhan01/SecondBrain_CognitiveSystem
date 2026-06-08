import os
import logging
import asyncio
from typing import Dict, Any, List, Optional
from datetime import datetime

# pyrefly: ignore [missing-import]
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent
from langchain.tools import tool

logger = logging.getLogger(__name__)

# =====================================================================
# HARDCODED NOTION SCHEMAS (Based on Structure.md)
# =====================================================================

CAPTURE_SCHEMA = {
    "Content/Message": {"title": {}},
    "Capture Timestamp": {"date": {}},
    "Set Reminder?": {"checkbox": {}},
    "Reminder Date/Time": {"date": {}},
    "Processed Status": {"select": {"options": [
        {"name": "Unprocessed", "color": "red"}, 
        {"name": "Moved to Area", "color": "green"},
        {"name": "Archived", "color": "gray"}
    ]}},
    "Proposed Area (AI)": {"select": {"options": [
        {"name": "Health & Fitness", "color": "red"},
        {"name": "Finance & Wealth", "color": "green"},
        {"name": "Career & Professional", "color": "blue"},
        {"name": "Personal Growth", "color": "purple"},
        {"name": "Home & Lifestyle", "color": "yellow"}
    ]}},
    "Proposed Project (AI)": {"rich_text": {}},
    "Input Type": {"select": {"options": [
        {"name": "Text", "color": "default"}, 
        {"name": "Link", "color": "blue"}, 
        {"name": "Voice Note", "color": "purple"},
        {"name": "Image", "color": "yellow"}
    ]}},
    "Actionability": {"select": {"options": [
        {"name": "Actionable Task", "color": "red"}, 
        {"name": "Reference Only", "color": "blue"}, 
        {"name": "Someday/Maybe", "color": "yellow"}
    ]}}
}

GLOBAL_AREA_SCHEMA = {
    "Name": {"title": {}},
    "Date Logged": {"date": {}},
    "AI Executive Summary": {"rich_text": {}}
    # "Source Capture Link" relation added dynamically during build
}

AREA_SPECIFICS = {
    "Health & Fitness": {
        "Sub-Category": {"select": {"options": [{"name": "Nutrition"}, {"name": "Workout"}, {"name": "Sleep"}, {"name": "Mental Health"}]}},
        "Biometric/Value": {"rich_text": {}},
        "Energy Level": {"select": {"options": [{"name": "High"}, {"name": "Medium"}, {"name": "Low"}]}}
    },
    "Finance & Wealth": {
        "Transaction Type": {"select": {"options": [{"name": "Expense Idea"}, {"name": "Income Stream"}, {"name": "Investment Research"}]}},
        "Estimated Amount": {"number": {"format": "dollar"}},
        "Financial Entity": {"rich_text": {}}
    },
    "Career & Professional": {
        "Professional Domain": {"select": {"options": [{"name": "Networking"}, {"name": "Skill Acquisition"}, {"name": "Work Project"}]}},
        "Associated Company/Person": {"rich_text": {}},
        "Impact Score": {"select": {"options": [{"name": "High Impact"}, {"name": "Routine Maintenance"}]}}
    },
    "Personal Growth & Learning": {
        "Media Format": {"select": {"options": [{"name": "Book"}, {"name": "Article"}, {"name": "Podcast"}, {"name": "Course"}]}},
        "Key Takeaway": {"rich_text": {}},
        "Application": {"rich_text": {}}
    },
    "Home & Lifestyle": {
        "Asset/Domain": {"select": {"options": [{"name": "Vehicle"}, {"name": "Apartment"}, {"name": "Hobbies"}, {"name": "Family"}]}},
        "Cost Estimate": {"number": {}},
        "Urgency": {"select": {"options": [{"name": "Immediate"}, {"name": "Seasonal"}, {"name": "Low Priority"}]}}
    }
}

PROJECTS_SCHEMA = {
    "Project Name": {"title": {}},
    "The 'Big Why'": {"rich_text": {}},
    "Target Deadline": {"date": {}},
    "Status": {"select": {"options": [
        {"name": "Proposed", "color": "blue"}, 
        {"name": "Active", "color": "green"},
        {"name": "Paused", "color": "yellow"},
        {"name": "Completed", "color": "gray"}
    ]}},
    "Progress Bar": {"number": {}}, # Recommend setting this to a Formula manually in Notion UI (Completed / Total Tasks)
    "Celebration Reward": {"rich_text": {}}
    # "Related Areas" relations added dynamically during build
}

TASKS_SCHEMA = {
    "Task Name": {"title": {}},
    "Execution Date": {"date": {}},
    "Requirement Level": {"select": {"options": [{"name": "Mandatory", "color": "red"}, {"name": "Optional", "color": "gray"}]}},
    "Criticality": {"select": {"options": [
        {"name": "P1 - Critical", "color": "red"}, 
        {"name": "P2 - Important", "color": "yellow"}, 
        {"name": "P3 - Minor", "color": "blue"}
    ]}},
    "Energy Required": {"select": {"options": [
        {"name": "High Focus", "color": "red"}, 
        {"name": "Medium", "color": "yellow"}, 
        {"name": "Low/Braindead", "color": "green"}
    ]}},
    "Time Block": {"select": {"options": [
        {"name": "Morning", "color": "yellow"}, 
        {"name": "Afternoon", "color": "orange"}, 
        {"name": "Evening", "color": "blue"}
    ]}},
    "Estimated Duration": {"number": {}}, # In minutes
    "Rollover Count": {"number": {}}
    # "Parent Project" relation added dynamically during build
}

# =====================================================================
# AGENT PROMPTS 
# =====================================================================

ROUTING_PROMPT = """You are a sorting assistant. 
A user has provided raw input. Your ONLY job is to format this data and insert it into '📝 Notes & Capture' using the `add_database_page` tool.
Deduce 'Input Type', 'Actionability', 'Proposed Area (AI)', and 'Proposed Project (AI)'. 
Set 'Processed Status' to 'Unprocessed'. Do NOT create Projects or Tasks yet."""

AUTOMATION_PROMPT = """You are the internal brain of a Second Brain system. Execute two phases:
Phase 2 (Sort): Query '📝 Notes & Capture' for 'Unprocessed' items. Move the data into the appropriate Area database (Health, Finance, etc.). Update the original Capture item status to 'Moved to Area' and link them.
Phase 3 (Synthesize): Query the Area databases. If you spot actionable goals, create a Project in the Master '🚀 Project Directory'. Then, break that project down into execution steps and create them in '☑️ Tasks and To Dos', linking them back to the specific Project using the 'Parent Project' relation. Also assign 'Time Block' and 'Energy Required' based on the task language."""

class NotionWorkflowManager:
    def __init__(self, notion_agent):
        self.notion_agent = notion_agent
        self.agent_executor = None

    def _init_agent(self, prompt: str):
        if not self.notion_agent.github_token:
            logger.warning("No GitHub token available for notion_workflow LLM Agent.")
            return None

        llm = ChatOpenAI(
            model="gpt-4o-mini",
            api_key=self.notion_agent.github_token,
            base_url="https://models.inference.ai.azure.com",
            temperature=0
        )
        
        @tool
        async def add_database_page(parent_database_id: str, title: str, properties: Dict[str, Any] = None) -> Dict[str, Any]:
            """Creates a new Notion Page (Row) inside a Database."""
            parent = {"type": "database_id", "database_id": parent_database_id}
            return await self.notion_agent.create_page(parent, properties)
            
        @tool
        async def update_page(page_id: str, properties: Dict[str, Any]) -> Dict[str, Any]:
            """Updates the properties of an existing Notion Page."""
            return await self.notion_agent.update_page_properties(page_id, properties)

        @tool
        async def query_database(database_id: str, filter: Dict[str, Any] = None) -> Dict[str, Any]:
            """Queries a Notion Database for existing pages."""
            return await self.notion_agent.query_database(database_id=database_id, filter=filter)
            
        tools = [add_database_page, update_page, query_database]
        return create_react_agent(llm, tools=tools, prompt=prompt)

    # =====================================================================
    # HARDCODED WORKSPACE BUILDER
    # =====================================================================

    async def _ensure_database(self, title: str, parent_id: str, schema: dict) -> str:
        existing = await self.notion_agent.get_database_ids(title)
        if existing:
            return list(existing.values())[0]
        
        logger.info(f"Creating database: {title}")
        db = await self.notion_agent.create_database(parent_id, title, schema)
        return db.get("id")

    async def _ensure_page(self, title: str, parent_id: str) -> str:
        if hasattr(self.notion_agent, "get_page_ids"):
            existing = await self.notion_agent.get_page_ids(title)
            if existing:
                return list(existing.values())[0]

        logger.info(f"Creating page: {title}")
        parent = {"type": "page_id", "page_id": parent_id}
        properties = {
            "title": {
                "title": [{"type": "text", "text": {"content": title}}]
            }
        }
        page = await self.notion_agent.create_page(parent, properties)
        return page.get("id")

    async def build_workspace_architecture(self):
        logger.info("Building workspace architecture programmatically...")
        root_id = self.notion_agent.parent_page_id

        # 1. Capture DB (Standalone DB)
        capture_id = await self._ensure_database("📝 Notes & Capture", root_id, CAPTURE_SCHEMA)
        capture_ds_id = await self.notion_agent.resolve_data_source_id(capture_id)

        # 2. Area Boards Page
        organize_page_id = await self._ensure_page("🗂️ Areas Boards", root_id)
        
        # 3. Area DBs (Nested inside Area Boards Page)
        area_ids = {}
        for area_name, specifics in AREA_SPECIFICS.items():
            schema = {**GLOBAL_AREA_SCHEMA, **specifics}
            schema["Source Capture Link"] = {"relation": {"database_id": capture_id, "data_source_id": capture_ds_id, "single_property": {}}}
            db_id = await self._ensure_database(area_name, organize_page_id, schema)
            area_ids[area_name] = db_id

        # 4. Master Projects Directory (Page holding the Master Project DB)
        projects_page_id = await self._ensure_page("🚀 Project Directory", root_id)
        
        # Link Projects to specific Areas
        for area_name, area_id in area_ids.items():
            area_ds_id = await self.notion_agent.resolve_data_source_id(area_id)
            PROJECTS_SCHEMA[f"Related {area_name}"] = {"relation": {"database_id": area_id, "data_source_id": area_ds_id, "single_property": {}}}
        
        # Create Master Projects DB inside the Directory Page
        projects_id = await self._ensure_database("Master Projects DB", projects_page_id, PROJECTS_SCHEMA)
        projects_ds_id = await self.notion_agent.resolve_data_source_id(projects_id)

        # 5. Master Tasks & To Dos DB
        # Relate Tasks directly to the Master Projects DB
        TASKS_SCHEMA["Parent Project"] = {"relation": {"database_id": projects_id, "data_source_id": projects_ds_id, "single_property": {}}}
        
        # NOTE: Notion API cannot create Kanbans or Calendars. 
        # Create the raw DB here, then manually create the Weekly/Monthly views in Notion UI.
        tasks_id = await self._ensure_database("☑️ Tasks and To Dos", root_id, TASKS_SCHEMA)

        logger.info("Workspace architecture verified/built successfully.")

    # =====================================================================
    # LLM EXECUTION METHODS
    # =====================================================================

    async def ensure_database_exists(self, db_type: str) -> Dict[str, str]:
        await self.build_workspace_architecture()
        mapping = {"capture": "📝 Notes & Capture", "projects": "Master Projects DB", "tasks": "☑️ Tasks and To Dos"}
        title = mapping.get(db_type, db_type)
        ids = await self.notion_agent.get_database_ids(title)
        return ids if ids else {"database_id": "mock", "data_source_id": "mock"}

    async def route_and_log_to_notion(self, text: str, intent: str, extracted_data: Dict[str, Any], emotion: str) -> Dict[str, Any]:
        agent = self._init_agent(ROUTING_PROMPT)
        if not agent: return {"id": "mock", "url": "mock"}
            
        capture_ids = await self.notion_agent.get_database_ids("📝 Notes & Capture")
        capture_id = list(capture_ids.values())[0] if capture_ids else "UNKNOWN"

        prompt = (
            f"New user input: '{text}'. Extracted Data: {extracted_data}. "
            f"ACTION: Insert this into the Capture Database (ID: {capture_id})."
        )
        logger.info(f"NotionWorkflow LLM: Routing raw input to Capture...")
        await agent.ainvoke({"messages": [("user", prompt)]})
        return {"id": "llm-handled", "url": "notion.so"}

    async def run_automations(self, chat_id: int):
        agent = self._init_agent(AUTOMATION_PROMPT)
        if not agent: return
            
        logger.info("NotionWorkflow LLM: Running Internal Automations (Sort & Synthesize)...")
        await agent.ainvoke({"messages": [("user", "Start the Phase 2 and Phase 3 internal review loops.")]})

    def get_current_lifecycle_phase(self) -> int:
        return 1

    async def render_dashboard(self):
        pass

    async def check_and_apply_persona_evolution(self, persona: str) -> Optional[str]:
        return None
        
    async def get_or_create_area_page(self, area_name: str) -> Optional[str]:
        return "mock-area-id"

    async def get_or_create_project_page(self, project_name: str, area_name: Optional[str] = None) -> Optional[str]:
        return "mock-project-id"