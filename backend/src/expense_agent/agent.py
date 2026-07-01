from dataclasses import dataclass

from .config import settings
from .memory import create_checkpointer, create_store, CheckpointerResource, StoreResource
from .tools import save_user_info
from .prompt import build_system_prompt
from .sql_agent.agent import db_assistant

from langchain_openai import ChatOpenAI
from langchain.agents.middleware import SummarizationMiddleware, PIIMiddleware
from langchain.agents import create_agent
from langgraph.graph.state import CompiledStateGraph

chat_model = ChatOpenAI(
    base_url=settings.BASE_URL,
    api_key=settings.OPENAI_API_KEY,
    model=settings.MODEL_NAME,
    temperature=0.0,
    streaming=True,
    stream_usage=True,
)

summarize_model = ChatOpenAI(
    base_url=settings.BASE_URL,
    api_key=settings.OPENAI_API_KEY,
    model=settings.MODEL_NAME,
    temperature=0.0,
)


@dataclass(slots=True)
class AgentResources:
    agent: CompiledStateGraph
    checkpoint: CheckpointerResource
    store: StoreResource


async def create_main_agent() -> AgentResources:
    checkpoint_resource  = await create_checkpointer()
    store_resource = await create_store()

    agent = create_agent(
        model=chat_model,
        tools=[save_user_info, db_assistant],
        checkpointer=checkpoint_resource.checkpointer,
        store=store_resource.store,
        middleware=[
            PIIMiddleware("credit_card", strategy="mask", apply_to_input=True),
            SummarizationMiddleware(
                model=summarize_model,
                trigger=[("tokens", 4096), ("messages", 6)],
                keep=("messages", 10)
            ),
            build_system_prompt
        ]
        
    )

    return AgentResources(
        agent=agent,
        checkpoint=checkpoint_resource,
        store=store_resource
    )