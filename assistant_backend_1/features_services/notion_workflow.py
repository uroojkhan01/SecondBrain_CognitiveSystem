# assistant_backend_1/features_services/notion_workflow.py

import os
import logging
import json
from typing import Dict, Any, List, Optional
from datetime import datetime

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
    """
    Manages the setup of Second Brain Notion structure and executes agentic tasks.
    This class is synchronous and integrates with the Groq API key configuration.
    """
    def __init__(self, notion_agent):
        self.notion_agent = notion_agent

    def _run_groq_agent(self, system_prompt: str, user_prompt: str) -> Optional[str]:
        """
        Executes a synchronous tool-calling loop using the native Groq SDK.
        Replaces previous LangChain/LangGraph implementations.
        """
        from assistant_backend_1.config import GROQ_API_KEYS
        from groq import Groq

        if not GROQ_API_KEYS:
            logger.warning("No Groq API keys found in config. Cannot run workflow agent.")
            return None

        # Use first Groq API key available
        client = Groq(api_key=GROQ_API_KEYS[0])

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]

        # Define tools in standard Groq function-calling specification
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "add_database_page",
                    "description": "Creates a new Notion Page (Row) inside a Database.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "parent_database_id": {
                                "type": "string",
                                "description": "The target Database ID where the page should be created."
                            },
                            "title": {
                                "type": "string",
                                "description": "The page title content."
                            },
                            "properties": {
                                "type": "object",
                                "description": "Property values corresponding to the target database schema."
                            }
                        },
                        "required": ["parent_database_id", "title"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "update_page",
                    "description": "Updates the properties of an existing Notion Page.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "page_id": {
                                "type": "string",
                                "description": "The ID of the page to update."
                            },
                            "properties": {
                                "type": "object",
                                "description": "The updated properties dictionary."
                            }
                        },
                        "required": ["page_id", "properties"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "query_database",
                    "description": "Queries a Notion Database for existing pages.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "database_id": {
                                "type": "string",
                                "description": "The Database ID to query."
                            },
                            "filter": {
                                "type": "object",
                                "description": "Filter criteria matching the Notion API query format."
                            }
                        },
                        "required": ["database_id"]
                    }
                }
            }
        ]

        # Iterate up to 5 steps of tool invocation and execution
        for step in range(5):
            try:
                response = client.chat.completions.create(
                    model="llama-3.3-70b-versatile",
                    messages=messages,
                    tools=tools,
                    tool_choice="auto",
                    temperature=0
                )

                response_message = response.choices[0].message
                messages.append(response_message)

                # If no tool calls are returned, we are done
                if not response_message.tool_calls:
                    logger.info("Groq workflow agent finished execution.")
                    return response_message.content

                for tool_call in response_message.tool_calls:
                    function_name = tool_call.function.name
                    function_args = json.loads(tool_call.function.arguments)

                    logger.info(f"Groq Agent executing tool: {function_name} with args {function_args}")

                    # Execute NotionAgent synchronous functions
                    if function_name == "add_database_page":
                        parent = {"type": "database_id", "database_id": function_args.get("parent_database_id")}
                        result = self.notion_agent.create_page(parent, function_args.get("properties", {}))
                    elif function_name == "update_page":
                        result = self.notion_agent.update_page_properties(
                            function_args.get("page_id"), 
                            function_args.get("properties", {})
                        )
                    elif function_name == "query_database":
                        result = self.notion_agent.query_database(
                            function_args.get("database_id"), 
                            filter=function_args.get("filter")
                        )
                    else:
                        result = {"error": f"Unknown tool: {function_name}"}

                    messages.append({
                        "tool_call_id": tool_call.id,
                        "role": "tool",
                        "name": function_name,
                        "content": json.dumps(result)
                    })

            except Exception as e:
                logger.error(f"Error in Groq agent workflow execution step {step}: {e}")
                break

        return None

    # =====================================================================
    # HARDCODED WORKSPACE BUILDER (Synchronous)
    # =====================================================================

    def _ensure_database(self, title: str, parent_id: str, schema: dict) -> str:
        """Ensures a database exists in the workspace, creating it if necessary."""
        existing = self.notion_agent.get_database_ids(title)
        if existing:
            return list(existing.values())[0]
        
        logger.info(f"Creating database: {title}")
        db = self.notion_agent.create_database(parent_id, title, schema)
        return db.get("id")

    def _ensure_page(self, title: str, parent_id: str) -> str:
        """Ensures a page exists under a parent block, creating it if necessary."""
        existing = self.notion_agent.get_page_ids(title)
        if existing:
            return list(existing.values())[0]

        logger.info(f"Creating page: {title}")
        parent = {"type": "page_id", "page_id": parent_id}
        properties = {
            "title": {
                "title": [{"type": "text", "text": {"content": title}}]
            }
        }
        page = self.notion_agent.create_page(parent, properties)
        return page.get("id")

    def build_workspace_architecture(self):
        """Builds/verifies the Second Brain database structure synchronously."""
        logger.info("Building workspace architecture programmatically...")
        root_id = self.notion_agent.parent_page_id
        
        if not root_id:
            logger.warning("No parent page ID configured. Skipping architecture build.")
            return

        # 1. Capture DB (Standalone DB)
        capture_id = self._ensure_database("📝 Notes & Capture", root_id, CAPTURE_SCHEMA)
        capture_ds_id = self.notion_agent.resolve_data_source_id(capture_id)

        # 2. Area Boards Page
        organize_page_id = self._ensure_page("🗂️ Areas Boards", root_id)
        
        # 3. Area DBs (Nested inside Area Boards Page)
        area_ids = {}
        for area_name, specifics in AREA_SPECIFICS.items():
            schema = {**GLOBAL_AREA_SCHEMA, **specifics}
            schema["Source Capture Link"] = {"relation": {"database_id": capture_id, "data_source_id": capture_ds_id, "single_property": {}}}
            db_id = self._ensure_database(area_name, organize_page_id, schema)
            area_ids[area_name] = db_id

        # 4. Master Projects Directory (Page holding the Master Project DB)
        projects_page_id = self._ensure_page("🚀 Project Directory", root_id)
        
        # Link Projects to specific Areas
        for area_name, area_id in area_ids.items():
            area_ds_id = self.notion_agent.resolve_data_source_id(area_id)
            PROJECTS_SCHEMA[f"Related {area_name}"] = {"relation": {"database_id": area_id, "data_source_id": area_ds_id, "single_property": {}}}
        
        # Create Master Projects DB inside the Directory Page
        projects_id = self._ensure_database("Master Projects DB", projects_page_id, PROJECTS_SCHEMA)
        projects_ds_id = self.notion_agent.resolve_data_source_id(projects_id)

        # 5. Master Tasks & To Dos DB
        # Relate Tasks directly to the Master Projects DB
        TASKS_SCHEMA["Parent Project"] = {"relation": {"database_id": projects_id, "data_source_id": projects_ds_id, "single_property": {}}}
        
        # Create the raw Tasks DB
        self._ensure_database("☑️ Tasks and To Dos", root_id, TASKS_SCHEMA)

        logger.info("Workspace architecture verified/built successfully.")

    # =====================================================================
    # LLM EXECUTION METHODS (Synchronous)
    # =====================================================================

    def ensure_database_exists(self, db_type: str) -> Dict[str, str]:
        """Resolves target database metadata, building the workspace architecture if missing."""
        self.build_workspace_architecture()
        mapping = {"capture": "📝 Notes & Capture", "projects": "Master Projects DB", "tasks": "☑️ Tasks and To Dos"}
        title = mapping.get(db_type, db_type)
        ids = self.notion_agent.get_database_ids(title)
        return ids if ids else {"database_id": "mock", "data_source_id": "mock"}

    def route_and_log_to_notion(self, text: str, intent: str, extracted_data: Dict[str, Any], emotion: str) -> Dict[str, Any]:
        """Runs the routing agent to record user inputs inside the capture DB."""
        capture_ids = self.notion_agent.get_database_ids("📝 Notes & Capture")
        capture_id = list(capture_ids.values())[0] if capture_ids else "UNKNOWN"

        prompt = (
            f"New user input: '{text}'. Extracted Data: {extracted_data}. "
            f"ACTION: Insert this into the Capture Database (ID: {capture_id})."
        )
        logger.info(f"NotionWorkflow LLM: Routing raw input to Capture...")
        
        self._run_groq_agent(ROUTING_PROMPT, prompt)
        return {"id": "llm-handled", "url": "notion.so"}

    def run_automations(self, chat_id: int):
        """Runs the automation agent tasks (Sort & Synthesize)."""
        logger.info("NotionWorkflow LLM: Running Internal Automations (Sort & Synthesize)...")
        self._run_groq_agent(AUTOMATION_PROMPT, "Start the Phase 2 and Phase 3 internal review loops.")

    def get_current_lifecycle_phase(self) -> int:
        return 1

    def render_dashboard(self):
        pass

    def check_and_apply_persona_evolution(self, persona: str) -> Optional[str]:
        return None
        
    def get_or_create_area_page(self, area_name: str) -> Optional[str]:
        return "mock-area-id"

    def get_or_create_project_page(self, project_name: str, area_name: Optional[str] = None) -> Optional[str]:
        return "mock-project-id"