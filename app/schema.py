from typing import TypedDict, List, Dict, Any, Optional
from datetime import datetime
from langgraph.graph.message import add_messages

class EmailPreferences(TypedDict):
    daily: bool
    weekly: bool
    aiSuggestions: bool
    adaptive: bool

class Milestone(TypedDict):
    title: str
    description: str
    target_date: str
    completed: bool

class Goal(TypedDict):
    id: Optional[int]
    title: str
    category: str
    description: str
    deadline: str
    created_at: datetime
    days: int
    milestones: List[Milestone]
    email_updates: EmailPreferences

class GoalState(TypedDict):
    """State representing the user's goal-setting conversation."""
    user_id: str
    messages: List[Dict[str, Any]]
    goals: List[Goal]
    routines: Dict[str, List[str]]
    finished: bool
