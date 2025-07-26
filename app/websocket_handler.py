from fastapi import WebSocket
from .flow import build_flow
from .nodes import active_users
from config import configAuth
from .auth import verify_google_token
import json
import logging
import base64
from io import BytesIO

logger = logging.getLogger(__name__)

graph = build_flow()

def get_flow_graph_image():
    """Generate and return the flow graph visualization as base64 encoded image."""
    try:
        # Get the graph visualization
        graph_image = graph.get_graph().draw_mermaid_png()
        
        # Convert to base64
        buffered = BytesIO(graph_image)
        img_str = base64.b64encode(buffered.getvalue()).decode()
        
        return {
            "type": "flow_graph",
            "data": {
                "image": img_str,
                "format": "png"
            }
        }
    except Exception as e:
        logger.error(f"Error generating flow graph: {e}")
        return {
            "type": "error",
            "message": "Failed to generate flow graph visualization"
        }

# Store user states with conversation history
# Each user state includes:
# - goals: List of user's goals
# - routines: Dictionary of routines for each goal
# - finished: Boolean indicating if the conversation is finished
# - conversation_history: List of message objects with role and content
user_states = {}

def trim_conversation_history(history, max_messages=20):
    """Trim conversation history to prevent it from growing too large."""
    if len(history) <= max_messages:
        return history
    
    # Keep the most recent messages, but always keep at least one user-assistant pair
    trimmed = history[-max_messages:]
    
    # Ensure we don't cut in the middle of a conversation
    if trimmed and trimmed[0]["role"] == "assistant":
        # If we start with an assistant message, remove it
        trimmed = trimmed[1:]
    
    return trimmed

async def handle_connection(websocket: WebSocket):
    await websocket.accept()
    logger.info("WebSocket connection accepted")

    try:
        # Wait for auth message first
        auth_data = await websocket.receive_json()
        logger.debug(f"Received auth data: {auth_data}")
        
        if auth_data.get("type") != "auth" or not auth_data.get("token"):
            logger.warning("Missing or invalid auth token")
            await websocket.send_json({ "type": "auth_error", "message": "Missing token" })
            await websocket.close()
            return

        token = auth_data["token"]
        user_info = verify_google_token(token, audience=configAuth["GOOGLE_CLIENT_ID"])
        logger.debug(f"Verified user info: {user_info}")

        if not user_info:
            logger.warning("Invalid or expired token")
            await websocket.send_json({ "type": "auth_error", "message": "Invalid or expired token" })
            await websocket.close()
            return

        user_id = user_info["sub"]  # Google's unique user ID
        active_users[user_id] = websocket
        logger.info(f"✅ Authenticated & Connected: {user_info['email']}")

        # Initialize user state if not exists
        if user_id not in user_states:
            logger.info(f"Initializing state for user {user_id}")
            user_states[user_id] = {
                "goals": [],
                "routines": {},
                "finished": False,
                "conversation_history": []  # Add conversation history
            }

        # Send authentication success
        await websocket.send_json({
            "type": "auth_success",
            "message": "Successfully authenticated",
            "user": {
                "id": user_id,
                "email": user_info["email"]
            }
        })
        logger.info(f"Sent auth success to user {user_id}")

        # Handle incoming messages
        while True:
            try:
                message = await websocket.receive_json()
                logger.info(f"Received message: {message}")
                
                message_type = message.get("type")
                
                # Handle flow graph request
                if message_type == "get_flow_graph":
                    graph_data = get_flow_graph_image()
                    await websocket.send_json(graph_data)
                    continue
                
                if message_type == "clear_history":
                    # Clear conversation history for the user
                    if user_id in user_states:
                        user_states[user_id]["conversation_history"] = []
                        await websocket.send_json({
                            "type": "clear_history_response",
                            "data": {
                                "status": "success",
                                "message": "Conversation history cleared"
                            }
                        })
                        logger.info(f"Cleared conversation history for user {user_id}")
                    continue
                
                args = message.get("args", {})
                logger.info(f"Processing message type: {message_type}")

                if message_type == "chat":
                    logger.info("Processing chat message")
                    # Extract email preferences and ensure proper format
                    user_message = args.pop("message")
                    current_state = user_states[user_id]

                    # Build conversation history with the new user message
                    conversation_history = current_state.get("conversation_history", [])
                    conversation_history.append({"role": "user", "content": user_message})
                    
                    # Send the message to the flow with full conversation history
                    result = await graph.ainvoke({
                        "user_id": user_id,
                        "messages": conversation_history,
                        "goals": current_state["goals"],
                        "routines": current_state["routines"],
                        "finished": current_state["finished"]
                    })
                    logger.info(f"Chat result: {result}")
                    
                    # Update user state with new conversation history
                    new_messages = result.get("messages", [])
                    updated_conversation_history = conversation_history.copy()
                    
                    # Add assistant responses to conversation history
                    for msg in new_messages:
                        if isinstance(msg, dict):
                            if msg.get("role") == "assistant":
                                updated_conversation_history.append(msg)
                        elif hasattr(msg, "content"):
                            # Check if this is a tool response (contains goal data patterns)
                            content = msg.content.lower()
                            is_tool_response = (
                                content.count("category:") > 1 or 
                                content.count("title:") > 1 or 
                                content.count("progress:") > 1
                            )
                            
                            if not is_tool_response:
                                updated_conversation_history.append({
                                    "role": "assistant",
                                    "content": msg.content
                                })
                            else:
                                logger.info("Skipping tool response in conversation history to prevent loops")
                    
                    user_states[user_id] = {
                        "goals": result.get("goals", []),
                        "routines": result.get("routines", {}),
                        "finished": result.get("finished", False),
                        "conversation_history": trim_conversation_history(updated_conversation_history)
                    }
                    
                    # Process response messages
                    response_messages = []
                    for msg in result.get("messages", []):
                        logger.debug(f"Processing message: {msg}")
                        if isinstance(msg, dict):
                            response_messages.append(msg)
                            logger.debug("Added dict message")
                        elif hasattr(msg, "content"):
                            response_messages.append({
                                "role": "assistant",
                                "content": msg.content
                            })
                            logger.debug("Added object message")
                        else:
                            response_messages.append({
                                "role": "assistant",
                                "content": str(msg)
                            })
                            logger.debug("Added string message")
                    
                    # Send chat response
                    response = {
                        "type": "chat_response",
                        "data": {
                            "messages": response_messages,
                            "goals": result.get("goals", []),
                            "routines": result.get("routines", {})
                        }
                    }
                    logger.debug(f"Sending chat response: {response}")
                    await websocket.send_json(response)
                    logger.info("Sent chat response")
                    continue

                if message_type == "add_goal":
                    logger.info("Processing add_goal message")
                    # Extract email preferences and ensure proper format
                    email_updates = args.pop("emailUpdates", "never")
                    
                    # Convert list of email updates to single string value
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
                    
                    # Validate email updates value
                    valid_email_updates = ["daily", "weekly", "monthly", "never"]
                    if email_updates not in valid_email_updates:
                        email_updates = "never"
                    
                    logger.debug(f"Formatted email updates: {email_updates}")
                    
                    # Extract milestones and ensure proper format
                    milestones = args.pop("milestones", [])
                    if isinstance(milestones, str):
                        try:
                            milestones = json.loads(milestones)
                        except json.JSONDecodeError:
                            milestones = []
                    elif not isinstance(milestones, list):
                        milestones = []
                    
                    # Ensure all milestones are strings and not empty
                    milestones = [str(m).strip() for m in milestones if str(m).strip()]
                    
                    # Add user_id to args
                    args["user_id"] = user_id
                    # Add the formatted fields
                    args["milestones"] = milestones
                    args["email_updates"] = email_updates
                    logger.debug(f"Processed goal args: {args}")

                # Get current state for user
                current_state = user_states[user_id]
                logger.debug(f"Current state for user {user_id}: {current_state}")

                # Format message for the flow
                flow_message = {
                    "type": message_type,
                    "args": args
                }
                logger.info(f"Formatted flow message: {flow_message}")

                # For add_goal, use the original approach without conversation history
                if message_type == "add_goal":
                    # Proceed with goal tracking flow using single message
                    result = await graph.ainvoke({
                        "user_id": user_id,
                        "messages": [{"role": "user", "content": json.dumps(flow_message)}],
                        "goals": current_state["goals"],
                        "routines": current_state["routines"],
                        "finished": current_state["finished"]
                    })
                    
                    # Update user state (don't add to conversation history for add_goal)
                    user_states[user_id] = {
                        "goals": result.get("goals", []),
                        "routines": result.get("routines", {}),
                        "finished": result.get("finished", False),
                        "conversation_history": current_state.get("conversation_history", [])
                    }
                else:
                    # For other message types, use conversation history
                    conversation_history = current_state.get("conversation_history", [])
                    conversation_history.append({"role": "user", "content": json.dumps(flow_message)})

                    # Proceed with goal tracking flow
                    result = await graph.ainvoke({
                        "user_id": user_id,
                        "messages": conversation_history,
                        "goals": current_state["goals"],
                        "routines": current_state["routines"],
                        "finished": current_state["finished"]
                    })
                    
                    # Update user state with conversation history
                    new_messages = result.get("messages", [])
                    updated_conversation_history = conversation_history.copy()
                    
                    # Add assistant responses to conversation history
                    for msg in new_messages:
                        if isinstance(msg, dict):
                            if msg.get("role") == "assistant":
                                updated_conversation_history.append(msg)
                        elif hasattr(msg, "content"):
                            # Check if this is a tool response (contains goal data patterns)
                            content = msg.content.lower()
                            is_tool_response = (
                                content.count("category:") > 1 or 
                                content.count("title:") > 1 or 
                                content.count("progress:") > 1
                            )
                            
                            if not is_tool_response:
                                updated_conversation_history.append({
                                    "role": "assistant",
                                    "content": msg.content
                                })
                            else:
                                logger.info("Skipping tool response in conversation history to prevent loops")
                    
                    user_states[user_id] = {
                        "goals": result.get("goals", []),
                        "routines": result.get("routines", {}),
                        "finished": result.get("finished", False),
                        "conversation_history": trim_conversation_history(updated_conversation_history)
                    }
                
                logger.info(f"Updated user state: {user_states[user_id]}")

                # Format the response based on message type
                if message_type == "add_goal":
                    # Extract the routine from the response
                    goals = result.get("goals", [])
                    routine = result.get("routines", {})
                    logger.info(f"state Messages: {goals}")


                    try:
                        response_data = goals
                        logger.info(f"Parsed response data: {response_data}")
                        
                        # Send the complete response to frontend
                        await websocket.send_json({
                            "type": "add_goal_response",
                            "data": {
                                "status": "success",
                                "goal": response_data,
                                "title": args["title"],
                                "category": args["category"],
                                "description": args["description"],
                                "deadline": args["deadline"],
                                "emailUpdates": email_updates,
                                "routine": routine[args["title"]]
                            }
                        })
                        logger.info("Sent add_goal response")
                    except json.JSONDecodeError as e:
                        logger.warning(f"Failed to parse response as JSON: {e}")
                        # Send error response
                        await websocket.send_json({
                            "type": "add_goal_response",
                            "data": {
                                "status": "error",
                                "message": "Failed to process goal addition",
                                "error": str(e)
                            }
                        })
                        logger.info("Sent error response")
                else:
                    # For other message types, send the standard response
                    response_messages = []
                    for msg in result.get("messages", []):
                        logger.debug(f"Processing message: {msg}")
                        if isinstance(msg, dict):
                            response_messages.append(msg)
                            logger.debug("Added dict message")
                        elif hasattr(msg, "content"):
                            response_messages.append({
                                "role": "assistant",
                                "content": msg.content
                            })
                            logger.debug("Added object message")
                        else:
                            response_messages.append({
                                "role": "assistant",
                                "content": str(msg)
                            })
                            logger.debug("Added string message")
                    
                    response = {
                        "type": f"{message_type}_response",
                        "data": {
                            "messages": response_messages,
                            "goals": result.get("goals", []),
                            "routines": result.get("routines", {})
                        }
                    }
                    logger.debug(f"Sending response: {response}")
                    await websocket.send_json(response)
                    logger.info(f"Sent {message_type} response")

            except Exception as e:
                logger.error(f"Error processing message: {e}", exc_info=True)
                await websocket.send_json({
                    "type": "error",
                    "message": str(e)
                })

    except Exception as e:
        logger.error(f"❌ Error: {e}", exc_info=True)
    finally:
        if 'user_id' in locals():
            del active_users[user_id]
            logger.info(f"Removed user {user_id} from active users")
            # Optionally clear user state on disconnect
            # del user_states[user_id]
        await websocket.close()
        logger.info(f"🔌 Disconnected")
