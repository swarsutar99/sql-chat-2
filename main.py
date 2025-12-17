import os
import pymysql
from passlib.context import CryptContext

from fastapi import FastAPI, Form, Response, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from vanna import Agent, AgentConfig
from vanna.core.registry import ToolRegistry
from vanna.core.user import UserResolver, User, RequestContext
from vanna.tools import RunSqlTool, VisualizeDataTool
from vanna.tools.agent_memory import (
    SaveQuestionToolArgsTool,
    SearchSavedCorrectToolUsesTool,
    SaveTextMemoryTool,
)
from vanna.servers.fastapi import VannaFastAPIServer
from vanna.integrations.anthropic import AnthropicLlmService
from vanna.integrations.mysql import MySQLRunner
from vanna.integrations.chromadb import ChromaAgentMemory

import uvicorn

# -------------------------------------------------------------------
# PASSWORD HANDLING (Devise-compatible bcrypt)
# -------------------------------------------------------------------
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def verify_password(plain, hashed):
    return pwd_context.verify(plain, hashed)

# -------------------------------------------------------------------
# AUTH DB CONNECTION (Admins table)
# -------------------------------------------------------------------
def get_auth_db():
    return pymysql.connect(
        host="164.52.192.171",
        user="root",
        password="AllInOne2020!",
        database="all_in_one_clone",
        cursorclass=pymysql.cursors.DictCursor
    )

# -------------------------------------------------------------------
# LLM CONFIG
# -------------------------------------------------------------------
llm = AnthropicLlmService(
    model="claude-sonnet-4-20250514",
    api_key="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"
)

# -------------------------------------------------------------------
# DATABASE TOOL (for queries via Vanna)
# -------------------------------------------------------------------
db_tool = RunSqlTool(
    sql_runner=MySQLRunner(
        host="164.52.192.171",
        database="all_in_one_clone",
        user="root",
        password="AllInOne2020!",
        port=3306
    )
)

# -------------------------------------------------------------------
# AGENT MEMORY (Chroma)
# -------------------------------------------------------------------
CHROMA_PERSIST_DIR = os.getcwd()

agent_memory = ChromaAgentMemory(
    persist_directory=CHROMA_PERSIST_DIR,
    collection_name="tool_memories"
)

# -------------------------------------------------------------------
# AGENT CONFIG
# -------------------------------------------------------------------
config = AgentConfig(
    max_tool_iterations=50,
    stream_responses=True,
    auto_save_conversations=True
)

# -------------------------------------------------------------------
# USER RESOLVER (COOKIE BASED)
# -------------------------------------------------------------------
class SimpleUserResolver(UserResolver):
    async def resolve_user(self, request_context: RequestContext) -> User:
        email = request_context.get_cookie("vanna_email")

        if not email:
            # Prevent Vanna UI fallback login
            raise PermissionError("AUTH_REQUIRED")

        return User(
            id=email,
            email=email,
            group_memberships=["admin"]
        )


user_resolver = SimpleUserResolver()

# -------------------------------------------------------------------
# TOOLS
# -------------------------------------------------------------------
tools = ToolRegistry()
tools.register_local_tool(db_tool, access_groups=["admin"])
tools.register_local_tool(SaveQuestionToolArgsTool(), access_groups=["admin"])
tools.register_local_tool(SearchSavedCorrectToolUsesTool(), access_groups=["admin"])
tools.register_local_tool(SaveTextMemoryTool(), access_groups=["admin"])
tools.register_local_tool(VisualizeDataTool(), access_groups=["admin"])

# -------------------------------------------------------------------
# AGENT
# -------------------------------------------------------------------
agent = Agent(
    llm_service=llm,
    tool_registry=tools,
    user_resolver=user_resolver,
    agent_memory=agent_memory,
    config=config
)

# -------------------------------------------------------------------
# SAVE BUSINESS RULES
# -------------------------------------------------------------------
# agent_memory.save_text_memory(
#     """
#     Business Rules:
#     1. Use only settled bets.
#     2. Profit = coins_credited - stake.
#     3. Exclude cancelled/void bets.
#     """,
#     "business_logic"
# )

# -------------------------------------------------------------------
# FASTAPI SERVER
# -------------------------------------------------------------------
server = VannaFastAPIServer(agent)
app = server.create_app()

# -------------------------------------------------------------------
# CORS
# -------------------------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:8001",
        "http://0.0.0.0:8001"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -------------------------------------------------------------------
# LOGIN API
# -------------------------------------------------------------------
@app.post("/login")
async def login(
    response: Response,
    email: str = Form(...),
    password: str = Form(...)
):
    db = get_auth_db()
    try:
        with db.cursor() as cursor:
            cursor.execute(
                """
                SELECT email, encrypted_password, is_enabled
                FROM admins
                WHERE email=%s
                LIMIT 1
                """,
                (email,)
            )
            admin = cursor.fetchone()

        if not admin:
            raise HTTPException(status_code=401, detail="Invalid credentials")

        if admin["is_enabled"] != 1:
            raise HTTPException(status_code=403, detail="Account disabled")

        if not verify_password(password, admin["encrypted_password"]):
            raise HTTPException(status_code=401, detail="Invalid credentials")

        response.set_cookie(
            key="vanna_email",
            value=admin["email"],
            httponly=True,
            samesite="none",
            secure=False,   # localhost
            path="/"        # 
        )

        return {"status": "success"}

    finally:
        db.close()

# -------------------------------------------------------------------
# LOGOUT API
# -------------------------------------------------------------------
@app.post("/logout")
async def logout(response: Response):
    response.delete_cookie("vanna_email")
    return {"status": "logged_out"}

# -------------------------------------------------------------------
# RUN
# -------------------------------------------------------------------
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
