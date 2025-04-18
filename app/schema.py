from typing import Annotated
from typing_extensions import TypedDict
from langgraph.graph.message import add_messages

class OrderState(TypedDict):
    user_id: str
    messages: Annotated[list, add_messages]
    order: list[str]
    finished: bool
