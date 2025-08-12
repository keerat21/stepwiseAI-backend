import json
import logging
from fastapi import WebSocket
from app.auth import verify_google_token
from app.tools import add_goal
from app.llm_flow import run_goal_planner
from config import GOOGLE_CLIENT_ID

logger = logging.getLogger(__name__)

# Store user states (simplified)
user_states = {}

async def handle_connection(websocket: WebSocket):
    """Handle WebSocket connection with authentication, add_goal, and chat (LLM) functionality."""
    await websocket.accept()
    logger.info("WebSocket connection accepted")
    
    try:
        while True:
            # Receive message
            data = await websocket.receive_text()
            message = json.loads(data)
            logger.info(f"Received message: {message}")
            
            # Extract message type and args
            message_type = message.get("type")
            args = message.get("args", {})
            
            if not message_type:
                await websocket.send_json({
                    "type": "error",
                    "data": {"message": "Message type is required"}
                })
                continue
            
            # Handle authentication
            if message_type == "auth":
                token = args.get("token")
                if not token:
                    await websocket.send_json({
                        "type": "auth_response",
                        "data": {"status": "error", "message": "Token is required"}
                    })
                    continue
                
                # Verify Google token
                user_info = verify_google_token(token, GOOGLE_CLIENT_ID)
                if not user_info:
                    await websocket.send_json({
                        "type": "auth_response",
                        "data": {"status": "error", "message": "Invalid token"}
                    })
                    continue
                
                user_id = user_info["sub"]
                user_states[user_id] = {
                    "goals": [],
                    "routines": {},
                    "finished": False
                }
                
                await websocket.send_json({
                    "type": "auth_response",
                    "data": {
                        "status": "success",
                        "user_id": user_id,
                        "user_info": user_info
                    }
                })
                logger.info(f"User authenticated: {user_id}")
                continue
            
            # Handle add_goal
            if message_type == "add_goal":
                user_id = args.get("user")
                if not user_id:
                    await websocket.send_json({
                        "type": "add_goal_response",
                        "data": {"status": "error", "message": "User ID is required"}
                    })
                    continue
                
                # Extract goal data
                title = args.get("title")
                category = args.get("category")
                description = args.get("description")
                deadline = args.get("deadline")
                email_updates = args.get("emailUpdates", "never")
                milestones = args.get("milestones", [])
                
                # Convert email updates list to string
                if isinstance(email_updates, list):
                    if "daily" in email_updates:
                        email_updates = "daily"
                    elif "weekly" in email_updates:
                        email_updates = "weekly"
                    elif "monthly" in email_updates:
                        email_updates = "monthly"
                    else:
                        email_updates = "never"
                elif not isinstance(email_updates, str):
                    email_updates = "never"
                
                # Validate required fields
                if not all([title, category, description, deadline]):
                    await websocket.send_json({
                        "type": "add_goal_response",
                        "data": {"status": "error", "message": "Missing required fields"}
                    })
                    continue
                try:
                    # Call add_goal tool using invoke method
                    result = add_goal.invoke({
                        "title": title,
                        "category": category,
                        "description": description,
                        "deadline": deadline,
                        "user_id": user_id,
                        "milestones": milestones,
                        "email_updates": email_updates
                    })
                    # Parse the result
                    if isinstance(result, str):
                        try:
                            result_data = json.loads(result)
                        except json.JSONDecodeError:
                            result_data = {"status": "success", "message": result}
                    else:
                        result_data = result
                    # Send response
                    await websocket.send_json({
                        "type": "add_goal_response",
                        "data": {
                            "status": "success",
                            "goal": result_data.get("goal", {}),
                            "title": title,
                            "category": category,
                            "description": description,
                            "deadline": deadline,
                            "emailUpdates": email_updates,
                            "routine": result_data.get("goal", {}).get("routine", [])
                        }
                    })
                    logger.info(f"Successfully added goal: {title}")
                except Exception as e:
                    logger.error(f"Error adding goal: {e}")
                    await websocket.send_json({
                        "type": "add_goal_response",
                        "data": {
                            "status": "error",
                            "message": f"Failed to add goal: {str(e)}"
                        }
                    })
                continue
            
            # Handle chat (LLM-driven goal planning)
            if message_type == "chat":
                user_id = args.get("user")
                user_message = args.get("message")
                if not user_id or not user_message:
                    await websocket.send_json({
                        "type": "chat_response",
                        "data": {"status": "error", "message": "User ID and message are required"}
                    })
                    continue
                try:
                    result = run_goal_planner(user_id, user_message)
                    await websocket.send_json({
                        "type": "chat_response",
                        "data": {"status": "success", "result": result}
                    })
                except Exception as e:
                    logger.error(f"Error in chat flow: {e}")
                    await websocket.send_json({
                        "type": "chat_response",
                        "data": {"status": "error", "message": str(e)}
                    })
                continue
            
            # Unknown message type
            await websocket.send_json({
                "type": "error",
                "data": {"message": f"Unknown message type: {message_type}"}
            })
            
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        await websocket.close()
