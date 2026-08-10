import json
import os

import chainlit as cl
import httpx

FASTAPI_URL = os.environ.get("BACKEND_API_URL", "http://127.0.0.1:8000/chat")


@cl.on_message
async def on_message(message: cl.Message):
    session_id = cl.user_session.get("id")

    # Initialize empty message (do NOT call msg.send() yet)
    msg = cl.Message(content="")

    payload = {
        "message": message.content,
        "thread_id": session_id,
    }

    async with (
        httpx.AsyncClient() as client,
        client.stream("POST", FASTAPI_URL, json=payload, timeout=300.0) as response,
    ):
        # Read line-by-line to prevent SSE chunk fragmentation
        async for line in response.aiter_lines():
            if not line:
                continue

            # Process only SSE data events
            if line.startswith("data: "):
                raw_data = line[6:].strip()

                try:
                    # Parse JSON payload: {"content": "token"}
                    data = json.loads(raw_data)
                    token = data.get("content", "")
                except json.JSONDecodeError:
                    token = raw_data

                if token:
                    await msg.stream_token(token)

    # Finalize the message stream in Chainlit UI
    await msg.update()