import os
from vanna import Agent
from vanna.core.registry import ToolRegistry
from vanna.core.user import UserResolver, User, RequestContext
from vanna.tools import RunSqlTool, VisualizeDataTool
from vanna.tools.agent_memory import SaveQuestionToolArgsTool, SearchSavedCorrectToolUsesTool, SaveTextMemoryTool
from vanna.servers.fastapi import VannaFastAPIServer
from vanna.integrations.openai import OpenAILlmService
from vanna.integrations.sqlite import SqliteRunner
from vanna.integrations.local.agent_memory import DemoAgentMemory
from vanna.integrations.anthropic import AnthropicLlmService
from vanna.integrations.ollama import OllamaLlmService
from vanna.integrations.google import GeminiLlmService

from vanna.integrations.mysql import MySQLRunner

from vanna.integrations.chromadb import ChromaAgentMemory
from vanna import Agent, AgentConfig
from fastapi.middleware.cors import CORSMiddleware


# Configure your LLM
llm = AnthropicLlmService(
    model="claude-sonnet-4-20250514",
    api_key=os.getenv("ANTHROPIC_API_KEY")
)
# llm = OpenAILlmService(
#     model="gpt-4o-mini",
#     api_key=""
# )
# llm = GeminiLlmService(
#     model="gemini-2.5-flash",
#     api_key=""
# )
# llm = OllamaLlmService(
#     model="llama3.1:8b",
#     api_key="http://localhost:11434"
# )


# Configure your database
# SQLITE_DB_PATH = "/home/define/Downloads/chinook.db"
# SQLITE_DB_PATH = "/home/define/Desktop/ui_v3/Studio21/backup/new/heroic/db/development.sqlite3"
# MYSQL_URI = "mysql+pymysql://root:@localhost/all_in_one"

# for mysql connection
# db_tool = RunSqlTool(
#     sql_runner=MySQLRunner(
#         host="localhost",
#         database="all_in_one",
#         user="vanna",
#         password="12345678", 
#         port=3306
#     )
# )

db_tool = RunSqlTool(
    sql_runner=MySQLRunner(
        host="164.52.192.171",
        database="all_in_one_clone",
        user="root",
        password="AllInOne2020!", 
        port=3306
    )
)



# for sqlite connction 
# db_tool = RunSqlTool(
#     sql_runner=SqliteRunner(database_path=SQLITE_DB_PATH)
# )

# Configure your agent memory
CHROMA_PERSIST_DIR = "/home/define/sql_chat" 
agent_memory = ChromaAgentMemory(
    persist_directory=CHROMA_PERSIST_DIR,
    collection_name="tool_memories"
)

config = AgentConfig(
    max_tool_iterations=50,
    stream_responses=True,
    auto_save_conversations=True
)

# Configure user authentication
class SimpleUserResolver(UserResolver):
    async def resolve_user(self, request_context: RequestContext) -> User:
        user_email = request_context.get_cookie('vanna_email') or 'guest@example.com'
        group = 'admin' if user_email == 'admin@example.com' else 'user'
        return User(id=user_email, email=user_email, group_memberships=[group])

user_resolver = SimpleUserResolver()

# Create your agent
tools = ToolRegistry()
tools.register_local_tool(db_tool, access_groups=['admin', 'user'])
tools.register_local_tool(SaveQuestionToolArgsTool(), access_groups=['admin'])
tools.register_local_tool(SearchSavedCorrectToolUsesTool(), access_groups=['admin', 'user'])
tools.register_local_tool(SaveTextMemoryTool(), access_groups=['admin', 'user'])
tools.register_local_tool(VisualizeDataTool(), access_groups=['admin', 'user'])

agent = Agent(
    llm_service=llm,
    tool_registry=tools,
    user_resolver=user_resolver,
    agent_memory=agent_memory,
    config=config
)


save_text_tool = SaveTextMemoryTool()

business_rules = """
Business Rules for Betting Analytics:

1. Only bets with status = 'settled' should be used in analytics.
2. Profit is calculated as coins_credited - stake.
3. Void or cancelled bets must be excluded.
4. coins_credited includes winnings plus stake return.
5. Use users.user_name to identify users in queries.
"""

agent_memory.save_text_memory(
    business_rules,
    "business_logic"
)

print("Business logic rules saved to memory.")


# Run the server
server = VannaFastAPIServer(agent)
# server.run()  # Access at http://localhost:8000
app = server.create_app()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8001"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Run with custom app
import uvicorn
uvicorn.run(app, host="0.0.0.0", port=8000)