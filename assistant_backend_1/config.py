import os

# getting telegram bot tokens
if os.path.exists(".env"):
    # if we see the .env file, load it
    from dotenv import load_dotenv
    load_dotenv(".env")

# now we have them as a handy python strings!
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_BOT_USERNAME = os.getenv('TELEGRAM_BOT_USERNAME')
NOTION_CLIENT_ID = os.getenv('NOTION_CLIENT_ID')
NOTION_CLIENT_SECRET = os.getenv('NOTION_CLIENT_SECRET')
NOTION_REDIRECT_URI = os.getenv('NOTION_REDIRECT_URI')
GROQ_API_KEYS = [
    os.getenv(f'GROQ_API_KEY_{i}') for i in range(1, 6) if os.getenv(f'GROQ_API_KEY_{i}')
]
# Fallback to the single GROQ_API_KEY if the numbered ones are not provided
if not GROQ_API_KEYS and os.getenv('GROQ_API_KEY'):
    GROQ_API_KEYS = [os.getenv('GROQ_API_KEY')]
    
ANTHROPIC_API_KEY= os.getenv('ANTHROPIC_API_KEY')

# Neo4j
NEO4J_URI = os.getenv('NEO4J_URI')
NEO4J_USERNAME = os.getenv('NEO4J_USERNAME')
NEO4J_PASSWORD = os.getenv('NEO4J_PASSWORD')

# Feature Flags
ENABLE_LLM_API = os.getenv('ENABLE_LLM_API', 'false').lower() in ('true', '1', 't')

# Notion API
NOTION_VERSION = "2022-06-28"
