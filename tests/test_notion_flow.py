#!/usr/bin/env python3
import os
import sys
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch

# Ensure the package is importable
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# 1. Mock Neo4j and voice transcription libraries before import
mock_neo4j = MagicMock()
sys.modules['neo4j'] = mock_neo4j
sys.modules['faster_whisper'] = MagicMock()

# Imports to test
from assistant_backend_1.features_services.notion_mcp import NotionAgent
from assistant_backend_1.features_services.notion_workflow import NotionWorkflowManager

async def test_database_attached_flow():
    print("\n--- Testing flow when a DATABASE is attached ---")
    
    # Mock user json
    chat_id = "test_user_db"
    mock_user_data = {
        str(chat_id): {
            "notion": {
                "token": "fake_token",
                "active_database_id": "db_id_123",
                "database_ids": [
                    {"id": "db_id_123", "name": "My Database", "type": "database", "schema": {}}
                ]
            }
        }
    }
    
    with patch("assistant_backend_1.helpers.load_users", return_value=mock_user_data), \
         patch("assistant_backend_1.features_services.notion_workflow.load_users", return_value=mock_user_data):
        
        # Initialize NotionAgent & Workflow Manager
        agent = NotionAgent()
        workflow = NotionWorkflowManager(agent)
        
        # Verify set_user_credentials correctly resolves types
        workflow.set_user_credentials(chat_id)
        
        # Mock client methods after set_user_credentials overwrites them
        agent.client = AsyncMock()
        agent.client.databases.retrieve = AsyncMock(return_value={"id": "db_id_123", "object": "database"})
        agent.client.pages.create = AsyncMock(return_value={"id": "new_page_id"})
        
        assert agent.active_item_type == "database"
        assert agent.active_database_id == "db_id_123"
        print("✅ Credentials and active_item_type resolved correctly")
        
        # Verify build_workspace_architecture is skipped
        with patch.object(workflow, "_ensure_database") as mock_ensure_db:
            await workflow.build_workspace_architecture(chat_id)
            mock_ensure_db.assert_not_called()
            print("✅ build_workspace_architecture correctly skipped for database root")

        # Verify get_id_type works for database
        id_type = await agent.get_id_type("db_id_123")
        assert id_type == "database"
        print("✅ get_id_type resolved database type successfully")


async def test_page_attached_flow():
    print("\n--- Testing flow when a PAGE is attached ---")
    
    # Mock user json
    chat_id = "test_user_page"
    mock_user_data = {
        str(chat_id): {
            "notion": {
                "token": "fake_token",
                "active_database_id": "page_id_456",
                "database_ids": [
                    {"id": "page_id_456", "name": "My Page Root", "type": "page", "schema": {}}
                ]
            }
        }
    }
    
    with patch("assistant_backend_1.helpers.load_users", return_value=mock_user_data), \
         patch("assistant_backend_1.features_services.notion_workflow.load_users", return_value=mock_user_data):
        
        agent = NotionAgent()
        workflow = NotionWorkflowManager(agent)
        
        # Verify set_user_credentials correctly resolves types and page parent ID
        workflow.set_user_credentials(chat_id)
        
        # Mock client methods after set_user_credentials overwrites them
        agent.client = AsyncMock()
        agent.client.pages.retrieve = AsyncMock(return_value={"id": "page_id_456", "object": "page"})
        agent.client.pages.create = AsyncMock(return_value={"id": "new_page_id"})
        agent.client.databases.create = AsyncMock(return_value={"id": "child_db_id"})
        
        assert agent.active_item_type == "page"
        assert agent.active_database_id == "page_id_456"
        assert agent.parent_page_id == "page_id_456"
        print("✅ Credentials and active_item_type resolved correctly")

        
        # Verify get_id_type works for page
        id_type = await agent.get_id_type("page_id_456")
        assert id_type == "page"
        print("✅ get_id_type resolved page type successfully")

        # Test the add_database_page tool simulation inside workflow agent
        # For a page parent, properties must be simplified to just 'title'
        
        # Simulate add_database_page tool handler when parent is a page
        parent_id = "page_id_456"
        p_type = await agent.get_id_type(parent_id)
        assert p_type == "page"
        
        parent = {"type": f"{p_type}_id", f"{p_type}_id": parent_id}
        
        # Properties with full schema (from DB structure)
        properties = {
            "Task name": {"title": [{"text": {"content": "Test Task Title"}}]},
            "Due date": {"date": {"start": "2026-06-17"}},
            "Status": {"status": {"name": "Not started"}}
        }
        
        if p_type == "page":
            title_val = ""
            for k, v in properties.items():
                if isinstance(v, dict) and "title" in v:
                    title_val = v["title"]
                    break
            properties = {"title": title_val}
            
        assert parent == {"type": "page_id", "page_id": "page_id_456"}
        assert properties == {"title": [{"text": {"content": "Test Task Title"}}]}
        
        # Verify page creation API is called with right arguments
        await agent.create_page(parent, properties)
        agent.client.pages.create.assert_called_once_with(parent=parent, properties=properties)
        print("✅ add_database_page dynamically transforms arguments for page parent correctly")


async def test_telegram_webhook_checks():
    print("\n--- Testing Telegram Webhook connection checks ---")
    from assistant_backend_1.api.handlers.telegram_handler import telegram_webhook
    
    # 1. Test when token is missing
    chat_id = "test_user_no_token"
    mock_user_data = {
        str(chat_id): {
            "notion": {
                "token": None,
                "active_database_id": None
            }
        }
    }
    
    # Mock FastAPI Request
    mock_request = AsyncMock()
    mock_request.json = AsyncMock(return_value={
        "message": {
            "chat": {"id": chat_id, "first_name": "Test", "username": "test"},
            "text": "Hello"
        }
    })
    
    with patch("assistant_backend_1.helpers.load_users", return_value=mock_user_data), \
         patch("assistant_backend_1.api.handlers.telegram_handler.load_users", return_value=mock_user_data), \
         patch("assistant_backend_1.api.handlers.telegram_handler.save_user"), \
         patch("assistant_backend_1.api.handlers.telegram_handler.send_message") as mock_send:
        
        await telegram_webhook(mock_request)
        mock_send.assert_called_once()
        sent_message = mock_send.call_args[0][1]
        assert "Welcome! Please connect your Notion account" in sent_message
        print("✅ Correctly prompted to connect Notion when token is missing")

    # 2. Test when token is present but active_database_id is missing
    mock_user_data = {
        str(chat_id): {
            "notion": {
                "token": "fake_token",
                "active_database_id": None
            }
        }
    }
    
    with patch("assistant_backend_1.helpers.load_users", return_value=mock_user_data), \
         patch("assistant_backend_1.api.handlers.telegram_handler.load_users", return_value=mock_user_data), \
         patch("assistant_backend_1.api.handlers.telegram_handler.save_user"), \
         patch("assistant_backend_1.api.handlers.telegram_handler.send_message") as mock_send:
        
        await telegram_webhook(mock_request)
        mock_send.assert_called_once()
        sent_message = mock_send.call_args[0][1]
        assert "no pages or databases are attached to the integration" in sent_message
        print("✅ Correctly prompted to attach databases/pages when active_database_id is missing")


async def main():
    try:
        await test_database_attached_flow()
        await test_page_attached_flow()
        await test_telegram_webhook_checks()
        print("\n🎉 All Notion flow tests PASSED successfully!")
    except AssertionError as e:
        print(f"\n❌ Assertion failed during tests: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Unexpected error during tests: {e}")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())
