from langchain_core.messages.ai import AIMessage
from langchain_core.messages.tool import ToolMessage
from langchain_core.messages.human import HumanMessage
from random import randint
from .schema import GoalState
from .tools import goal_auto_tools, goal_action_tools, llm_with_tools
from fastapi import WebSocket
from typing import Literal
from datetime import datetime
import logging
import json
import uuid

# Set up logging
logger = logging.getLogger(__name__)

# External state
active_users = {}

def get_system_prompt(user_id: str) -> tuple[str, str]:
    """Generate system prompt with user context."""
    return (
        "system",
        f"You are GoalSetterAI, a supportive assistant that helps users:"
        f"- Set personal development goals"
        f"- Break down goals into daily routines"
        f"- Log daily progress and track consistency"
        f"Current user ID: {user_id}"
        f"Use the user id to identify the user and their goals. Do not ask the user for their id."
        f"CRITICAL: You have access to tools. When users ask to review, analyze, or see their goals, you MUST call the get_goals tool with user_id={user_id}."
        f"CRITICAL: When users ask to add a new goal, you MUST call the add_goal tool."
        f"CRITICAL: Do not ask users for information that you can get from tools. Use the tools to retrieve information."
        f"Available tools: get_goals, add_goal, generate_routine, get_goal_progress, get_user_goals"
        f"Use tools when the user wants to add, review, or modify goals and routines."
        f" Always aim to assist the user in staying motivated and organized."
        f"IMPORTANT: If the user asks to review their goals, immediately call get_goals with user_id={user_id}."
    )

# This is the message with which the system opens the conversation.
WELCOME_GOAL_MSG = "Welcome to the Goal Setter AI. How may I help you today?"

async def human_node(state: GoalState) -> GoalState:
    """Display last AI message and receive user input."""
    user_id = state["user_id"]
    logger.info(f"Processing human_node for user {user_id}")
    logger.info(f"Current state: {state}")
    
    ws = active_users.get(user_id)
    if not ws:
        logger.error(f"WebSocket not found for user {user_id}")
        raise RuntimeError("WebSocket not found")

    last_msg = state["messages"][-1]
    # Handle both dictionary and object message formats
    if isinstance(last_msg, dict):
        message_content = last_msg.get("content", "")
    elif hasattr(last_msg, "content"):
        message_content = last_msg.content
    else:
        message_content = str(last_msg)
    
    logger.info(f"Sending message to user: {message_content}")
    await ws.send_json({"action": "speak", "text": message_content})

    while True:
        msg = await ws.receive_json()
        logger.info(f"Received message from user: {msg}")
        if msg.get("type") == "userSpeech":
            break

    if msg["text"].lower() in {"q", "quit", "exit", "bye"}:
        logger.info(f"User {user_id} requested to exit")
        state["finished"] = True

    # Create a proper HumanMessage
    human_msg = HumanMessage(content=msg["text"])
    logger.debug(f"Created HumanMessage: {human_msg}")
    return state | {"messages": [human_msg]}

def goal_ai_with_tools(state: GoalState) -> GoalState:
    """Generate AI response using tools."""
    logger.info(f"Processing goal_ai_with_tools")
    logger.debug(f"Input state: {state}")
    
    # Don't reset goals and routines, use existing state
    current_state = {
        "goals": state.get("goals", []),
        "routines": state.get("routines", {}),
        "finished": state.get("finished", False)
    }

    if state["messages"]:
        # Check if this is an add_goal message
        last_msg = state["messages"][-1]
        logger.info(f"Last message: {last_msg}")
        
        # Handle HumanMessage objects
        if isinstance(last_msg, HumanMessage):
            content = last_msg.content
            try:
                message_data = json.loads(content)
                if message_data.get("type") == "add_goal":
                    logger.info("Processing add_goal message")
                    # Directly add the goal without confirmation
                    args = message_data.get("args", {})
                    logger.debug(f"Goal arguments: {args}")
                    
                    if all(k in args for k in ["title", "category", "description", "deadline"]):
                        # Create a tool call for add_goal
                        tool_call = {
                            "name": "add_goal",
                            "args": args,
                            "id": str(uuid.uuid4())  # Generate unique ID for tool call
                        }
                        logger.debug(f"Created tool call: {tool_call}")
                        
                        # Process the tool call directly
                        result = goal_action_node({
                            "messages": [{"tool_calls": [tool_call]}], 
                            "goals": current_state["goals"], 
                            "routines": current_state["routines"], 
                            "user_id": state["user_id"]
                        })
                        logger.debug(f"Tool call result: {result}")
                        
                        # Update current state with new goals and routines
                        current_state["goals"] = result.get("goals", current_state["goals"])
                        current_state["routines"] = result.get("routines", current_state["routines"])
                        
                        # Convert tool message to dict format
                        tool_message = result["messages"][0]
                        if isinstance(tool_message, ToolMessage):
                            response_content = tool_message.content
                        elif isinstance(tool_message, dict):
                            response_content = tool_message.get("content", "")
                        else:
                            response_content = str(tool_message)
                            
                        try:
                            # Try to parse the response as JSON
                            response_data = json.loads(response_content)
                            if response_data.get("status") == "success":
                                return current_state | {
                                    "messages": [{
                                        "role": "assistant",
                                        "content": f"✅ Successfully added your goal: {args['title']}\n\n{response_data.get('message', '')}"
                                    }]
                                }
                            else:
                                return current_state | {
                                    "messages": [{
                                        "role": "assistant",
                                        "content": f"❌ {response_data.get('message', 'Error adding goal')}"
                                    }]
                                }
                        except json.JSONDecodeError:
                            return current_state | {
                                "messages": [{
                                    "role": "assistant",
                                    "content": response_content
                                }]
                            }
                    else:
                        missing_fields = [k for k in ["title", "category", "description", "deadline"] if k not in args]
                        return current_state | {
                            "messages": [{
                                "role": "assistant",
                                "content": f"❌ Missing required fields: {', '.join(missing_fields)}"
                            }]
                        }
            except json.JSONDecodeError:
                # If not JSON, treat as regular message
                pass
        
        # Convert messages to proper format for LLM
        # Use all messages for context, but filter out tool responses to prevent loops
        messages = []
        for msg in state["messages"]:
            if isinstance(msg, dict):
                if msg["role"] == "user":
                    messages.append(HumanMessage(content=msg["content"]))
                elif msg["role"] == "assistant":
                    # Include assistant messages for context but don't process them for tools
                    messages.append(AIMessage(content=msg["content"]))
            elif isinstance(msg, (HumanMessage, AIMessage)):
                messages.append(msg)
            elif isinstance(msg, ToolMessage):
                # Skip ToolMessage objects to prevent re-processing tool responses
                continue
        
        # Check if the user is asking to review goals and manually trigger tool call
        # Only check the latest user message, not all messages
        user_messages = [msg for msg in messages if isinstance(msg, HumanMessage)]
        if user_messages:
            last_user_message = user_messages[-1]
            
            # Skip if this is not actually a user message (e.g., it's a tool response converted to HumanMessage)
            if hasattr(last_user_message, 'content'):
                content = last_user_message.content.lower()
                # Check if this looks like a tool response that was converted to a user message
                if (content.count("category:") > 1 or 
                    content.count("title:") > 1 or 
                    content.count("progress:") > 1):
                    logger.info("Skipping tool trigger - detected tool response converted to user message")
                    # Let the LLM process this normally without manual tool triggering
            
            # Check if this is a tool response by multiple criteria
            is_tool_response = False
            
            # 1. Check if it's a ToolMessage type
            if isinstance(last_user_message, ToolMessage):
                is_tool_response = True
                logger.info("Detected ToolMessage - skipping tool trigger")
            
            # 2. Check if it has tool_call_id attribute
            elif hasattr(last_user_message, 'tool_call_id') and last_user_message.tool_call_id:
                is_tool_response = True
                logger.info("Detected tool_call_id - skipping tool trigger")
            
            # 3. Check if it's a dict with tool_call_id
            elif isinstance(last_user_message, dict) and last_user_message.get('tool_call_id'):
                is_tool_response = True
                logger.info("Detected dict with tool_call_id - skipping tool trigger")
            
            # 4. Check content for goal data patterns
            elif hasattr(last_user_message, 'content'):
                content = last_user_message.content.lower()
                # Check for goal data patterns (multiple goals with category/title/description/deadline)
                goal_patterns = [
                    "category:" in content and "title:" in content and "description:" in content and "deadline:" in content,
                    content.count("category:") > 1,  # Multiple goals
                    content.count("title:") > 1,     # Multiple goals
                    content.count("progress:") > 1   # Multiple goals with progress
                ]
                if any(goal_patterns):
                    is_tool_response = True
                    logger.info("Detected goal data in content - skipping tool trigger")
            
            if not is_tool_response:
                # Get the content for keyword checking
                if hasattr(last_user_message, 'content'):
                    last_user_content = last_user_message.content.lower()
                elif isinstance(last_user_message, dict):
                    last_user_content = last_user_message.get('content', '').lower()
                else:
                    last_user_content = str(last_user_message).lower()
                
                if any(keyword in last_user_content for keyword in ["review", "see", "show", "list", "check", "analyze", "view"]):
                    if any(keyword in last_user_content for keyword in ["goal", "goals"]):
                        logger.info("User asked to review goals, manually triggering get_goals tool")
                        # Create a tool call manually
                        tool_call = {
                            "name": "get_goals",
                            "args": {"user_id": state["user_id"]},
                            "id": str(uuid.uuid4())
                        }
                        
                        # Process the tool call
                        result = goal_action_node({
                            "messages": [{"tool_calls": [tool_call]}],
                            "goals": current_state["goals"],
                            "routines": current_state["routines"],
                            "user_id": state["user_id"]
                        })
                        
                        return current_state | {
                            "messages": state.get("messages", []) + [result["messages"][0]],
                            "goals": result.get("goals", current_state["goals"]),
                            "routines": result.get("routines", current_state["routines"])
                        }
        
        logger.debug(f"Converted messages: {messages}")
        system_prompt = get_system_prompt(state["user_id"])
        logger.info(f"Using system prompt: {system_prompt}")
        logger.info(f"Available tools: {[tool.name for tool in goal_auto_tools]}")
        
        try:
            new_output = llm_with_tools.invoke([system_prompt] + messages)
            logger.debug(f"LLM output: {new_output}")
            logger.info(f"LLM output type: {type(new_output)}")
            if hasattr(new_output, 'tool_calls'):
                logger.info(f"Tool calls: {new_output.tool_calls}")
            if hasattr(new_output, 'content'):
                logger.info(f"LLM content: {new_output.content}")
        except Exception as e:
            logger.error(f"Error calling LLM: {e}")
            new_output = {"role": "assistant", "content": "I'm here to help you with your goals! You can ask me to:\n- Review your existing goals\n- Add a new goal\n- Track your progress\n- Generate routines for your goals\n\nWhat would you like to do?", "is_fallback": True}

        # Convert AIMessage to dict for JSON serialization
        if isinstance(new_output, AIMessage):
            new_output = {"role": "assistant", "content": new_output.content}
    else:
        logger.info("No messages, sending welcome message")
        new_output = {"role": "assistant", "content": WELCOME_GOAL_MSG}

    # 🛡️ Prevent Gemini from crashing on empty content
    if not new_output["content"].strip():
        logger.warning("Empty LLM output, using fallback message")
        new_output["content"] = "I'm here to help you with your goals! You can ask me to:\n- Review your existing goals\n- Add a new goal\n- Track your progress\n- Generate routines for your goals\n\nWhat would you like to do?"
        # Mark this as a fallback response to prevent infinite loops
        new_output["is_fallback"] = True

    result = current_state | {"messages": state.get("messages", []) + [new_output]}
    logger.debug(f"Final state: {result}")
    return result

def maybe_exit_human_node(state: GoalState) -> Literal["goal_ai", "__end__"]:
    """Route to the goal_ai_node, unless it looks like the user is exiting."""
    if state.get("finished", False):
        print(state)
        return "__end__"
    else:
        return "goal_ai"

def goal_action_node(state: GoalState) -> GoalState:
    """Handles goal planning, logging, modifying, confirming."""
    tool_msg = state.get("messages", [])[-1]
    goals = state.get("goals", [])
    routines = state.get("routines", {})
    outbound_msgs = []

    # Handle both dict and object tool calls
    tool_calls = []
    if isinstance(tool_msg, dict):
        if "tool_calls" in tool_msg:
            tool_calls = tool_msg["tool_calls"]
        elif "content" in tool_msg:
            try:
                content = json.loads(tool_msg["content"])
                if isinstance(content, dict) and "tool_calls" in content:
                    tool_calls = content["tool_calls"]
            except json.JSONDecodeError:
                pass
    elif hasattr(tool_msg, "tool_calls"):
        tool_calls = tool_msg.tool_calls

    # Find tools by name
    generate_routine_tool = next((tool for tool in goal_action_tools if tool.name == "generate_routine"), None)
    add_goal_tool = next((tool for tool in goal_action_tools if tool.name == "add_goal"), None)
    get_goals_tool = next((tool for tool in goal_action_tools if tool.name == "get_goals"), None)

    for tool_call in tool_calls:
        if "user_id" in tool_call["args"]:
            tool_call["args"]["user_id"] = state["user_id"]
             
        if tool_call["name"] == "add_goal":
            goal_title = tool_call["args"]["title"]
            category = tool_call["args"]["category"]
            description = tool_call["args"]["description"]
            deadline = tool_call["args"].get("deadline", "")
            milestones = tool_call["args"].get("milestones", [])
            email_updates = tool_call["args"].get("email_updates", {})
            
            # Ensure milestones is a list
            if isinstance(milestones, str):
                try:
                    milestones = json.loads(milestones)
                except json.JSONDecodeError:
                    milestones = []
            elif not isinstance(milestones, list):
                milestones = []
            
            # Calculate days from deadline
            try:
                if deadline:
                    deadline_date = datetime.strptime(deadline, "%Y-%m-%d")
                    days = max(1, (deadline_date - datetime.now()).days)
                else:
                    days = 30  # Default to 30 days if no deadline
            except ValueError:
                days = 30  # Default to 30 days if invalid deadline format
            
            # Create goal object
            goal = {
                "title": goal_title,
                "category": category,
                "description": description,
                "deadline": deadline,
                "milestones": milestones,  # Convert milestones to JSON string for storage
                "email_updates": email_updates
            }
            
            # Add to goals list
            goals.append(goal)
            logger.info(f"=======HERE======Goals: {goals}")
            
            # Generate and store routine using the tool directly
            if generate_routine_tool:
                routine = generate_routine_tool.invoke({
                    "goal": goal_title,
                    "days": days,
                    "milestones": milestones
                })
                routines[goal_title] = routine
            
            # Create tool message with the response
            if add_goal_tool:
                response = add_goal_tool.invoke({
                    "title": goal_title,
                    "category": category,
                    "description": description,
                    "deadline": deadline,
                    "user_id": state["user_id"],
                    "milestones": milestones,
                    "email_updates": email_updates
                })
                
                # Parse the JSON response
                try:
                    response_data = json.loads(response)
                    if response_data["status"] == "success":
                        # Update goal with database ID
                        goal["id"] = response_data["goal"]["id"]
                        response = response_data["message"]
                    else:
                        response = response_data["message"]
                except json.JSONDecodeError:
                    logger.error("Failed to parse add_goal response ")
                    response = "Error processing goal addition"
            else:
                response = "Error: add_goal tool not found"

        elif tool_call["name"] == "get_goals":
            if get_goals_tool:
                response = get_goals_tool.invoke({
                    "user_id": tool_call["args"]["user_id"]
                })
            else:
                response = "Error: get_goals tool not found"

        else:
            raise NotImplementedError(f"Unknown tool: {tool_call['name']}")

        outbound_msgs.append(
            ToolMessage(
                content=response,
                name=tool_call["name"],
                tool_call_id=tool_call["id"]
            )
        )

    return {"messages": outbound_msgs, "goals": goals, "routines": routines, "finished": state.get("finished", False)}

def maybe_route_goal_tools(state: GoalState) -> Literal["goal_ai", "goal_tools", "goal_actions", "human", "__end__"]:
    if not (msgs := state.get("messages", [])):
        raise ValueError("No messages found.")

    msg = msgs[-1]

    if state.get("finished", False):
        return "__end__"

    # Check if this is a ToolMessage (tool response) - end the flow
    if isinstance(msg, ToolMessage) or hasattr(msg, 'tool_call_id'):
        logger.info("Detected ToolMessage - ending flow")
        return "__end__"

    elif hasattr(msg, "tool_calls") and len(msg.tool_calls) > 0:
        tool_names = [tool["name"] for tool in msg.tool_calls]
        if any(name in [t.name for t in goal_action_tools] for name in tool_names):
            return "goal_actions"
        else:
            return "goal_tools"

    # Check if this is a chat message (not a structured API call)
    # If it's a simple chat message, let the AI process it first
    if isinstance(msg, dict):
        content = msg.get("content", "")
        # Check if this is a fallback response to prevent infinite loops
        if msg.get("is_fallback", False):
            return "__end__"
        # Check if this is an assistant message to prevent self-conversation
        if msg.get("role") == "assistant":
            return "__end__"
        # Check if this is a tool response (has tool_call_id)
        if msg.get("tool_call_id"):
            logger.info("Detected dict with tool_call_id - ending flow")
            return "__end__"
    else:
        content = msg.content
        # Check if this is an AIMessage to prevent self-conversation
        if isinstance(msg, AIMessage):
            return "__end__"
    
    # If this is a simple string message (not JSON), it's a chat message
    # Let the AI process it and potentially generate tool calls
    try:
        json.loads(content)
        # If it's valid JSON, it might be an API call, so route to human
        return "human"
    except json.JSONDecodeError:
        # If it's not JSON, it's a simple chat message
        # Let the AI process it first, then it can route to tools if needed
        return "goal_ai"

async def api_node(state: GoalState) -> GoalState:
    """Handle direct API requests from frontend."""
    logger.info("Processing API request")
    
    if not state.get("messages"):
        return state | {"messages": [{"role": "assistant", "content": "No request data provided"}]}
    
    # Get the last message which should contain the request
    request = state["messages"][-1]
    if isinstance(request, dict):
        request_data = request.get("content", {})
        if isinstance(request_data, str):
            try:
                request_data = json.loads(request_data)
            except json.JSONDecodeError:
                return state | {"messages": [{"role": "assistant", "content": "Invalid JSON request"}]}
    else:
        request_data = json.loads(request.content)
    
    request_type = request_data.get("type")
    args = request_data.get("args", {})
    
    if request_type == "add_goal":
        # Validate required fields
        required_fields = ["title", "category", "description"]
        missing_fields = [field for field in required_fields if field not in args]
        if missing_fields:
            return state | {
                "messages": [{
                    "role": "assistant",
                    "content": json.dumps({
                        "status": "error",
                        "message": f"Missing required fields: {', '.join(missing_fields)}"
                    })
                }]
            }
        
        # Process email updates
        email_updates = args.pop("emailUpdates", "never")
        if isinstance(email_updates, list):
            if "daily" in email_updates:
                email_updates = "daily"
            elif "weekly" in email_updates:
                email_updates = "weekly"
            elif "monthly" in email_updates:
                email_updates = "monthly"
            else:
                email_updates = "never"
        
        # Process milestones
        milestones = args.pop("milestones", [])
        if isinstance(milestones, str):
            try:
                milestones = json.loads(milestones)
            except json.JSONDecodeError:
                milestones = []
        elif not isinstance(milestones, list):
            milestones = []
        
        # Clean milestones
        milestones = [str(m).strip() for m in milestones if str(m).strip()]
        
        # Add user_id to args
        args["user_id"] = state["user_id"]
        args["milestones"] = milestones
        args["email_updates"] = email_updates
        
        # Create tool call
        tool_call = {
            "name": "add_goal",
            "args": args,
            "id": str(uuid.uuid4())
        }
        
        # Process the goal addition
        result = goal_action_node({
            "messages": [{"tool_calls": [tool_call]}],
            "goals": state.get("goals", []),
            "routines": state.get("routines", {}),
            "user_id": state["user_id"]
        })
        # logger.info(f"Api node Result: {result}")
        
        # Format the response
        try:
            response_data = json.loads(result["messages"][0].content)
            if response_data.get("status") == "success":
                return result | {
                    "messages": [{
                        "role": "assistant",
                        "content": json.dumps({
                            "status": "success",
                            "message": f"✅ Successfully added your goal: {args['title']}",
                            "goal": response_data.get("goal", {}),
                            "routine": response_data.get("goal", {}).get("routine", [])
                        })
                    }]
                }
            else:
                return result | {
                    "messages": [{
                        "role": "assistant",
                        "content": json.dumps({
                            "status": "error",
                            "message": response_data.get("message", "Error adding goal")
                        })
                    }]
                }
        except json.JSONDecodeError:
            return result | {
                "messages": [{
                    "role": "assistant",
                    "content": json.dumps({
                        "status": "error",
                        "message": "Error processing goal addition"
                    })
                }]
            }
    
    return state | {
        "messages": [{
            "role": "assistant",
            "content": json.dumps({
                "status": "error",
                "message": f"Unknown request type: {request_type}"
            })
        }]
    }
