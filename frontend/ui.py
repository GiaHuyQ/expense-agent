import os
import chainlit as cl
import httpx

FASTAPI_URL = os.environ.get("BACKEND_API_URL", "http://127.0.0.1:8000/chat")

@cl.on_message
async def on_message(message: cl.Message):
    session_id = cl.user_session.get("id")
    msg = cl.Message(content="")
    await msg.send()

    payload = {"message": message.content, "thread_id": session_id}

    async with httpx.AsyncClient() as client:
        async with client.stream("POST", FASTAPI_URL, json=payload, timeout=300.0) as response:
            async for chunk in response.aiter_text():
                if chunk:
                    await msg.stream_token(chunk)

    await msg.update()