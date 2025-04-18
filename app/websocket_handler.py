from fastapi import WebSocket
from .flow import build_flow
from .nodes import active_users
from config import config

graph = build_flow()

async def handle_connection(user_id: str, websocket: WebSocket):
    await websocket.accept()
    active_users[user_id] = websocket
    print(f"✅ Connected: {user_id}")

    try:
        result = await graph.ainvoke({
            "user_id": user_id,
            "messages": [],
            "order": [],
            "finished": False
        }, config)

        await websocket.send_json({
            "action": "speak",
            "text": "Thank you for your order! Goodbye!"
        })

    except Exception as e:
        print(f"❌ Error: {e}")
    finally:
        del active_users[user_id]
        await websocket.close()
        print(f"🔌 Disconnected: {user_id}")
