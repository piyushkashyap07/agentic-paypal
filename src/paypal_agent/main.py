import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

import aiosqlite
from fastapi import FastAPI
from fastapi.responses import FileResponse
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from paypal_agent.agent.graph import build_graph
from paypal_agent.api.routes import router
from paypal_agent.config import settings
from paypal_agent.workers.payment_monitor import run_monitor_loop


@asynccontextmanager
async def lifespan(app: FastAPI):
    print(f"Starting {settings.app_name}...")

    async with aiosqlite.connect(
        "paypal_agent_checkpoints.db"
    ) as connection:
        checkpointer = AsyncSqliteSaver(connection)
        await checkpointer.setup()

        app.state.payment_agent = build_graph(checkpointer)

        monitor_task = None

        if settings.monitor_enabled:
            monitor_task = asyncio.create_task(run_monitor_loop())

        yield

        if monitor_task:
            monitor_task.cancel()

    print("Shutting down PayPal AI Agent...")


app = FastAPI(
    title=settings.app_name,
    description="An AI agent that helps users manage the PayPal payment lifecycle.",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(router)


@app.get("/", tags=["Health"])
async def root():
    return {
        "app": settings.app_name,
        "status": "running",
        "environment": settings.app_env,
    }


@app.get("/health", tags=["Health"])
async def health():
    return {"status": "healthy"}


@app.get("/ui", include_in_schema=False)
async def chat_ui():
    return FileResponse(Path(__file__).parent / "static" / "index.html")