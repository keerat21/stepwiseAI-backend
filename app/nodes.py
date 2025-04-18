from langchain_core.messages.ai import AIMessage
from langchain_core.messages.tool import ToolMessage
from random import randint
from .schema import OrderState
from .tools import order_tools
from fastapi import WebSocket

# External state
active_users = {}

BARISTABOT_SYSINT = (
    "system",
    "You are a BaristaBot, an interactive cafe ordering system. A human will talk to you about the "
    "available products you have and you will answer any questions about menu items (and only about "
    "menu items - no off-topic discussion, but you can chat about the products and their history). "
    "The customer will place an order for 1 or more items from the menu, which you will structure "
    "and send to the ordering system after confirming the order with the human. "
    "\n\n"
    "Add items to the customer's order with add_to_order, and reset the order with clear_order. "
    "To see the contents of the order so far, call get_order (this is shown to you, not the user) "
    "Always confirm_order with the user (double-check) before calling place_order. Calling confirm_order will "
    "display the order items to the user and returns their response to seeing the list. Their response may contain modifications. "
    "Always verify and respond with drink and modifier names from the MENU before adding them to the order. "
    "If you are unsure a drink or modifier matches those on the MENU, ask a question to clarify or redirect. "
    "You only have the modifiers listed on the menu. "
    "Once the customer has finished ordering items, Call confirm_order to ensure it is correct then make "
    "any necessary updates and then call place_order. Once place_order has returned, thank the user and "
    "say goodbye!"
    "\n\n"
    "If any of the tools are unavailable, you can break the fourth wall and tell the user that "
    "they have not implemented them yet and should keep reading to do so.",
)

WELCOME_MSG = "Welcome to the BaristaBot cafe. How may I serve you today?"

def chatbot_with_tools(llm):
    async def node(state: OrderState) -> OrderState:
        if state["messages"]:
            output = await llm.ainvoke([BARISTABOT_SYSINT] + state["messages"])
        else:
            output = AIMessage(content=WELCOME_MSG)
        return {**state, "messages": [output]}
    return node

async def human_node(state: OrderState) -> OrderState:
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

async def order_node(state: OrderState) -> OrderState:
    from .websocket_handler import active_users  # avoid circular import
    user_id = state["user_id"]
    ws = active_users[user_id]
    tool_msg = state["messages"][-1]
    order = state.get("order", [])
    outbound_msgs = []

    for tool_call in tool_msg.tool_calls:
        name = tool_call["name"]
        args = tool_call["args"]

        if name == "add_to_order":
            order.append(f"{args['drink']} ({', '.join(args['modifiers'])})")
            await ws.send_json({"action": "updateOrder", "text": order})
            response = "\n".join(order)
        elif name == "confirm_order":
            await ws.send_json({"action": "finalizeOrder", "order": [
                {"name": item.split('(')[0], "price": 4.99, "quantity": 1} for item in order
            ]})
            confirm = await ws.receive_json()
            response = confirm.get("text", "Yes")
        elif name == "get_order":
            response = "\n".join(order)
        elif name == "clear_order":
            order.clear()
            response = None
        elif name == "place_order":
            response = randint(1, 5)
            state["finished"] = True
        else:
            raise NotImplementedError(name)

        outbound_msgs.append(ToolMessage(content=response, name=name, tool_call_id=tool_call["id"]))

    await ws.send_json({
        "action": "updateOrder",
        "order": [{"name": item.split(')')[0], "price": 4.99, "quantity": 1} for item in order]
    })

    return {"messages": outbound_msgs, "order": order, "finished": state["finished"]}

def maybe_exit_human_node(state: OrderState):
    return "__end__" if state.get("finished") else "chatbot"

def maybe_route_to_tools(state: OrderState, tool_node):
    msg = state["messages"][-1]
    if state.get("finished"):
        return "__end__"
    elif hasattr(msg, "tool_calls") and any(t["name"] in tool_node.tools_by_name for t in msg.tool_calls):
        return "tools"
    else:
        return "ordering" if msg.tool_calls else "human"
