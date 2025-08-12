from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import Tool
from langchain_core.runnables import RunnableSequence
from app.tools import add_goal
from config import llm

# System prompt for Gemini
SYSTEM_PROMPT = (
    "You are GoalSetterAI, a supportive assistant that helps users set personal development goals, break them into daily routines, and log progress. "
    "When a user describes a goal, break it down into a step-by-step routine with daily tasks and milestones. "
    "Then call the add_goal tool with the structured plan, including milestones and a suggested routine. "
    "Always provide a clear, actionable plan."
)

def run_goal_planner(user_id: str, user_message: str):
    # Compose the prompt
    messages = [
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=user_message)
    ]
    # Register the add_goal tool
    tools = [add_goal]
    # Create the LLM chain with tool support
    chain = llm.bind_tools(tools)
    # Run the LLM with the prompt
    result = chain.invoke(messages)
    print("result AImssg: ", type(result.content)) 
    return result.content