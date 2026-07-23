from typing import Any, Annotated

from langchain_openai.chat_models import ChatOpenAI
from langchain.messages import HumanMessage
from langchain.agents import create_agent
from langchain.tools import tool

from langchain_core.runnables import RunnableConfig
from langgraph.store.base import BaseStore
from langgraph.prebuilt import InjectedStore 

from .prompt import build_system_prompt
from src.expense_agent.config import settings
from src.expense_agent.logging_config import logger
from src.expense_agent.sql_agent.tools import (
    execute_sql,
    add_transaction,
    update_transaction,
    delete_transaction,
    add_category,
    add_money_source,
)

model = ChatOpenAI(
    base_url=settings.BASE_URL,
    api_key=settings.OPENAI_API_KEY,
    model=settings.MODEL_NAME,
    temperature=0.0,
    top_p=0.95,
    
)

sql_agent = create_agent(
    model=model,
    middleware=[build_system_prompt], 
    tools=[execute_sql, add_category, add_money_source, add_transaction, update_transaction, delete_transaction]
)

@tool

async def db_assistant(
    query: str, 
    config: RunnableConfig,
    store: Annotated[BaseStore, InjectedStore()]
) -> dict[str, Any]:
    """Assistant specialized in financial expense tracking data.

    Call this tool whenever the user wants to inquire about wallet balances,
    net worth, transaction history, or wants to add, update, or delete
    expense/income records.

    Args:
        query: The raw natural language instruction or question from the user,
            passed through as-is for the specialized assistant to interpret.
    """
    logger.info(f"finance_db_assistant_triggered | query='{query}'")
    try:
        
        sub_config = config.copy()
        sub_config["recursion_limit"] = 25

        response = await sql_agent.ainvoke(
            {"messages": [HumanMessage(content=query)]},
            config=sub_config,
            store=store
        )
        
        logger.info("finance_db_assistant_success")
        
        return {
            "status": "success",
            "content": str(response["messages"][-1].content)
        }
        
    except Exception as err:
        logger.error(f"finance_db_assistant_failed | error='{str(err)}'")            
        return {
            "status": "error"
        }