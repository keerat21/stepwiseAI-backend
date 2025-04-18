from langgraph.graph import StateGraph, START, END
from langgraph.prebuilt import ToolNode
from .schema import OrderState
from .tools import auto_tools, order_tools
from .nodes import chatbot_with_tools, human_node, order_node, maybe_exit_human_node, maybe_route_to_tools
from config import llm

llm_with_tools = llm.bind_tools(auto_tools + order_tools)
tool_node = ToolNode(auto_tools)

def build_flow():
    builder = StateGraph(OrderState)
    builder.add_node("chatbot", chatbot_with_tools(llm_with_tools))
    builder.add_node("human", human_node)
    builder.add_node("tools", tool_node)
    builder.add_node("ordering", order_node)

    builder.add_conditional_edges("chatbot", lambda state: maybe_route_to_tools(state, tool_node))
    builder.add_conditional_edges("human", maybe_exit_human_node)
    builder.add_edge("tools", "chatbot")
    builder.add_edge("ordering", "chatbot")
    builder.add_edge(START, "chatbot")
    
    return builder.compile()
