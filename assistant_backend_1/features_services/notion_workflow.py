# assistant_backend_1/features_services/notion_workflow.py

import os
import logging
import json
from typing import Dict, Any, List, Optional
from datetime import datetime

# Import schemas, prompts, and helpers from their organized locations
from assistant_backend_1.schema import (
    CAPTURE_SCHEMA,
    GLOBAL_AREA_SCHEMA,
    AREA_SPECIFICS,
    PROJECTS_SCHEMA,
    TASKS_SCHEMA
)
from assistant_backend_1.prompts import ROUTING_PROMPT, AUTOMATION_PROMPT
from assistant_backend_1.helpers import load_users


logger = logging.getLogger(__name__)

class NotionWorkflowManager:
    """
    Orchestrates the Second Brain Notion workspace structure and runs
    agentic routing and synthesis workflows asynchronously.
    """
    def __init__(self, notion_agent):
        self.notion_agent = notion_agent
        self.agent_executor = None

    def set_user_credentials(self, chat_id: Optional[str] = None):
        """
        Dynamically configures the notion_agent instance to run on behalf of the given chat_id.
        Loads the user's connected Notion OAuth token, active database, and isolated cache file.
        This enables multi-tenant OAuth permissions directly in the workflow layer
        without modifying notion_mcp.py.
        """
        if not chat_id:
            logger.info("No chat_id provided. Using default global agent credentials.")
            return

        try:
            from assistant_backend_1.helpers import load_users
            from notion_client import AsyncClient
            
            users = load_users()
            user = users.get(str(chat_id), {})
            notion = user.get("notion", {})
            token = notion.get("token")
            database_id = notion.get("active_database_id")
            
            if token:
                logger.info(f"Dynamically switching NotionAgent to credentials of user {chat_id}...")
                self.notion_agent.token = token
                self.notion_agent.client = AsyncClient(auth=token)
                self.notion_agent.chat_id = chat_id
                
                # Overwrite cache path and reload database cache for the user
                self.notion_agent.cache_file = f"notion_cache_{str(chat_id)}.json"
                self.notion_agent.db_cache = self.notion_agent._load_cache()
                
                # Store the active database ID and type
                self.notion_agent.active_database_id = database_id
                
                database_list = notion.get("database_ids", [])
                active_item_type = "database"
                for db in database_list:
                    if db.get("id") == database_id:
                        active_item_type = db.get("type", "database")
                        break
                
                self.notion_agent.active_item_type = active_item_type
                if active_item_type == "page":
                    self.notion_agent.parent_page_id = database_id
            else:
                logger.warning(f"No Notion token stored for user {chat_id}. Using default/mock credentials.")
        except Exception as e:
            logger.error(f"Error dynamically switching user credentials: {e}")

    async def _run_groq_agent(self, system_prompt: str, user_prompt: str) -> Optional[str]:
        """
        Executes an asynchronous tool-calling loop using the native AsyncGroq SDK.
        This completely replaces the langchain_openai.ChatOpenAI and langgraph dependencies.
        It uses the llama-3.3-70b-versatile model.
        """
        from assistant_backend_1.config import GROQ_API_KEYS
        from groq import AsyncGroq
        
        # Use first Groq API key available in config
        groq_api_key = GROQ_API_KEYS[0] if GROQ_API_KEYS else os.getenv("GROQ_API_KEY")
        if not groq_api_key:
            logger.warning("No Groq API key available for notion_workflow LLM Agent.")
            return None

        client = AsyncGroq(api_key=groq_api_key)

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
                response = await client.chat.completions.create(
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

                    # Execute NotionAgent asynchronous functions
                    if function_name == "add_database_page":
                        parent_id = function_args.get("parent_database_id")
                        p_type = await self.notion_agent.get_id_type(parent_id)
                        parent = {"type": f"{p_type}_id", f"{p_type}_id": parent_id}
                        
                        properties = function_args.get("properties", {})
                        if p_type == "page":
                            title_val = ""
                            # Extract title from properties
                            for k, v in properties.items():
                                if isinstance(v, dict) and "title" in v:
                                    title_val = v["title"]
                                    break
                            if not title_val:
                                title_val = function_args.get("title", "")
                            
                            if isinstance(title_val, list):
                                properties = {"title": title_val}
                            else:
                                properties = {"title": [{"text": {"content": str(title_val)}}]}
                        
                        result = await self.notion_agent.create_page(parent, properties)
                    elif function_name == "update_page":
                        result = await self.notion_agent.update_page_properties(
                            function_args.get("page_id"), 
                            function_args.get("properties", {})
                        )
                    elif function_name == "query_database":
                        result = await self.notion_agent.query_database(
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

    async def build_workspace_architecture(self, chat_id: Optional[str] = None):
        """Builds workspace architecture programmatically for a specific user."""
        if chat_id:
            self.set_user_credentials(chat_id)

        # Skip building architecture if the active item is a database, as we cannot nest databases/pages under a database parent
        if getattr(self.notion_agent, "active_item_type", "database") == "database":
            logger.info("Active attached item is a database. Skipping workspace architecture build.")
            return

        logger.info("Building workspace architecture programmatically...")
        root_id = self.notion_agent.parent_page_id
        if not root_id:
            logger.warning("No parent page ID configured. Skipping architecture build.")
            return

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
        
        # Create the raw Tasks DB
        tasks_id = await self._ensure_database("☑️ Tasks and To Dos", root_id, TASKS_SCHEMA)

        logger.info("Workspace architecture verified/built successfully.")

    # =====================================================================
    # LLM EXECUTION METHODS
    # =====================================================================

    async def ensure_database_exists(self, db_type: str, chat_id: Optional[str] = None) -> Dict[str, str]:
        """Resolves target database metadata, building the workspace architecture if missing."""
        if chat_id:
            self.set_user_credentials(chat_id)
        await self.build_workspace_architecture(chat_id=chat_id)
        mapping = {"capture": "📝 Notes & Capture", "projects": "Master Projects DB", "tasks": "☑️ Tasks and To Dos"}
        title = mapping.get(db_type, db_type)
        ids = await self.notion_agent.get_database_ids(title)
        return ids if ids else {"database_id": "mock", "data_source_id": "mock"}

    async def route_and_log_to_notion(self, text: str, intent: str, extracted_data: Dict[str, Any], emotion: str, chat_id: Optional[str] = None) -> Dict[str, Any]:
        """Runs the routing agent to record raw input inside the capture DB for a user."""
        if chat_id:
            self.set_user_credentials(chat_id)

        capture_ids = await self.notion_agent.get_database_ids("📝 Notes & Capture")
        capture_id = list(capture_ids.values())[0] if capture_ids else "UNKNOWN"
        
        # Fallback to user active database ID if "📝 Notes & Capture" is not found in cache/workspace
        if capture_id == "UNKNOWN" and hasattr(self.notion_agent, "active_database_id") and self.notion_agent.active_database_id:
            capture_id = self.notion_agent.active_database_id

        prompt = (
            f"New user input: '{text}'. Extracted Data: {extracted_data}. "
            f"ACTION: Insert this into the Capture Database (ID: {capture_id})."
        )
        logger.info(f"NotionWorkflow LLM: Routing raw input to Capture...")
        await self._run_groq_agent(ROUTING_PROMPT, prompt)
        return {"id": "llm-handled", "url": "notion.so"}

    async def run_automations(self, chat_id: int):
        """Runs the automation agent tasks (Sort & Synthesize) for a user."""
        self.set_user_credentials(chat_id)
            
        logger.info("NotionWorkflow LLM: Running Internal Automations (Sort & Synthesize)...")
        await self._run_groq_agent(AUTOMATION_PROMPT, "Start the Phase 2 and Phase 3 internal review loops.")

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