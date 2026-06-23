import os
import logging
import json
from typing import Dict, Any, List, Optional
from datetime import datetime

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
        """
        if not chat_id:
            logger.info("No chat_id provided. Using default global agent credentials.")
            return

        try:
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

    # =====================================================================
    # GROQ AGENT WITH CLAUDE FALLBACK
    # =====================================================================

    async def _run_groq_agent(self, system_prompt: str, user_prompt: str) -> Optional[str]:
        """
        Executes an async tool-calling loop using Groq first.
        If all Groq keys fail, falls back to Claude via the Anthropic SDK.
        """
        result = await self._try_groq_agent(system_prompt, user_prompt)

        if result is None:
            logger.warning("[NotionWorkflow] Groq agent failed. Switching to Claude fallback...")
            result = await self._try_claude_agent(system_prompt, user_prompt)

        return result

    async def _try_groq_agent(self, system_prompt: str, user_prompt: str) -> Optional[str]:
        """
        Tries all available Groq API keys in sequence.
        Returns result string on success, None if all keys fail.
        """
        from assistant_backend_1.config import GROQ_API_KEYS
        from groq import AsyncGroq

        if not GROQ_API_KEYS:
            logger.warning("[NotionWorkflow] No Groq API keys configured.")
            return None

        tools = self._get_tool_definitions()

        for idx, api_key in enumerate(GROQ_API_KEYS):
            try:
                logger.info(f"[NotionWorkflow] Trying Groq key {idx + 1}/{len(GROQ_API_KEYS)}...")
                client = AsyncGroq(api_key=api_key)

                messages = [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ]

                for step in range(5):
                    response = await client.chat.completions.create(
                        model="llama-3.3-70b-versatile",
                        messages=messages,
                        tools=tools,
                        tool_choice="auto",
                        temperature=0
                    )

                    response_message = response.choices[0].message
                    messages.append(response_message)

                    if not response_message.tool_calls:
                        logger.info("[NotionWorkflow] Groq agent finished execution.")
                        return response_message.content

                    # Execute tool calls
                    for tool_call in response_message.tool_calls:
                        tool_result = await self._execute_tool_call(
                            tool_call.function.name,
                            json.loads(tool_call.function.arguments)
                        )
                        messages.append({
                            "tool_call_id": tool_call.id,
                            "role": "tool",
                            "name": tool_call.function.name,
                            "content": json.dumps(tool_result)
                        })

            except Exception as e:
                logger.error(f"[NotionWorkflow] Groq key {idx + 1} failed: {e}")
                continue  # try next key

        logger.warning("[NotionWorkflow] All Groq keys exhausted.")
        return None

    async def _try_claude_agent(self, system_prompt: str, user_prompt: str) -> Optional[str]:
        """
        Fallback agent using Claude via Anthropic SDK with tool calling.
        Mirrors the same tool-calling loop as Groq.
        """
        try:
            import anthropic

            claude_api_key = os.getenv("ANTHROPIC_API_KEY")
            if not claude_api_key:
                logger.error("[NotionWorkflow] ANTHROPIC_API_KEY not set. Claude fallback unavailable.")
                return None

            client = anthropic.AsyncAnthropic(api_key=claude_api_key)
            logger.info("[NotionWorkflow] Claude fallback agent starting...")

            # Convert tools to Anthropic format
            claude_tools = self._get_claude_tool_definitions()

            messages = [
                {"role": "user", "content": user_prompt}
            ]

            for step in range(5):
                response = await client.messages.create(
                    model="claude-sonnet-4-6",
                    max_tokens=1024,
                    temperature=0,
                    system=system_prompt,
                    tools=claude_tools,
                    messages=messages
                )

                # Check stop reason
                if response.stop_reason == "end_turn":
                    # Extract text response
                    for block in response.content:
                        if hasattr(block, "text"):
                            logger.info("[NotionWorkflow] Claude agent finished execution.")
                            return block.text
                    return None

                if response.stop_reason == "tool_use":
                    # Append assistant response to messages
                    messages.append({
                        "role": "assistant",
                        "content": response.content
                    })

                    # Process each tool call
                    tool_results = []
                    for block in response.content:
                        if block.type == "tool_use":
                            logger.info(f"[NotionWorkflow] Claude executing tool: {block.name}")
                            tool_result = await self._execute_tool_call(block.name, block.input)
                            tool_results.append({
                                "type": "tool_result",
                                "tool_use_id": block.id,
                                "content": json.dumps(tool_result)
                            })

                    # Append tool results as user message (Anthropic format)
                    messages.append({
                        "role": "user",
                        "content": tool_results
                    })

                else:
                    logger.warning(f"[NotionWorkflow] Unexpected Claude stop reason: {response.stop_reason}")
                    break

        except Exception as e:
            logger.error(f"[NotionWorkflow] Claude fallback agent failed: {e}")

        return None

    # =====================================================================
    # SHARED TOOL DEFINITIONS & EXECUTOR
    # =====================================================================

    def _get_tool_definitions(self) -> list:
        """Tool definitions in Groq/OpenAI format."""
        return [
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

    def _get_claude_tool_definitions(self) -> list:
        """
        Same tools but in Anthropic Claude format.
        Claude uses 'input_schema' instead of 'parameters'.
        """
        return [
            {
                "name": "add_database_page",
                "description": "Creates a new Notion Page (Row) inside a Database.",
                "input_schema": {
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
            },
            {
                "name": "update_page",
                "description": "Updates the properties of an existing Notion Page.",
                "input_schema": {
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
            },
            {
                "name": "query_database",
                "description": "Queries a Notion Database for existing pages.",
                "input_schema": {
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
        ]

    async def _execute_tool_call(self, function_name: str, function_args: dict) -> dict:
        """
        Shared tool executor used by both Groq and Claude agents.
        Handles all three tools: add_database_page, update_page, query_database.
        """
        try:
            if function_name == "add_database_page":
                parent_id = function_args.get("parent_database_id")
                p_type = await self.notion_agent.get_id_type(parent_id)
                parent = {"type": f"{p_type}_id", f"{p_type}_id": parent_id}

                properties = function_args.get("properties", {})

                if p_type == "page":
                    title_val = ""
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

                elif p_type == "database":
                    title_col = await self.notion_agent._get_title_property_name(parent_id)
                    existing_title_val = None
                    keys_to_remove = []
                    for k, v in list(properties.items()):
                        if isinstance(v, dict) and "title" in v:
                            existing_title_val = v["title"]
                            if k != title_col:
                                keys_to_remove.append(k)
                    for k in keys_to_remove:
                        del properties[k]
                    if not existing_title_val:
                        existing_title_val = function_args.get("title", "")
                    if isinstance(existing_title_val, list):
                        properties[title_col] = {"title": existing_title_val}
                    else:
                        properties[title_col] = {"title": [{"text": {"content": str(existing_title_val)}}]}

                return await self.notion_agent.create_page(parent, properties)

            elif function_name == "update_page":
                return await self.notion_agent.update_page_properties(
                    function_args.get("page_id"),
                    function_args.get("properties", {})
                )

            elif function_name == "query_database":
                return await self.notion_agent.query_database(
                    function_args.get("database_id"),
                    filter=function_args.get("filter")
                )

            else:
                return {"error": f"Unknown tool: {function_name}"}

        except Exception as e:
            logger.error(f"[NotionWorkflow] Tool execution error for '{function_name}': {e}")
            return {"error": str(e)}

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
        properties = {"title": {"title": [{"type": "text", "text": {"content": title}}]}}
        page = await self.notion_agent.create_page(parent, properties)
        return page.get("id")

    async def build_workspace_architecture(self, chat_id: Optional[str] = None):
        """Builds workspace architecture programmatically for a specific user."""
        if chat_id:
            self.set_user_credentials(chat_id)

        if getattr(self.notion_agent, "active_item_type", "database") == "database":
            logger.info("Active attached item is a database. Skipping workspace architecture build.")
            return

        logger.info("Building workspace architecture programmatically...")
        root_id = self.notion_agent.parent_page_id
        if not root_id:
            logger.warning("No parent page ID configured. Skipping architecture build.")
            return

        capture_id = await self._ensure_database("📝 Notes & Capture", root_id, CAPTURE_SCHEMA)
        capture_ds_id = await self.notion_agent.resolve_data_source_id(capture_id)

        organize_page_id = await self._ensure_page("🗂️ Areas Boards", root_id)

        area_ids = {}
        for area_name, specifics in AREA_SPECIFICS.items():
            schema = {**GLOBAL_AREA_SCHEMA, **specifics}
            schema["Source Capture Link"] = {"relation": {"database_id": capture_id, "data_source_id": capture_ds_id, "single_property": {}}}
            db_id = await self._ensure_database(area_name, organize_page_id, schema)
            area_ids[area_name] = db_id

        projects_page_id = await self._ensure_page("🚀 Project Directory", root_id)

        for area_name, area_id in area_ids.items():
            area_ds_id = await self.notion_agent.resolve_data_source_id(area_id)
            PROJECTS_SCHEMA[f"Related {area_name}"] = {"relation": {"database_id": area_id, "data_source_id": area_ds_id, "single_property": {}}}

        projects_id = await self._ensure_database("Master Projects DB", projects_page_id, PROJECTS_SCHEMA)
        projects_ds_id = await self.notion_agent.resolve_data_source_id(projects_id)

        TASKS_SCHEMA["Parent Project"] = {"relation": {"database_id": projects_id, "data_source_id": projects_ds_id, "single_property": {}}}
        await self._ensure_database("☑️ Tasks and To Dos", root_id, TASKS_SCHEMA)

        logger.info("Workspace architecture verified/built successfully.")

    # =====================================================================
    # LLM EXECUTION METHODS
    # =====================================================================

    async def ensure_database_exists(self, db_type: str, chat_id: Optional[str] = None) -> Dict[str, str]:
        if chat_id:
            self.set_user_credentials(chat_id)
        has_capture = "📝 Notes & Capture" in self.notion_agent.db_cache
        if not has_capture and getattr(self.notion_agent, "active_item_type", "database") != "database":
            await self.build_workspace_architecture(chat_id=chat_id)
        mapping = {"capture": "📝 Notes & Capture", "projects": "Master Projects DB", "tasks": "☑️ Tasks and To Dos"}
        title = mapping.get(db_type, db_type)
        ids = await self.notion_agent.get_database_ids(title)
        return ids if ids else {"database_id": "mock", "data_source_id": "mock"}

    async def get_all_database_ids(self, chat_id: Optional[str] = None) -> Dict[str, str]:
        if chat_id:
            self.set_user_credentials(chat_id)
        has_capture = "📝 Notes & Capture" in self.notion_agent.db_cache
        if not has_capture and getattr(self.notion_agent, "active_item_type", "database") != "database":
            await self.build_workspace_architecture(chat_id=chat_id)

        db_names = [
            "📝 Notes & Capture", "Health & Fitness", "Finance & Wealth",
            "Career & Professional", "Personal Growth & Learning",
            "Home & Lifestyle", "Master Projects DB", "☑️ Tasks and To Dos"
        ]

        ids = {}
        for name in db_names:
            db_info = await self.notion_agent.get_database_ids(name)
            if db_info:
                ids[name] = db_info.get("database_id")
            else:
                cache_entry = self.notion_agent.db_cache.get(name)
                if cache_entry:
                    ids[name] = cache_entry.get("database_id") if isinstance(cache_entry, dict) else cache_entry
                else:
                    ids[name] = None

        if not ids.get("📝 Notes & Capture") and getattr(self.notion_agent, "active_item_type", "database") == "database":
            ids["📝 Notes & Capture"] = getattr(self.notion_agent, "active_database_id", None)

        return ids

    async def route_and_log_to_notion(self, text: str, intent: str, extracted_data: Dict[str, Any], emotion: str, chat_id: Optional[str] = None) -> Dict[str, Any]:
        """Runs the routing agent to record raw input inside the capture DB for a user."""
        if chat_id:
            self.set_user_credentials(chat_id)
            has_capture = "📝 Notes & Capture" in self.notion_agent.db_cache
            if not has_capture and getattr(self.notion_agent, "active_item_type", "database") != "database":
                await self.build_workspace_architecture(chat_id)

        capture_ids = await self.notion_agent.get_database_ids("📝 Notes & Capture")
        capture_id = list(capture_ids.values())[0] if capture_ids else "UNKNOWN"

        if capture_id == "UNKNOWN" and hasattr(self.notion_agent, "active_database_id") and self.notion_agent.active_database_id:
            capture_id = self.notion_agent.active_database_id

        import pytz
        berlin_tz = pytz.timezone("Europe/Berlin")
        now_berlin = datetime.now(berlin_tz)
        current_time_str = now_berlin.strftime("%Y-%m-%dT%H:%M:%S%z")
        if len(current_time_str) > 19 and current_time_str[-2] != ":":
            current_time_str = current_time_str[:-2] + ":" + current_time_str[-2:]

        schema_description = f"""
Database Schema Reference for '📝 Notes & Capture':
- Title Column: 'Content/Message' (MUST contain the user's raw input / text)
- Date Columns: 
  - 'Capture Timestamp': set to the current timestamp ({current_time_str}) in standard shape: {{"date": {{"start": "{current_time_str}"}}}}
  - 'Reminder Date/Time': set if a specific reminder date/time is extracted in shape: {{"date": {{"start": "ISO-Date-String"}}}}
- Checkbox Column: 'Set Reminder?' (set to true if 'Reminder Date/Time' is present, otherwise false, in shape: {{"checkbox": true/false}})
- Select Columns:
  - 'Processed Status': MUST be 'Unprocessed' (shape: {{"select": {{"name": "Unprocessed"}}}})
  - 'Proposed Area (AI)': Deduces the most relevant area (shape: {{"select": {{"name": "OptionName"}}}}). Options: 'Health & Fitness', 'Finance & Wealth', 'Career & Professional', 'Personal Growth', 'Home & Lifestyle'
  - 'Input Type': Deduces the format (shape: {{"select": {{"name": "OptionName"}}}}). Options: 'Text', 'Link', 'Voice Note', 'Image'
  - 'Actionability': Deduces action level (shape: {{"select": {{"name": "OptionName"}}}}). Options: 'Actionable Task', 'Reference Only', 'Someday/Maybe'
- Rich Text Column: 'Proposed Project (AI)' (deduces a short project title if input is actionable, otherwise empty, in shape: {{"rich_text": [{{"text": {{"content": "project title"}}}}]}})
"""

        system_prompt = ROUTING_PROMPT + "\n\n" + schema_description
        prompt = (
            f"Current Timestamp: {current_time_str}\n"
            f"New user input: '{text}'\n"
            f"Extracted Data from LLM Conversation: {json.dumps(extracted_data)}\n"
            f"ACTION: Create a page in the Capture Database (ID: {capture_id}) using the `add_database_page` tool."
        )

        logger.info("NotionWorkflow LLM: Routing raw input to Capture...")
        await self._run_groq_agent(system_prompt, prompt)
        return {"id": "llm-handled", "url": "notion.so"}

    async def run_automations(self, chat_id: int):
        """Runs the automation agent tasks (Sort & Synthesize) for a user."""
        self.set_user_credentials(chat_id)

        if getattr(self.notion_agent, "active_item_type", "database") == "database":
            logger.info("Active attached item is a database. Skipping automations.")
            return

        logger.info("NotionWorkflow LLM: Running Internal Automations (Sort & Synthesize)...")

        db_ids = await self.get_all_database_ids(str(chat_id))
        db_info_str = "\n".join([f"- '{name}': {db_id}" for name, db_id in db_ids.items() if db_id])

        schema_info = """
Database Schema Reference:
1. '📝 Notes & Capture':
   Properties:
   - 'Content/Message': title
   - 'Processed Status': select (options: 'Unprocessed', 'Moved to Area', 'Archived')
   - 'Proposed Area (AI)': select
   - 'Proposed Project (AI)': rich_text
   - 'Input Type': select
   - 'Actionability': select

2. Area Databases ('Health & Fitness', 'Finance & Wealth', 'Career & Professional', 'Personal Growth & Learning', 'Home & Lifestyle'):
   Properties:
   - 'Name': title
   - 'Date Logged': date
   - 'AI Executive Summary': rich_text
   - 'Source Capture Link': relation

3. 'Master Projects DB':
   Properties:
   - 'Project Name': title
   - 'Status': select (options: 'Proposed', 'Active', 'Paused', 'Completed')
   - 'Target Deadline': date
   - 'Progress Bar': number

4. '☑️ Tasks and To Dos':
   Properties:
   - 'Task Name': title
   - 'Execution Date': date
   - 'Criticality': select (options: 'P1 - Critical', 'P2 - Important', 'P3 - Minor')
   - 'Parent Project': relation
"""

        system_prompt = (
            AUTOMATION_PROMPT +
            f"\n\nActive Notion Database IDs for this user:\n{db_info_str}\n" +
            schema_info
        )

        await self._run_groq_agent(system_prompt, "Start the Phase 2 and Phase 3 internal review loops.")

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