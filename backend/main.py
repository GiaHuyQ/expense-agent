from typing import cast
from dataclasses import dataclass
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from langgraph.graph.state import CompiledStateGraph

from src.expense_agent.agent import create_main_agent
from src.expense_agent.db import ExpenseDBResource, create_database
from src.expense_agent.logging_config import logger, setup_logging
from src.expense_agent.memory import (
    CheckpointerResource,
    StoreResource,
)
from src.expense_agent.services.chat_service import chat_stream

setup_logging()

@dataclass(slots=True)
class AppResources:
    agent: CompiledStateGraph
    checkpoint: CheckpointerResource
    store: StoreResource
    db: ExpenseDBResource


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("application_startup")

    resources = await create_main_agent()
    db = await create_database()

    app.state.resources = AppResources(
        agent=resources.agent,
        checkpoint=resources.checkpoint,
        store=resources.store,
        db=db,
    )

    yield

    logger.info("application_shutdown")

    await resources.checkpoint.manager.__aexit__(
        None,
        None,
        None,
    )

    await resources.store.manager.__aexit__(
        None,
        None,
        None,
    )


app = FastAPI(
    title="Expense Agent API",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_resources(
    request: Request,
) -> AppResources:
    return cast(
        AppResources,
        request.app.state.resources,
    )


class ChatRequest(BaseModel):
    message: str = Field(
        ...,
        min_length=1,
        description="User message.",
    )

    thread_id: str = Field(
        ...,
        min_length=1,
        description="Conversation thread identifier.",
    )


@app.post("/chat")
async def chat(
    body: ChatRequest,
    resources: AppResources = Depends(get_resources),
):
    logger.info(
        "chat_endpoint_called | thread_id=%s",
        body.thread_id,
    )

    return StreamingResponse(
    chat_stream(
        agent=resources.agent,
        db=resources.db,
        message=body.message,
        thread_id=body.thread_id,
    ),
    media_type="text/event-stream",
)



    