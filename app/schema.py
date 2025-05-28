from typing import Annotated
from typing_extensions import TypedDict
from langgraph.graph.message import add_messages

class GoalState(TypedDict):
    """State representing the user's goal-setting conversation."""
    user_id: str
    messages: Annotated[list, add_messages]
    goals: list[str]
    routines: dict[str, list[str]]
    finished: bool
