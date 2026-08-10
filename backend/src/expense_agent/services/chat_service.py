import json
from collections.abc import AsyncGenerator

from langchain.messages import HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph.state import CompiledStateGraph
from src.expense_agent.db import ExpenseDBResource
from src.expense_agent.logging_config import logger


async def chat_stream(
    agent: CompiledStateGraph,
    db: ExpenseDBResource,
    message: str,
    thread_id: str,
) -> AsyncGenerator[str, None]:

    logger.info(
        "chat_stream_called | thread_id=%s",
        thread_id,
    )

    config = RunnableConfig(
        configurable={
            "thread_id": thread_id,
            "db": db
        },
        recursion_limit=30
    )

    try:
        async for event in agent.astream(
            {
                "messages": [
                    HumanMessage(content=message),
                ]
            },
            config=config,
            stream_mode="messages",
            version="v2"
        ):  
            if event["type"] == "messages":
                chunk, metadata = event["data"]
                node = metadata.get("langgraph_node")         
                if node == "model":
                    payload = json.dumps({"content": chunk.content})
                    yield f"data: {payload}\n\n"
            
        logger.info(
            "chat_stream_finished | thread_id=%s",
            thread_id,
        )

    except Exception:
        logger.exception(
            "chat_stream_failed | thread_id=%s",
            thread_id,
        )
        raise


