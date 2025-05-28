from langgraph.graph import StateGraph, START, END
from langgraph.prebuilt import ToolNode
from .schema import GoalState
from .tools import goal_auto_tools, goal_action_tools, llm_with_tools
from .nodes import *
from config import llm

def build_flow():
# Define the graph
    graph_builder = StateGraph(GoalState)

    # Nodes
    graph_builder.add_node("goal_ai", goal_ai_with_tools)
    graph_builder.add_node("human", human_node)
    graph_builder.add_node("goal_tools", ToolNode(goal_auto_tools))
    graph_builder.add_node("goal_actions", ToolNode(goal_action_tools))

    # Routing
    # AI model may send to tools or human
    graph_builder.add_conditional_edges("goal_ai", maybe_route_goal_tools)
    # Human routes to AI or END
    graph_builder.add_conditional_edges("human", maybe_exit_human_node)

    # After tool execution, go back to AI
    graph_builder.add_edge("goal_tools", "goal_ai")
    graph_builder.add_edge("goal_actions", "goal_ai")

    # Start from AI
    graph_builder.add_edge(START, "goal_ai")

    # Compile graph
    goal_flow_graph = graph_builder.compile()
    
    return goal_flow_graph
