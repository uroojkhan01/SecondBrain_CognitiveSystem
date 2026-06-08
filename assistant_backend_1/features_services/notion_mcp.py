# assistant_backend_1/features_services/notion_mcp.py

import os
import logging
import json
import re
import requests
import pytz
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta

# Import only what is actually present in helpers
from assistant_backend_1.helpers import load_users

logger = logging.getLogger(__name__)
__version__ = "1.0.0"

# =====================================================================
# CREDENTIALS & SCHEMA HELPERS (Ported from notion.py)
# =====================================================================

def get_user_notion_credentials(chat_id: str):
    """Get token and active database id for a user from user settings."""
    users = load_users()
    user = users.get(str(chat_id), {})
    notion = user.get("notion", {})
    token = notion.get("token")
    database_id = notion.get("active_database_id")
    return token, database_id


def get_active_database_schema(chat_id: str) -> dict:
    """Get schema of user's active database."""
    users = load_users()
    user = users.get(str(chat_id), {})
    notion = user.get("notion", {})
    active_id = notion.get("active_database_id")
    database_ids = notion.get("database_ids", [])
    
    for db in database_ids:
        if db["id"] == active_id:
            return db.get("schema", {})
    
    return {}


def get_column_name(schema: dict, col_type: str) -> str:
    """Find column name by type from schema."""
    for col_name, col_type_val in schema.items():
        if col_type_val == col_type:
            return col_name
    return None

# =====================================================================
# DATE & TIMEZONE HELPERS (Ported from notion.py)
# =====================================================================

def get_notion_workspace_timezone(token: str, database_id: str) -> str:
    """
    Fetch timezone from Notion database settings.
    Falls back to Europe/Berlin or UTC if not found.
    Queries the database metadata endpoint: GET /v1/databases/{database_id}
    """
    url = f"https://api.notion.com/v1/databases/{database_id}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Notion-Version": "2022-06-28"
    }
    try:
        response = requests.get(url, headers=headers)
        data = response.json()
        print(f"🔍 Full Notion DB response: {data}")
        tz = (
            data.get("properties", {})
                .get("Due date", {})
                .get("date", {})
                .get("time_zone")
        )
        
        if tz:
            print(f"🌍 Notion timezone: {tz}")
            return tz
    except Exception as e:
        print(f"⚠️ Could not fetch timezone: {e}")

    return "Europe/Berlin"  # Aligned default fallback timezone


def parse_relative_time(due_str: str) -> str:
    """
    Convert relative time strings (e.g. "in 5 minutes", "tomorrow") to absolute ISO datetime.
    If the string is not relative, return it as is.
    """
    now = datetime.now()
    due_str_lower = due_str.lower().strip()

    # "in X minutes"
    match = re.match(r"in (\d+) minutes?", due_str_lower)
    if match:
        mins = int(match.group(1))
        result = (now + timedelta(minutes=mins)).strftime("%Y-%m-%dT%H:%M:%S")
        print(f"⏱ Relative time '{due_str}' → {result}")
        return result

    # "in X hours"
    match = re.match(r"in (\d+) hours?", due_str_lower)
    if match:
        hours = int(match.group(1))
        result = (now + timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%S")
        print(f"⏱ Relative time '{due_str}' → {result}")
        return result

    # "in X days"
    match = re.match(r"in (\d+) days?", due_str_lower)
    if match:
        days = int(match.group(1))
        result = (now + timedelta(days=days)).strftime("%Y-%m-%d")
        print(f"⏱ Relative time '{due_str}' → {result}")
        return result

    # "tomorrow"
    if "tomorrow" in due_str_lower:
        result = (now + timedelta(days=1)).strftime("%Y-%m-%d")
        print(f"⏱ Relative time '{due_str}' → {result}")
        return result

    # "tonight"
    if "tonight" in due_str_lower:
        result = now.strftime("%Y-%m-%d") + "T21:00:00"
        print(f"⏱ Relative time '{due_str}' → {result}")
        return result

    # "next week"
    if "next week" in due_str_lower:
        result = (now + timedelta(weeks=1)).strftime("%Y-%m-%d")
        print(f"⏱ Relative time '{due_str}' → {result}")
        return result

    return due_str  # not relative — return as is


def format_due_date_for_notion(due_str: str, token: str = None, database_id: str = None) -> Optional[str]:
    """
    Formats a date string into ISO 8601 offset format required by the Notion API.
    Localizes naive dates to 'Europe/Berlin' by default.
    """
    if not due_str:
        return None

    due_str = due_str.strip()
    due_str = parse_relative_time(due_str)

    try:
        if "T" in due_str:
            dt = datetime.fromisoformat(due_str)

            # If already has timezone offset → use directly, no conversion
            if dt.tzinfo is not None:
                print(f"✅ Already has timezone: {dt.isoformat()}")
                return dt.isoformat()

            # No timezone → fallback to Berlin
            print(f"⚠️ No timezone in string, applying Berlin fallback")
            tz = pytz.timezone("Europe/Berlin")
            dt = tz.localize(dt)
            return dt.isoformat()

        elif len(due_str) == 10 and due_str.count("-") == 2:
            # Date only → midnight Berlin
            tz = pytz.timezone("Europe/Berlin")
            dt = datetime.strptime(due_str, "%Y-%m-%d")
            dt = tz.localize(dt.replace(hour=0, minute=0, second=0))
            print(f"📅 Date-only → midnight Berlin: {dt.isoformat()}")
            return dt.isoformat()

        else:
            print(f"⚠️ Unrecognized date format: {due_str}")
            return None

    except Exception as e:
        print(f"❌ Error formatting date: {e}")
        return None


# =====================================================================
# MULTI-TENANT NOTION AGENT CLASS (Synchronous)
# =====================================================================

class NotionAgent:
    """
    Synchronous wrapper for executing operations against the Notion API.
    Supports multi-tenant authentication per user chat_id, falling back 
    to environment variables for a single-tenant layout.
    """
    def __init__(self, chat_id: Optional[str] = None):
        logger.info(f"NotionAgent v{__version__} initializing (chat_id: {chat_id})...")
        self.chat_id = str(chat_id) if chat_id else None
        
        # Load user credentials if chat_id is provided
        if self.chat_id:
            self.token, self.active_database_id = get_user_notion_credentials(self.chat_id)
        else:
            self.token = None
            self.active_database_id = None
            
        # Fallback to environment configuration if no user credentials exist
        if not self.token:
            self.token = os.getenv("NOTION_INTEGRATION_TOKEN")
        if not self.active_database_id:
            self.active_database_id = os.getenv("NOTION_PAGE_ID")
            
        self.parent_page_id = os.getenv("NOTION_PAGE_ID")
        self.github_token = os.getenv("GITHUB_TOKEN")
        self.telegram_bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
        
        # Setup isolated cache file to avoid multi-tenant data bleed
        if self.chat_id:
            self.cache_file = f"notion_cache_{self.chat_id}.json"
        else:
            self.cache_file = "notion_cache.json"
            
        # Clean up parent page ID if set (ensures 32-character hex format)
        if self.parent_page_id:
            normalized_id = self.parent_page_id.replace("-", "").lower()
            match = re.search(r"([a-f0-9]{32})", normalized_id)
            if match:
                self.parent_page_id = match.group(1)
                logger.info(f"Extracted Parent Notion Page ID: {self.parent_page_id}")
            else:
                logger.warning(f"Could not extract a valid 32-character hex Page ID from: {self.parent_page_id}")
                
        self.db_cache = self._load_cache()
        
        # Track initial startup timestamp in cache
        if "first_started_at" not in self.db_cache:
            self.db_cache["first_started_at"] = datetime.utcnow().isoformat()
            self._save_cache()
            
        self.last_automation_run = None

    # =====================================================================
    # REQUEST UTILITY
    # =====================================================================

    def _request(self, method: str, url: str, json_data: Optional[Dict[str, Any]] = None, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Sends a synchronous HTTP request to the Notion API.
        Includes authentication token and current Notion API version headers.
        """
        if not self.token:
            logger.error("Notion API call attempted but no token is available.")
            raise ValueError("Notion Integration Token not configured.")

        headers = {
            "Authorization": f"Bearer {self.token}",
            "Notion-Version": "2022-06-28",
            "Content-Type": "application/json"
        }

        try:
            logger.debug(f"Notion Request: {method} {url} | Params: {params}")
            response = requests.request(method, url, headers=headers, json=json_data, params=params)
            
            if response.status_code >= 400:
                logger.error(f"Notion API Error [{response.status_code}]: {response.text}")
                response.raise_for_status()
                
            return response.json()
        except Exception as e:
            logger.error(f"Failed Notion API request to {url}: {e}")
            raise e

    # =====================================================================
    # CACHE MANAGEMENT
    # =====================================================================

    def _load_cache(self) -> Dict[str, Any]:
        """Loads persistent database/page mapping cache from disk."""
        if os.path.exists(self.cache_file):
            try:
                with open(self.cache_file, "r") as f:
                    cache = json.load(f)
                    cleaned_cache = {k.strip(): v for k, v in cache.items()}
                    logger.info(f"Loaded {len(cleaned_cache)} cached items from {self.cache_file}")
                    return cleaned_cache
            except Exception as e:
                logger.error(f"Error loading Notion cache file: {e}")
        return {}

    def _save_cache(self):
        """Saves persistent mapping cache to disk."""
        try:
            with open(self.cache_file, "w") as f:
                cleaned_cache = {k.strip(): v for k, v in self.db_cache.items()}
                json.dump(cleaned_cache, f, indent=2)
                logger.info(f"Saved cache to {self.cache_file}")
        except Exception as e:
            logger.error(f"Error saving Notion cache file: {e}")

    # =====================================================================
    # SEARCH & RETRIEVAL HELPERS
    # =====================================================================

    def _extract_title_from_object(self, obj: Dict[str, Any]) -> str:
        """Helper to extract plain text title from a Notion object."""
        # Check standard titles (databases often have "title" key containing richtext)
        title_obj = obj.get("title", [])
        if title_obj and isinstance(title_obj, list):
            return title_obj[0].get("plain_text", "").strip()
            
        # Pages or details can hold properties
        properties = obj.get("properties", {})
        for prop in properties.values():
            if prop.get("type") == "title":
                items = prop.get("title", [])
                if items and isinstance(items, list):
                    return items[0].get("plain_text", "").strip()
        return ""

    def _find_page_ids_by_search(self, title: str) -> Optional[Dict[str, str]]:
        """Searches specifically for standard Pages (not databases) by title."""
        if not self.token:
            return None
        try:
            url = "https://api.notion.com/v1/search"
            payload = {
                "query": title,
                "filter": {"property": "object", "value": "page"}
            }
            results = self._request("POST", url, json_data=payload)
            for page in results.get("results", []):
                if not page.get("archived", False):
                    # Check properties title
                    props = page.get("properties", {})
                    for prop_data in props.values():
                        if prop_data.get("type") == "title":
                            page_title = self._extract_title_from_object(prop_data)
                            if page_title == title.strip():
                                return {"page_id": page.get("id")}
            return None
        except Exception as e:
            logger.error(f"Error searching for page '{title}': {e}")
            return None

    def get_page_ids(self, page_name: str) -> Optional[Dict[str, str]]:
        """Retrieves cached page ID, or searches the workspace if not found."""
        cache_key = f"page_{page_name}"
        if cache_key in self.db_cache:
            entry = self.db_cache[cache_key]
            if isinstance(entry, dict) and "page_id" in entry:
                try:
                    # Verify the page hasn't been deleted in Notion
                    page = self.retrieve_page(entry["page_id"])
                    if not page.get("archived", False):
                        return entry
                except Exception:
                    pass # Fall through to search if retrieval fails

        # Search fallback
        ids = self._find_page_ids_by_search(page_name)
        if ids:
            self.db_cache[cache_key] = ids
            self._save_cache()
            return ids

        return None

    def _get_title_property_name(self, database_id: str) -> str:
        """Retrieves the exact name of the title property of a database dynamically."""
        if not self.token:
            return "Name"
        try:
            db = self.retrieve_database(database_id)
            for k, v in db.get("properties", {}).items():
                if v.get("type") == "title":
                    return k
        except Exception as e:
            logger.error(f"Error getting title property for database {database_id}: {e}")
        return "Name"

    def _find_database_ids_consistently(self, title: str) -> Optional[Dict[str, str]]:
        """Lists page block children recursively to identify child database IDs consistently."""
        if not self.token or not self.parent_page_id:
            return None
        try:
            logger.info(f"Notion: Scanning parent page blocks consistently for active '{title}'...")
            start_cursor = None
            while True:
                url = f"https://api.notion.com/v1/blocks/{self.parent_page_id}/children"
                params = {}
                if start_cursor:
                    params["start_cursor"] = start_cursor
                    
                response = self._request("GET", url, params=params)
                for block in response.get("results", []):
                    if block.get("archived", False) or block.get("type") != "child_database":
                        continue
                        
                    db_id = block.get("id")
                    try:
                        db = self.retrieve_database(db_id)
                        if db.get("archived", False):
                            continue
                            
                        if self._extract_title_from_object(db) == title.strip():
                            return {"database_id": db_id, "data_source_id": db_id}
                    except Exception as e:
                        logger.error(f"Error retrieving database {db_id}: {e}")
                        
                if not response.get("has_more"):
                    break
                start_cursor = response.get("next_cursor")
            return None
        except Exception as e:
            logger.error(f"Error consistently listing child blocks: {e}")
            return None

    def _find_database_ids_by_search(self, title: str) -> Optional[Dict[str, str]]:
        """Finds database IDs using Notion's search endpoint."""
        if not self.token:
            return None
        try:
            url = "https://api.notion.com/v1/search"
            payload = {
                "query": title,
                "filter": {"property": "object", "value": "database"}
            }
            results = self._request("POST", url, json_data=payload)
            for db in results.get("results", []):
                if not db.get("archived", False):
                    if self._extract_title_from_object(db) == title.strip():
                        db_id = db.get("id")
                        return {"database_id": db_id, "data_source_id": db_id}
            return None
        except Exception as e:
            logger.error(f"Error searching for database '{title}': {e}")
            return None

    def get_database_ids(self, db_name: str) -> Optional[Dict[str, str]]:
        """Retrieves cached database ID and data source ID, or searches if not found."""
        if db_name in self.db_cache:
            entry = self.db_cache[db_name]
            # Handle both dictionary caches and old string caches safely
            db_id = entry.get("database_id") if isinstance(entry, dict) else entry
            
            try:
                db = self.retrieve_database(db_id)
                if not db.get("archived", False):
                    result = {"database_id": db_id, "data_source_id": db_id}
                    
                    # Update cache if it was in the old string format
                    if not isinstance(entry, dict):
                        self.db_cache[db_name] = result
                        self._save_cache()
                        
                    return result
            except Exception:
                pass # Fall through if retrieval fails

        # Try to locate by consistently searching child blocks
        ids = self._find_database_ids_consistently(db_name)
        if ids:
            self.db_cache[db_name] = ids
            self._save_cache()
            return ids

        # Fallback to search query
        ids = self._find_database_ids_by_search(db_name)
        if ids:
            self.db_cache[db_name] = ids
            self._save_cache()
            return ids

        return None

    def resolve_data_source_id(self, database_id: str) -> str:
        """
        Helper to resolve the data_source_id.
        In standard public Notion API, the data_source_id is equal to database_id.
        """
        return database_id

    # =====================================================================
    # GENERIC MCP TOOLS / CAPABILITIES (Synchronous)
    # =====================================================================

    def _format_property_colors(self, properties: Dict[str, Any]):
        """Helper to clean select option colors: enforce gray instead of light_gray."""
        for prop_def in properties.values():
            if "select" in prop_def:
                opts = prop_def["select"].get("options", [])
                for opt in opts:
                    if opt.get("color") == "light_gray":
                        opt["color"] = "gray"
            elif "multi_select" in prop_def:
                opts = prop_def["multi_select"].get("options", [])
                for opt in opts:
                    if opt.get("color") == "light_gray":
                        opt["color"] = "gray"

    def create_database(self, parent_page_id: str, title: str, properties: Dict[str, Any]) -> Dict[str, Any]:
        """
        Creates a new Notion Database as a child of a page.
        Endpoint: POST /v1/databases
        """
        if not self.token:
            logger.info(f"[MOCK MCP] Creating database: {title}")
            return {"id": "mock-db", "properties": properties}
            
        formatted_properties = {}
        for prop_name, prop_def in properties.items():
            if isinstance(prop_def, str):
                prop_str = prop_def.lower()
                if "title" in prop_str:
                    formatted_properties[prop_name] = {"title": {}}
                elif "multi" in prop_str:
                    formatted_properties[prop_name] = {"multi_select": {"options": []}}
                elif "select" in prop_str:
                    formatted_properties[prop_name] = {"select": {"options": []}}
                elif "date" in prop_str:
                    formatted_properties[prop_name] = {"date": {}}
                elif "checkbox" in prop_str:
                    formatted_properties[prop_name] = {"checkbox": {}}
                elif "number" in prop_str:
                    formatted_properties[prop_name] = {"number": {"format": "number"}}
                else:
                    formatted_properties[prop_name] = {"rich_text": {}}
            else:
                # Clean up relation properties for standard Notion API compatibility
                if isinstance(prop_def, dict) and "relation" in prop_def:
                    rel_def = prop_def["relation"]
                    db_id = rel_def.get("database_id") or rel_def.get("data_source_id")
                    formatted_properties[prop_name] = {
                        "relation": {
                            "database_id": db_id
                        }
                    }
                else:
                    formatted_properties[prop_name] = prop_def

        self._format_property_colors(formatted_properties)

        try:
            logger.info(f"Notion: Creating database '{title}' under page {parent_page_id}...")
            url = "https://api.notion.com/v1/databases"
            
            # Standard public API uses 'properties', not 'initial_data_source'
            payload = {
                "parent": {"type": "page_id", "page_id": parent_page_id},
                "title": [{"type": "text", "text": {"content": title}}],
                "properties": formatted_properties
            }
            
            new_db = self._request("POST", url, json_data=payload)
            db_id = new_db.get("id")
            self.db_cache[title] = {"database_id": db_id, "data_source_id": db_id}
            self._save_cache()
            return new_db
        except Exception as e:
            logger.error(f"Notion: Failed to create database '{title}': {e}")
            raise e

    def update_database(self, database_id: str, title: Optional[str] = None, properties: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Updates database schema or title.
        Endpoint: PATCH /v1/databases/{database_id}
        """
        if not self.token:
            logger.info(f"[MOCK MCP] Updating database: {database_id}")
            return {"id": database_id}
            
        payload = {}
        if title is not None:
            payload["title"] = [{"type": "text", "text": {"content": title}}]
        if properties is not None:
            self._format_property_colors(properties)
            payload["properties"] = properties

        try:
            logger.info(f"Notion: Updating database {database_id}...")
            url = f"https://api.notion.com/v1/databases/{database_id}"
            return self._request("PATCH", url, json_data=payload)
        except Exception as e:
            logger.error(f"Notion: Failed to update database {database_id}: {e}")
            raise e

    def retrieve_database(self, database_id: str) -> Dict[str, Any]:
        """
        Fetches metadata and schema details of a database.
        Endpoint: GET /v1/databases/{database_id}
        """
        if not self.token:
            logger.info(f"[MOCK MCP] Retrieving database: {database_id}")
            return {"id": database_id, "properties": {}}
            
        try:
            logger.info(f"Notion: Retrieving database {database_id}...")
            url = f"https://api.notion.com/v1/databases/{database_id}"
            return self._request("GET", url)
        except Exception as e:
            logger.error(f"Notion: Failed to retrieve database {database_id}: {e}")
            raise e

    def query_database(self, database_id: str, filter: Optional[Dict[str, Any]] = None, sorts: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        """
        Queries database records matching criteria.
        Endpoint: POST /v1/databases/{database_id}/query
        """
        if not self.token:
            logger.info(f"[MOCK MCP] Querying database: {database_id}")
            return {"results": []}
            
        payload = {}
        if filter is not None:
            payload["filter"] = filter
        if sorts is not None:
            payload["sorts"] = sorts
            
        try:
            logger.info(f"Notion: Querying database {database_id}...")
            url = f"https://api.notion.com/v1/databases/{database_id}/query"
            return self._request("POST", url, json_data=payload)
        except Exception as e:
            logger.error(f"Notion: Failed to query database {database_id}: {e}")
            raise e

    def create_page(self, parent: Dict[str, Any], properties: Dict[str, Any], children: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        """
        Creates a new Page or Database Row.
        Endpoint: POST /v1/pages
        """
        if not self.token:
            logger.info(f"[MOCK MCP] Creating page in parent {parent}")
            return {"id": "mock-page", "properties": properties}
            
        payload = {"parent": parent, "properties": properties}
        if children is not None:
            payload["children"] = children
            
        try:
            logger.info(f"Notion: Creating page under parent type '{parent.get('type')}'...")
            url = "https://api.notion.com/v1/pages"
            return self._request("POST", url, json_data=payload)
        except Exception as e:
            logger.error(f"Notion: Failed to create page: {e}")
            raise e

    def retrieve_page(self, page_id: str) -> Dict[str, Any]:
        """
        Fetches metadata of a page.
        Endpoint: GET /v1/pages/{page_id}
        """
        if not self.token:
            logger.info(f"[MOCK MCP] Retrieving page: {page_id}")
            return {"id": page_id}
            
        try:
            logger.info(f"Notion: Retrieving page {page_id}...")
            url = f"https://api.notion.com/v1/pages/{page_id}"
            return self._request("GET", url)
        except Exception as e:
            logger.error(f"Notion: Failed to retrieve page {page_id}: {e}")
            raise e

    def update_page_properties(self, page_id: str, properties: Dict[str, Any]) -> Dict[str, Any]:
        """
        Updates page property values.
        Endpoint: PATCH /v1/pages/{page_id}
        """
        if not self.token:
            logger.info(f"[MOCK MCP] Updating properties of page: {page_id}")
            return {"id": page_id}
            
        try:
            logger.info(f"Notion: Updating properties for page {page_id}...")
            url = f"https://api.notion.com/v1/pages/{page_id}"
            payload = {"properties": properties}
            return self._request("PATCH", url, json_data=payload)
        except Exception as e:
            logger.error(f"Notion: Failed to update page properties for {page_id}: {e}")
            raise e

    def archive_page(self, page_id: str) -> Dict[str, Any]:
        """
        Safely deletes/archives a page.
        Endpoint: PATCH /v1/pages/{page_id}
        """
        if not self.token:
            logger.info(f"[MOCK MCP] Archiving page: {page_id}")
            return {"id": page_id}
            
        try:
            logger.info(f"Notion: Archiving page {page_id}...")
            url = f"https://api.notion.com/v1/pages/{page_id}"
            payload = {"archived": True}
            return self._request("PATCH", url, json_data=payload)
        except Exception as e:
            logger.error(f"Notion: Failed to archive page {page_id}: {e}")
            raise e

    def append_block_children(self, block_id: str, children: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Appends content blocks as children of another block.
        Endpoint: PATCH /v1/blocks/{block_id}/children
        """
        if not self.token:
            logger.info(f"[MOCK MCP] Appending {len(children)} block children to block {block_id}")
            return {"results": []}
            
        try:
            logger.info(f"Notion: Appending {len(children)} blocks to block {block_id}...")
            url = f"https://api.notion.com/v1/blocks/{block_id}/children"
            payload = {"children": children}
            return self._request("PATCH", url, json_data=payload)
        except Exception as e:
            logger.error(f"Notion: Failed to append blocks to {block_id}: {e}")
            raise e

    def delete_block(self, block_id: str) -> Dict[str, Any]:
        """
        Deletes a content block.
        Endpoint: DELETE /v1/blocks/{block_id}
        """
        if not self.token:
            logger.info(f"[MOCK MCP] Deleting block: {block_id}")
            return {"id": block_id}
            
        try:
            logger.info(f"Notion: Deleting block {block_id}...")
            url = f"https://api.notion.com/v1/blocks/{block_id}"
            return self._request("DELETE", url)
        except Exception as e:
            logger.error(f"Notion: Failed to delete block {block_id}: {e}")
            raise e