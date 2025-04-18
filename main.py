from fastapi import FastAPI, WebSocket
from app.websocket_handler import handle_connection

app = FastAPI()

@app.websocket("/ws/{user_id}")
async def websocket_route(websocket: WebSocket, user_id: str):
    await handle_connection(user_id, websocket)

# if __name__ == "__main__":
#     import uvicorn
#     uvicorn.run("main:app", host="0.0.0.0", port=9000, reload=True)
