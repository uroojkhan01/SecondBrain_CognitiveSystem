import logging
import json
import re
from typing import Dict, Any, List, Optional
from datetime import datetime
from notion_client import AsyncClient

logger = logging.getLogger(__name__)

class NotionAgent:
    def __init__(self):
        """
        Starts with no credentials.
        Credentials are always set per-user via set_credentials()
        called from NotionWorkflowManager.set_user_credentials()
        """
        self.token = None
        self.client = None
        self.chat_id = None
        self.active_database_id = None
        self.active_item_type = "database"
        self.parent_page_id = None
        self.db_cache = {}
        self.cache_file = "notion_cache.json"
        logger.info("NotionAgent initialized — waiting for user credentials.")

    def set_credentials(self, token: str, database_id: str, chat_id: str, item_type: str = "database"):
        """
        Set credentials for a specific user.
        Called by NotionWorkflowManager.set_user_credentials() on every request.
        """
        self.token = token
        self.client = AsyncClient(auth=token)
        self.chat_id = chat_id
        self.active_database_id = database_id
        self.active_item_type = item_type
        self.cache_file = f"notion_cache_{chat_id}.json"
        self.db_cache = self._load_cache()

        if item_type == "page":
            self.parent_page_id = database_id

        logger.info(f"NotionAgent credentials set for user {chat_id}")

    # =====================================================================
    # CACHE MANAGEMENT
    # =====================================================================

    def _load_cache(self) -> Dict[str, Any]:
        """Loads persistent database/page mapping cache from disk."""
        import os
        if os.path.exists(self.cache_file):
            try:
                with open(self.cache_file, "r") as f:
                    cache = json.load(f)
                    return {k.strip(): v for k, v in cache.items()}
            except Exception as e:
                logger.error(f"Error loading cache: {e}")
        return {}

    def _save_cache(self):
        """Saves persistent mapping cache to disk."""
        try:
            with open(self.cache_file, "w") as f:
                json.dump({k.strip(): v for k, v in self.db_cache.items()}, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving cache: {e}")

    # =====================================================================
    # SEARCH & RETRIEVAL
    # =====================================================================

    def _extract_title_from_object(self, obj: Dict[str, Any]) -> str:
        title_obj = obj.get("title", [{}])
        if title_obj and isinstance(title_obj, list):
            return title_obj[0].get("plain_text", "").strip()
        return ""

    async def _get_title_property_name(self, database_id: str) -> str:
        """Fetches the actual title column name of a database."""
        if not self.client:
            return "Name"
        try:
            db = await self.client.databases.retrieve(database_id=database_id)
            for k, v in db.get("properties", {}).items():
                if v.get("type") == "title":
                    return k
        except Exception as e:
            logger.error(f"Error getting title property for {database_id}: {e}")
        return "Name"

    async def get_database_ids(self, db_name: str) -> Optional[Dict[str, str]]:
        """Check cache first, then search Notion."""
        if not self.client:
            return None

        # Check cache
        if db_name in self.db_cache:
            entry = self.db_cache[db_name]
            db_id = entry.get("database_id") if isinstance(entry, dict) else entry
            try:
                db = await self.client.databases.retrieve(database_id=db_id)
                if not db.get("archived", False):
                    data_sources = db.get("data_sources", [])
                    ds_id = data_sources[0].get("id") if data_sources else db_id
                    return {"database_id": db_id, "data_source_id": ds_id}
            except Exception:
                pass

        # Search fallback
        try:
            results = await self.client.search(query=db_name)
            for db in results.get("results", []):
                if db.get("object") == "database" and not db.get("archived", False):
                    if self._extract_title_from_object(db) == db_name.strip():
                        db_id = db.get("id")
                        data_sources = db.get("data_sources", [])
                        ds_id = data_sources[0].get("id") if data_sources else db_id
                        result = {"database_id": db_id, "data_source_id": ds_id}
                        self.db_cache[db_name] = result
                        self._save_cache()
                        return result
        except Exception as e:
            logger.error(f"Error searching for database '{db_name}': {e}")

        return None

    async def get_page_ids(self, page_name: str) -> Optional[Dict[str, str]]:
        """Check cache first, then search Notion for pages."""
        if not self.client:
            return None

        cache_key = f"page_{page_name}"
        if cache_key in self.db_cache:
            entry = self.db_cache[cache_key]
            if isinstance(entry, dict) and "page_id" in entry:
                try:
                    page = await self.client.pages.retrieve(page_id=entry["page_id"])
                    if not page.get("archived", False):
                        return entry
                except Exception:
                    pass

        # Search fallback
        try:
            results = await self.client.search(query=page_name)
            for page in results.get("results", []):
                if page.get("object") == "page" and not page.get("archived", False):
                    props = page.get("properties", {})
                    for prop_data in props.values():
                        if prop_data.get("type") == "title":
                            if self._extract_title_from_object(prop_data) == page_name.strip():
                                result = {"page_id": page.get("id")}
                                self.db_cache[cache_key] = result
                                self._save_cache()
                                return result
        except Exception as e:
            logger.error(f"Error searching for page '{page_name}': {e}")

        return None

    async def resolve_data_source_id(self, database_id: str) -> str:
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
        """Determines if object_id belongs to a page or database."""
        # Check user.json first
        if self.chat_id:
            try:
                from assistant_backend_1.helpers import load_users
                users = load_users()
                database_ids = users.get(str(self.chat_id), {}).get("notion", {}).get("database_ids", [])
                for db in database_ids:
                    if db.get("id") == object_id:
                        return db.get("type", "database")
            except Exception as e:
                logger.error(f"Error checking user database_ids: {e}")

        # Check cache
        for entry in self.db_cache.values():
            if isinstance(entry, dict):
                if entry.get("database_id") == object_id:
                    return "database"
                if entry.get("page_id") == object_id:
                    return "page"

        # Ask Notion API
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

        return "database"

    # =====================================================================
    # CRUD OPERATIONS
    # =====================================================================

    def _format_property_colors(self, properties: Dict[str, Any]):
        """Enforce gray instead of light_gray for select options."""
        for prop_def in properties.values():
            for key in ("select", "multi_select"):
                if key in prop_def:
                    for opt in prop_def[key].get("options", []):
                        if opt.get("color") == "light_gray":
                            opt["color"] = "gray"

    async def create_database(self, parent_page_id: str, title: str, properties: Dict[str, Any]) -> Dict[str, Any]:
        if not self.client:
            return {"id": "mock-db"}

        formatted = {}
        for name, defn in properties.items():
            if isinstance(defn, str):
                d = defn.lower()
                if "title" in d:       formatted[name] = {"title": {}}
                elif "multi" in d:     formatted[name] = {"multi_select": {"options": []}}
                elif "select" in d:    formatted[name] = {"select": {"options": []}}
                elif "date" in d:      formatted[name] = {"date": {}}
                elif "checkbox" in d:  formatted[name] = {"checkbox": {}}
                elif "number" in d:    formatted[name] = {"number": {"format": "number"}}
                else:                  formatted[name] = {"rich_text": {}}
            else:
                formatted[name] = defn

        self._format_property_colors(formatted)

        try:
            new_db = await self.client.databases.create(
                parent={"type": "page_id", "page_id": parent_page_id},
                title=[{"type": "text", "text": {"content": title}}],
                initial_data_source={"title": title, "properties": formatted}
            )
            data_sources = new_db.get("data_sources", [])
            ds_id = data_sources[0].get("id") if data_sources else new_db.get("id")
            self.db_cache[title] = {"database_id": new_db.get("id"), "data_source_id": ds_id}
            self._save_cache()
            return new_db
        except Exception as e:
            logger.error(f"Failed to create database '{title}': {e}")
            raise

    async def update_database(self, database_id: str, title: Optional[str] = None, properties: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        if not self.client:
            return {"id": database_id}
        payload = {}
        if title:
            payload["title"] = [{"type": "text", "text": {"content": title}}]
        if properties:
            self._format_property_colors(properties)
            payload["properties"] = properties
        try:
            return await self.client.databases.update(database_id=database_id, **payload)
        except Exception as e:
            logger.error(f"Failed to update database {database_id}: {e}")
            raise

    async def retrieve_database(self, database_id: str) -> Dict[str, Any]:
        if not self.client:
            return {"id": database_id, "properties": {}}
        try:
            return await self.client.databases.retrieve(database_id=database_id)
        except Exception as e:
            logger.error(f"Failed to retrieve database {database_id}: {e}")
            raise

    async def query_database(self, database_id: str, filter: Optional[Dict[str, Any]] = None, sorts: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        if not self.client:
            return {"results": []}
        ds_id = await self.resolve_data_source_id(database_id)
        payload = {}
        if filter:
            payload["filter"] = filter
        if sorts:
            payload["sorts"] = sorts
        try:
            return await self.client.data_sources.query(data_source_id=ds_id, **payload)
        except Exception as e:
            logger.error(f"Failed to query database {database_id}: {e}")
            raise

    async def create_page(self, parent: Dict[str, Any], properties: Dict[str, Any], children: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        if not self.client:
            return {"id": "mock-page"}
        payload = {"parent": parent, "properties": properties}
        if children:
            payload["children"] = children
        try:
            return await self.client.pages.create(**payload)
        except Exception as e:
            logger.error(f"Failed to create page: {e}")
            raise

    async def retrieve_page(self, page_id: str) -> Dict[str, Any]:
        if not self.client:
            return {"id": page_id}
        try:
            return await self.client.pages.retrieve(page_id=page_id)
        except Exception as e:
            logger.error(f"Failed to retrieve page {page_id}: {e}")
            raise

    async def update_page_properties(self, page_id: str, properties: Dict[str, Any]) -> Dict[str, Any]:
        if not self.client:
            return {"id": page_id}
        try:
            return await self.client.pages.update(page_id=page_id, properties=properties)
        except Exception as e:
            logger.error(f"Failed to update page {page_id}: {e}")
            raise

    async def archive_page(self, page_id: str) -> Dict[str, Any]:
        if not self.client:
            return {"id": page_id}
        try:
            return await self.client.pages.update(page_id=page_id, in_trash=True)
        except Exception as e:
            logger.error(f"Failed to archive page {page_id}: {e}")
            raise

    async def append_block_children(self, block_id: str, children: List[Dict[str, Any]]) -> Dict[str, Any]:
        if not self.client:
            return {"results": []}
        try:
            return await self.client.blocks.children.append(block_id=block_id, children=children)
        except Exception as e:
            logger.error(f"Failed to append blocks to {block_id}: {e}")
            raise

    async def delete_block(self, block_id: str) -> Dict[str, Any]:
        if not self.client:
            return {"id": block_id}
        try:
            return await self.client.blocks.delete(block_id=block_id)
        except Exception as e:
            logger.error(f"Failed to delete block {block_id}: {e}")
            raise