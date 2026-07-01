from collections.abc import AsyncGenerator

from langchain.messages import HumanMessage, AIMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph.state import CompiledStateGraph

from expense_agent.db import ExpenseDBResource
from expense_agent.logging_config import logger



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
        async for chunk, _ in agent.astream(
            {
                "messages": [
                    HumanMessage(content=message),
                ]
            },
            config=config,
            stream_mode="messages",
        ):  
            if chunk.content:          # type: ignore[attr-defined]
                yield chunk.content    # type: ignore[attr-defined]
            
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


