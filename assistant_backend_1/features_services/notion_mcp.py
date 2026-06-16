import os
import logging
import json
import re
from typing import Dict, Any, List, Optional
from datetime import datetime
from notion_client import AsyncClient



logger = logging.getLogger(__name__)
__version__ = "1.0.0"

class NotionAgent:
    def __init__(self):
        logger.info(f"NotionAgent v{__version__} initializing...")
        self.token = os.getenv("NOTION_INTEGRATION_TOKEN")
        self.parent_page_id = os.getenv("NOTION_PAGE_ID")
        self.github_token = os.getenv("GITHUB_TOKEN")
        self.telegram_bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
        
        self.cache_file = "notion_cache.json"
        
        if not self.token or not self.parent_page_id:
            logger.warning("Notion credentials not fully set. Notion features will run in mock mode.")
            self.client = None
        else:
            # Clean up page ID (remove dashes, make lowercase) and extract the 32-character hex string
            normalized_id = self.parent_page_id.replace("-", "").lower()
            match = re.search(r"([a-f0-9]{32})", normalized_id)
            if match:
                self.parent_page_id = match.group(1)
                logger.info(f"Extracted Notion Page ID: {self.parent_page_id}")
            else:
                logger.warning(f"Could not extract a valid 32-character hex Page ID from: {self.parent_page_id}")
            self.client = AsyncClient(auth=self.token)
            
        self.db_cache = self._load_cache()
        
        # Initialize lifecycle starting time if not present
        if "first_started_at" not in self.db_cache:
            self.db_cache["first_started_at"] = datetime.utcnow().isoformat()
            self._save_cache()
            
        # Initialize last run timestamp for lazy trigger automations
        self.last_automation_run = None

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
    # SEARCH & RETRIEVAL
    # =====================================================================

    def _extract_title_from_object(self, obj: Dict[str, Any]) -> str:
        """Helper to extract plain text title from a Notion object."""
        title_obj = obj.get("title", [{}])
        if title_obj and isinstance(title_obj, list):
            return title_obj[0].get("plain_text", "").strip()
        return ""

    async def _find_page_ids_by_search(self, title: str) -> Optional[Dict[str, str]]:
        """Searches specifically for standard Pages (not databases) by title."""
        if not self.client:
            return None
        try:
            results = await self.client.search(query=title)
            for page in results.get("results", []):
                if page.get("object") == "page" and not page.get("archived", False):
                    props = page.get("properties", {})
                    for prop_name, prop_data in props.items():
                        if prop_data.get("type") == "title":
                            page_title = self._extract_title_from_object(prop_data)
                            if page_title == title.strip():
                                return {"page_id": page.get("id")}
            return None
        except Exception as e:
            logger.error(f"Error searching for page '{title}': {e}")
            return None

    async def get_page_ids(self, page_name: str) -> Optional[Dict[str, str]]:
        """Retrieves cached page ID, or searches the workspace if not found."""
        cache_key = f"page_{page_name}"
        if cache_key in self.db_cache:
            entry = self.db_cache[cache_key]
            if isinstance(entry, dict) and "page_id" in entry:
                try:
                    # Verify the page hasn't been deleted in Notion
                    page = await self.client.pages.retrieve(page_id=entry["page_id"])
                    if not page.get("archived", False):
                        return entry
                except Exception:
                    pass # Fall through to search if retrieval fails

        # Search fallback
        ids = await self._find_page_ids_by_search(page_name)
        if ids:
            self.db_cache[cache_key] = ids
            self._save_cache()
            return ids

        return None

    async def _get_title_property_name(self, database_id: str) -> str:
        """Retrieves the exact name of the title property of a database dynamically."""
        if not self.client:
            return "Name"
        try:
            db = await self.client.databases.retrieve(database_id=database_id)
            for k, v in db.get("properties", {}).items():
                if v.get("type") == "title":
                    return k
        except Exception as e:
            logger.error(f"Error getting title property for database {database_id}: {e}")
        return "Name"

    async def _find_database_ids_consistently(self, title: str) -> Optional[Dict[str, str]]:
        if not self.client:
            return None
        try:
            logger.info(f"Notion: Scanning parent page blocks consistently for active '{title}'...")
            start_cursor = None
            while True:
                response = await self.client.blocks.children.list(
                    block_id=self.parent_page_id,
                    start_cursor=start_cursor
                )
                for block in response.get("results", []):
                    if block.get("archived", False) or block.get("type") != "child_database":
                        continue
                        
                    db_id = block.get("id")
                    try:
                        db = await self.client.databases.retrieve(database_id=db_id)
                        if db.get("archived", False):
                            continue
                            
                        if self._extract_title_from_object(db) == title.strip():
                            data_sources = db.get("data_sources", [])
                            ds_id = data_sources[0].get("id") if data_sources else db_id
                            return {"database_id": db_id, "data_source_id": ds_id}
                    except Exception as e:
                        logger.error(f"Error retrieving database {db_id}: {e}")
                        
                if not response.get("has_more"):
                    break
                start_cursor = response.get("next_cursor")
            return None
        except Exception as e:
            logger.error(f"Error consistently listing child blocks: {e}")
            return None

    async def _find_database_ids_by_search(self, title: str) -> Optional[Dict[str, str]]:
        if not self.client:
            return None
        try:
            results = await self.client.search(query=title)
            for db in results.get("results", []):
                if db.get("object") == "database" and not db.get("archived", False):
                    if self._extract_title_from_object(db) == title.strip():
                        db_id = db.get("id")
                        data_sources = db.get("data_sources", [])
                        ds_id = data_sources[0].get("id") if data_sources else db_id
                        return {"database_id": db_id, "data_source_id": ds_id}
            return None
        except Exception as e:
            logger.error(f"Error searching for database '{title}': {e}")
            return None

    async def get_database_ids(self, db_name: str) -> Optional[Dict[str, str]]:
        """Retrieves cached database ID and data source ID, or searches if not found."""
        if db_name in self.db_cache:
            entry = self.db_cache[db_name]
            # Handle both dictionary caches and old string caches safely
            db_id = entry.get("database_id") if isinstance(entry, dict) else entry
            
            try:
                db = await self.client.databases.retrieve(database_id=db_id)
                if not db.get("archived", False):
                    data_sources = db.get("data_sources", [])
                    ds_id = data_sources[0].get("id") if data_sources else db_id
                    result = {"database_id": db_id, "data_source_id": ds_id}
                    
                    # Update cache if it was in the old string format
                    if not isinstance(entry, dict):
                        self.db_cache[db_name] = result
                        self._save_cache()
                        
                    return result
            except Exception:
                pass # Fall through if retrieval fails

        # Consistent block search
        ids = await self._find_database_ids_consistently(db_name)
        if ids:
            self.db_cache[db_name] = ids
            self._save_cache()
            return ids

        # Search fallback
        ids = await self._find_database_ids_by_search(db_name)
        if ids:
            self.db_cache[db_name] = ids
            self._save_cache()
            return ids

        return None

    async def resolve_data_source_id(self, database_id: str) -> str:
        """Helper to resolve the data_source_id for a database to comply with custom endpoint rules."""
        if not self.client:
            return database_id
        try:
            db = await self.client.databases.retrieve(database_id=database_id)
            data_sources = db.get("data_sources", [])
            return data_sources[0].get("id") if data_sources else database_id
        except Exception as e:
            logger.error(f"Error resolving data_source_id for {database_id}: {e}")
            return database_id

    async def get_id_type(self, object_id: str) -> str:
        """Determines if the object_id is a page or database."""
        # 1. Check user.json if we have chat_id
        chat_id = getattr(self, "chat_id", None)
        if chat_id:
            try:
                from assistant_backend_1.helpers import load_users
                users = load_users()
                user = users.get(str(chat_id), {})
                database_ids = user.get("notion", {}).get("database_ids", [])
                for db in database_ids:
                    if db.get("id") == object_id:
                        return db.get("type", "database")
            except Exception as e:
                logger.error(f"Error checking user database_ids for object_id type: {e}")

        # 2. Check db_cache values
        for k, entry in self.db_cache.items():
            if isinstance(entry, dict):
                if entry.get("database_id") == object_id:
                    return "database"
                if entry.get("page_id") == object_id:
                    return "page"
            elif entry == object_id:
                return "database"

        # 3. Query Notion API
        if self.client:
            try:
                await self.client.databases.retrieve(database_id=object_id)
                return "database"
            except Exception:
                try:
                    await self.client.pages.retrieve(page_id=object_id)
                    return "page"
                except Exception:
                    pass
        return "database" # default fallback


    # =====================================================================
    # GENERIC MCP TOOLS / CAPABILITIES
    # =====================================================================

    def _format_property_colors(self, properties: Dict[str, Any]):
        """Helper to clean select option colors: enforce gray instead of light_gray (Rule 3)"""
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

    async def create_database(self, parent_page_id: str, title: str, properties: Dict[str, Any]) -> Dict[str, Any]:
        """Exposes standard Notion API databases.create with validation fixes applied."""
        if not self.client:
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
                formatted_properties[prop_name] = prop_def

        self._format_property_colors(formatted_properties)

        try:
            logger.info(f"Notion Generic MCP: Creating database '{title}' under parent {parent_page_id}...")
            new_db = await self.client.databases.create(
                parent={"type": "page_id", "page_id": parent_page_id},
                title=[{"type": "text", "text": {"content": title}}],
                initial_data_source={
                    "title": title,
                    "properties": formatted_properties
                }
            )
            data_sources = new_db.get("data_sources", [])
            ds_id = data_sources[0].get("id") if data_sources else new_db.get("id")
            self.db_cache[title] = {"database_id": new_db.get("id"), "data_source_id": ds_id}
            self._save_cache()
            return new_db
        except Exception as e:
            logger.error(f"Notion Generic MCP: Failed to create database '{title}': {e}")
            raise e

    async def update_database(self, database_id: str, title: Optional[str] = None, properties: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Exposes standard Notion API databases.update with validation fixes applied."""
        if not self.client:
            logger.info(f"[MOCK MCP] Updating database: {database_id}")
            return {"id": database_id}
            
        payload = {}
        if title is not None:
            payload["title"] = [{"type": "text", "text": {"content": title}}]
        if properties is not None:
            self._format_property_colors(properties)
            payload["properties"] = properties

        try:
            logger.info(f"Notion Generic MCP: Updating database {database_id}...")
            return await self.client.databases.update(database_id=database_id, **payload)
        except Exception as e:
            logger.error(f"Notion Generic MCP: Failed to update database {database_id}: {e}")
            raise e

    async def retrieve_database(self, database_id: str) -> Dict[str, Any]:
        """Exposes standard Notion API databases.retrieve."""
        if not self.client:
            logger.info(f"[MOCK MCP] Retrieving database: {database_id}")
            return {"id": database_id, "properties": {}}
            
        try:
            logger.info(f"Notion Generic MCP: Retrieving database {database_id}...")
            return await self.client.databases.retrieve(database_id=database_id)
        except Exception as e:
            logger.error(f"Notion Generic MCP: Failed to retrieve database {database_id}: {e}")
            raise e

    async def query_database(self, database_id: str, filter: Optional[Dict[str, Any]] = None, sorts: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        """Exposes custom query databases endpoint using data_sources."""
        if not self.client:
            logger.info(f"[MOCK MCP] Querying database: {database_id}")
            return {"results": []}
            
        ds_id = await self.resolve_data_source_id(database_id)
        
        payload = {}
        if filter is not None:
            payload["filter"] = filter
        if sorts is not None:
            payload["sorts"] = sorts
            
        try:
            logger.info(f"Notion Generic MCP: Querying database via data source {ds_id}...")
            return await self.client.data_sources.query(data_source_id=ds_id, **payload)
        except Exception as e:
            logger.error(f"Notion Generic MCP: Failed to query database via data source {ds_id}: {e}")
            raise e

    async def create_page(self, parent: Dict[str, Any], properties: Dict[str, Any], children: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        """Exposes standard Notion API pages.create."""
        if not self.client:
            logger.info(f"[MOCK MCP] Creating page in parent {parent}")
            return {"id": "mock-page", "properties": properties}
            
        payload = {"parent": parent, "properties": properties}
        if children is not None:
            payload["children"] = children
            
        try:
            logger.info(f"Notion Generic MCP: Creating page under parent type '{parent.get('type')}'...")
            return await self.client.pages.create(**payload)
        except Exception as e:
            logger.error(f"Notion Generic MCP: Failed to create page: {e}")
            raise e

    async def retrieve_page(self, page_id: str) -> Dict[str, Any]:
        """Exposes standard Notion API pages.retrieve."""
        if not self.client:
            logger.info(f"[MOCK MCP] Retrieving page: {page_id}")
            return {"id": page_id}
            
        try:
            logger.info(f"Notion Generic MCP: Retrieving page {page_id}...")
            return await self.client.pages.retrieve(page_id=page_id)
        except Exception as e:
            logger.error(f"Notion Generic MCP: Failed to retrieve page {page_id}: {e}")
            raise e

    async def update_page_properties(self, page_id: str, properties: Dict[str, Any]) -> Dict[str, Any]:
        """Exposes standard Notion API pages.update to change property values."""
        if not self.client:
            logger.info(f"[MOCK MCP] Updating properties of page: {page_id}")
            return {"id": page_id}
            
        try:
            logger.info(f"Notion Generic MCP: Updating properties for page {page_id}...")
            return await self.client.pages.update(page_id=page_id, properties=properties)
        except Exception as e:
            logger.error(f"Notion Generic MCP: Failed to update page properties for {page_id}: {e}")
            raise e

    async def archive_page(self, page_id: str) -> Dict[str, Any]:
        """Exposes pages.update with archived=True to safely delete/archive pages."""
        if not self.client:
            logger.info(f"[MOCK MCP] Archiving page: {page_id}")
            return {"id": page_id}
            
        try:
            logger.info(f"Notion Generic MCP: Archiving page {page_id}...")
            return await self.client.pages.update(page_id=page_id, archived=True)
        except Exception as e:
            logger.error(f"Notion Generic MCP: Failed to archive page {page_id}: {e}")
            raise e

    async def append_block_children(self, block_id: str, children: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Exposes standard Notion API blocks.children.append."""
        if not self.client:
            logger.info(f"[MOCK MCP] Appending {len(children)} block children to block {block_id}")
            return {"results": []}
            
        try:
            logger.info(f"Notion Generic MCP: Appending {len(children)} blocks to block {block_id}...")
            return await self.client.blocks.children.append(block_id=block_id, children=children)
        except Exception as e:
            logger.error(f"Notion Generic MCP: Failed to append blocks to {block_id}: {e}")
            raise e

    async def delete_block(self, block_id: str) -> Dict[str, Any]:
        """Exposes standard Notion API blocks.delete."""
        if not self.client:
            logger.info(f"[MOCK MCP] Deleting block: {block_id}")
            return {"id": block_id}
            
        try:
            logger.info(f"Notion Generic MCP: Deleting block {block_id}...")
            return await self.client.blocks.delete(block_id=block_id)
        except Exception as e:
            logger.error(f"Notion Generic MCP: Failed to delete block {block_id}: {e}")
            raise e