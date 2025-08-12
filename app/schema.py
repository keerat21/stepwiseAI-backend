from typing import TypedDict, List, Dict, Any, Optional
from datetime import datetime

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
