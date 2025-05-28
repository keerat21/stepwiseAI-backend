from langchain_core.messages.ai import AIMessage
from langchain_core.messages.tool import ToolMessage
from random import randint
from .schema import GoalState
from .tools import goal_auto_tools, goal_action_tools, llm_with_tools
from fastapi import WebSocket
from typing import Literal
# External state
active_users = {}


GOAL_TRACKING_SYS_PROMPT = (
    "system",
    "You are GoalSetterAI, a supportive assistant that helps users:"
    "- Set personal development goals"
    "- Break down goals into daily routines"
    "- Log daily progress and track consistency"
    "Use the user id to identify the user and their goals. Do not ask the user for their id."

   " Use tools when the user wants to add, review, or modify goals and routines."
   " Always aim to assist the user in staying motivated and organized."
)

# This is the message with which the system opens the conversation.
WELCOME_GOAL_MSG = "Welcome to the Goal Setter AI. How may I serve you today?"

async def human_node(state: GoalState) -> GoalState:
    user_id = state["user_id"]
    ws = active_users.get(user_id)
    if not ws:
        raise RuntimeError("WebSocket not found")

    last_msg = state["messages"][-1]
    await ws.send_json({"action": "speak", "text": last_msg.content})

    while True:
        msg = await ws.receive_json()
        if msg.get("type") == "userSpeech":
            break

    if msg["text"].lower() in {"q", "quit", "exit", "bye"}:
        state["finished"] = True

    return state | {"messages": [{"role": "user", "content": msg["text"]}]}

def goal_ai_with_tools(state: GoalState) -> GoalState:
    defaults = {"goals": [], "routines": {}, "finished": False}

    if state["messages"]:
        new_output = llm_with_tools.invoke([GOAL_TRACKING_SYS_PROMPT] + state["messages"])
    else:
        new_output = AIMessage(content=WELCOME_GOAL_MSG)

    # 🛡️ Prevent Gemini from crashing on empty content
    if not new_output.content.strip():
        new_output.content = "🛠️ Working on your request..."

    return defaults | state | {"messages": state.get("messages", []) + [new_output]}


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

    for tool_call in tool_msg.tool_calls:

        if "user_id" in tool_call["args"]:
            tool_call["args"]["user_id"] = state["user_id"]
             
        if tool_call["name"] == "add_goal":
            goal_title = tool_call["args"]["title"]
            days = int(tool_call["args"].get("days", 7))
            goals.append(goal_title)
            routines[goal_title] = goal_action_tools.generate_routine(goal_title, days)
            response = f"Added goal: {goal_title}\nRoutine: \n" + "\n".join(routines[goal_title])

        elif tool_call["name"] == "log_progress":
            goal_index = tool_call["args"]["goal_index"]
            log = tool_call["args"].get("log", "Logged progress")
            response = f"Log for '{goals[goal_index]}': {log}"

        elif tool_call["name"] == "modify_goal":
            index = tool_call["args"]["index"]
            new_title = tool_call["args"].get("title", goals[index])
            new_days = int(tool_call["args"].get("days", 7))
            goals[index] = new_title
            routines[new_title] = goal_action_tools.generate_routine(new_title, new_days)
            response = f"Updated goal: {new_title}\nRoutine: \n" + "\n".join(routines[new_title])

        elif tool_call["name"] == "get_goals":
            response = "\n".join(goals) if goals else "No goals set."

        elif tool_call["name"] == "clear_goals":
            goals.clear()
            routines.clear()
            response = "Cleared all goals."

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

    elif hasattr(msg, "tool_calls") and len(msg.tool_calls) > 0:
        tool_names = [tool["name"] for tool in msg.tool_calls]
        if any(name in [t.name for t in goal_action_tools] for name in tool_names):
            return "goal_actions"
        else:
            return "goal_tools"

    return "human"
