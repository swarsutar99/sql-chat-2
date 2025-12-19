import os
import pymysql
from passlib.context import CryptContext
import logging

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

from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi import Request


logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
)
logger = logging.getLogger("vanna-trace")

logger.info("Application starting...")
# -------------------------------------------------------------------
# PASSWORD HANDLING (Devise-compatible bcrypt)
# -------------------------------------------------------------------
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def verify_password(plain, hashed):
    logger.debug("Verifying password hash")
    return pwd_context.verify(plain, hashed)

# -------------------------------------------------------------------
# AUTH DB CONNECTION (Admins table)
# -------------------------------------------------------------------
def get_auth_db():
    logger.info("Opening auth DB connection")
    return pymysql.connect(
        host="localhost",
        user="vanna",
        password="12345678",
        database="all_in_one",
        cursorclass=pymysql.cursors.DictCursor
    )

# -------------------------------------------------------------------
# LLM CONFIG
# -------------------------------------------------------------------
logger.info("Initializing LLM service")
llm = AnthropicLlmService(
    model="claude-sonnet-4-20250514",
    api_key="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"
)

# -------------------------------------------------------------------
# DATABASE TOOL (for queries via Vanna)
# -------------------------------------------------------------------
# db_tool = RunSqlTool(
#     sql_runner=MySQLRunner(
#         host="164.52.192.171",
#         database="all_in_one_clone",
#         user="root",
#         password="AllInOne2020!",
#         port=3306
#     )
# )

# for mysql connection
class LoggingMySQLRunner(MySQLRunner):
    def run_sql(self, *args, **kwargs):
        # SQL is always the first positional argument
        sql = args[0] if args else kwargs.get("sql")

        logger.info("MySQLRunner.run_sql called")
        logger.debug(f"Generated SQL:\n{sql}")

        result = super().run_sql(*args, **kwargs)

        logger.info("SQL execution completed")
        logger.debug(f"SQL result rows: {result}")

        return result

        
db_tool = RunSqlTool(
    sql_runner=LoggingMySQLRunner(
        host="localhost",
        database="all_in_one",
        user="vanna",
        password="12345678", 
        port=3306
    )
)

# -------------------------------------------------------------------
# AGENT MEMORY (Chroma)
# -------------------------------------------------------------------
class LoggingChromaAgentMemory(ChromaAgentMemory):
    def save_text_memory(self, text: str, namespace: str):
        logger.info(f"Saving text memory (namespace={namespace})")
        logger.debug(f"Memory content:\n{text}")
        super().save_text_memory(text, namespace)

CHROMA_PERSIST_DIR = os.getcwd()

agent_memory = LoggingChromaAgentMemory(
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
logger.info("AgentConfig initialized")
# -------------------------------------------------------------------
# USER RESOLVER (COOKIE BASED)
# -------------------------------------------------------------------
class SimpleUserResolver(UserResolver):
    async def resolve_user(self, request_context: RequestContext) -> User:
        logger.info("Resolving user from request context")
        email = request_context.get_cookie("vanna_email")
        logger.debug(f"Cookie vanna_email={email}")
        if not email:
            # Prevent Vanna UI fallback login
            raise PermissionError("AUTH_REQUIRED")
        logger.info(f"User resolved successfully: {email}")
        return User(
            id=email,
            email=email,
            group_memberships=["admin"]
        )


user_resolver = SimpleUserResolver()

# -------------------------------------------------------------------
# TOOLS
# -------------------------------------------------------------------
logger.info("Registering tools")
tools = ToolRegistry()
tools.register_local_tool(db_tool, access_groups=["admin"])
tools.register_local_tool(SaveQuestionToolArgsTool(), access_groups=["admin"])
tools.register_local_tool(SearchSavedCorrectToolUsesTool(), access_groups=["admin"])
tools.register_local_tool(SaveTextMemoryTool(), access_groups=["admin"])
tools.register_local_tool(VisualizeDataTool(), access_groups=["admin"])

# -------------------------------------------------------------------
# AGENT
# -------------------------------------------------------------------
logger.info("Initializing Agent")
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


@app.middleware("http")
async def log_http_requests(request: Request, call_next):
    logger.info(f"Incoming request: {request.method} {request.url}")

    body = await request.body()
    if body:
        logger.debug(f"Request body: {body.decode(errors='ignore')}")

    response = await call_next(request)

    logger.info(f"Response status: {response.status_code}")
    return response
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
            samesite="lax",
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


@app.get("/index")
def serve_frontend():
    return FileResponse("index.html")

@app.get("/me")
async def me(request: Request):
    email = request.cookies.get("vanna_email")
    if not email:
        raise HTTPException(status_code=401, detail="Not authenticated")

    return {
        "email": email,
        "authenticated": True
    }
# -------------------------------------------------------------------
# RUN
# -------------------------------------------------------------------
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
