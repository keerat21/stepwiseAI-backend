from collections.abc import Iterable
from langchain_core.tools import tool
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnablePassthrough
from langchain_google_genai import ChatGoogleGenerativeAI
from config import llm
from .db_conn import get_cursor, commit
import json
from typing import List, Dict, Any, Optional, Union, TypedDict
import logging
from datetime import datetime
import re

logger = logging.getLogger(__name__)

# Initialize the LLM with tools
llm_with_tools = llm.bind_tools([])

def clean_llm_json(raw: str):
    """
    Cleans up common LLM output issues to allow safe JSON parsing.
    """
    # Remove Markdown-style code fences
    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?", "", raw)
    raw = re.sub(r"```$", "", raw)

    # Replace smart quotes with normal quotes
    raw = raw.replace("‘", "'").replace("’", "'").replace(""", '"').replace(""", '"')

    return raw.strip()

def get_elapsed_days(goal_id: int) -> int:
    """Calculate how many days have elapsed since the goal started."""
    cursor = get_cursor()
    cursor.execute("""
        SELECT DATEDIFF(CURRENT_TIMESTAMP, created_at) as elapsed_days
        FROM goals
        WHERE goal_id = %s
    """, (goal_id,))
    result = cursor.fetchone()
    return result['elapsed_days'] if result else 0

def get_goal_progress_query(goal_id: int) -> dict:
    """Get goal progress including elapsed days and completion status."""
    cursor = get_cursor()
    cursor.execute("""
        SELECT g.*, 
               DATEDIFF(CURRENT_TIMESTAMP, g.created_at) as elapsed_days,
               COUNT(DISTINCT l.day_number) as completed_days
        FROM goals g
        LEFT JOIN logs l ON g.goal_id = l.goal_id
        WHERE g.goal_id = %s
        GROUP BY g.goal_id
    """, (goal_id,))
    return cursor.fetchone()

@tool
def goal_menu() -> list[tuple[str, int]]:
    """List all goals with their duration (in days)."""
    cursor = get_cursor()
    cursor.execute("SELECT title, days FROM goals;")
    return cursor.fetchall()

# These functions have no body; LangGraph does not allow @tools to update
# the conversation state, so you will implement a separate node to handle
# state updates. Using @tools is still very convenient for defining the tool
# schema, so empty functions have been defined that will be bound to the LLM
# but their implementation is deferred to the order_node.

@tool
def add_goal(title: str, category: str, description: str, deadline: str, user_id: str, milestones: List[str] = None, email_updates: str = None) -> str:
    """Add a new goal to the user's list."""
    cursor = None
    try:
        logger.info(f"Adding goal: {title} for user {user_id}")
        cursor = get_cursor()
        
        # Calculate days from deadline
        try:
            if deadline:
                deadline_date = datetime.strptime(deadline, "%Y-%m-%d")
                days = max(1, (deadline_date - datetime.now()).days)
            else:
                days = 30  # Default to 30 days if no deadline
        except ValueError:
            days = 30  # Default to 30 days if invalid deadline format
        logger.debug(f"Days until deadline: {days}")
        
        # Format email updates - convert to single string value
        valid_email_updates = ["daily", "weekly", "monthly", "never"]
        email_updates = email_updates or "never"
        if email_updates not in valid_email_updates:
            email_updates = "never"
        logger.debug(f"Email updates set to: {email_updates}")
        
        # Format milestones
        milestones = milestones or []
        if isinstance(milestones, str):
            try:
                milestones = json.loads(milestones)
            except json.JSONDecodeError:
                milestones = []
        elif not isinstance(milestones, list):
            milestones = []
        
        milestones_json = json.dumps([str(milestone) for milestone in milestones])
        logger.debug(f"Formatted milestones: {milestones_json}")
        
        # Insert the goal
        cursor.execute("""
            INSERT INTO goals (user_id, title, category, description, deadline, days, milestones, email_updates)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            user_id, 
            title, 
            category, 
            description, 
            deadline, 
            days,
            milestones_json,
            email_updates
        ))
        
        goal_id = cursor.lastrowid
        logger.info(f"Goal inserted with ID: {goal_id}")
        
        # Generate routine for the goal
        routine = generate_routine.invoke({"goal": title, "days": days, "milestones": milestones})
        # logger.info(f"Generated routine in add_goal: {routine}")
        
        # Insert routine into database
        for day_number, task in enumerate(routine, 1):
            cursor.execute("""
                INSERT INTO routines (goal_id, day_number, description)
                VALUES (%s, %s, %s)
            """, (goal_id, day_number, task))
            logger.debug(f"Inserted routine for day {day_number}")
        
        # Commit the transaction
        commit()
        logger.info(f"Successfully added goal '{title}' with routine")
        
        # Verify the goal was added
        cursor.execute("""
            SELECT * FROM goals WHERE goal_id = %s
        """, (goal_id,))
        saved_goal = cursor.fetchone()
        
        if not saved_goal:
            raise Exception("Goal was not saved properly")
            
        # Format the response
        response = {
            "status": "success",
            "message": f"Added goal: {title}",
            "goal": {
                "id": goal_id,
                "title": title,
                "category": category,
                "description": description,
                "deadline": deadline,
                "milestones": milestones,
                "email_updates": email_updates,
                "routine": routine
            }
        }
        
        # logger.info(f"Response: {response}")
        return json.dumps(response)
        
    except Exception as e:
        logger.error(f"Error adding goal: {str(e)}")
        # Try to rollback if possible
        try:
            if cursor and cursor._connection:
                cursor._connection.rollback()
                logger.info("Transaction rolled back")
        except Exception as rollback_error:
            logger.error(f"Error during rollback: {str(rollback_error)}")
        
        error_response = {
            "status": "error",
            "message": f"Error adding goal: {str(e)}"
        }
        return json.dumps(error_response)

@tool
def log_progress(goal_index: int, log: str = "Logged progress", user_id: str = None) -> str:
    """Log progress for a specific goal."""
    return f"Logged progress for goal {goal_index}: {log}"

@tool
def modify_goal(index: int, title: str = None, category: str = None, description: str = None, deadline: str = None, user_id: str = None) -> str:
    """Modify an existing goal's details."""
    try:
        if deadline:
            deadline_date = datetime.strptime(deadline, "%Y-%m-%d")
            days = max(1, (deadline_date - datetime.now()).days)
            routine = generate_routine(title or f"Goal {index}", days)
            return f"Updated goal {index} with new deadline: {deadline}\nRoutine:\n" + "\n".join(routine)
        return f"Updated goal {index}"
    except Exception as e:
        logger.error(f"Error modifying goal: {str(e)}")
        return f"Error modifying goal: {str(e)}"

@tool
def get_goals(user_id: str = None) -> str:
    """Get all goals for the user."""
    try:
        cursor = get_cursor()
        cursor.execute("""
            SELECT g.*, 
                   DATEDIFF(CURRENT_TIMESTAMP, g.created_at) as elapsed_days,
                   DATEDIFF(g.deadline, CURRENT_DATE) as days_remaining,
                   COUNT(DISTINCT r.routine_id) as total_routines
            FROM goals g
            LEFT JOIN routines r ON g.goal_id = r.goal_id
            WHERE g.user_id = %s
            GROUP BY g.goal_id
        """, (user_id,))
        
        goals = cursor.fetchall()
        if not goals:
            return "No goals found."
            
        result = []
        for goal in goals:
            # Safely parse milestones and email_updates
            try:
                milestones = json.loads(goal['milestones']) if goal['milestones'] else []
            except (json.JSONDecodeError, TypeError):
                milestones = []
            
            try:
                email_updates = json.loads(goal['email_updates']) if goal['email_updates'] else {}
            except (json.JSONDecodeError, TypeError):
                email_updates = {}
            
            result.append(
                f"Category: {goal['category']}\n"
                f"Title: {goal['title']}\n"
                f"Description: {goal['description']}\n"
                f"Deadline: {goal['deadline']}\n"
                f"Progress: {goal['total_routines']}/{goal['days']} days completed"
            )
            
        return "\n\n".join(result)
    except Exception as e:
        logger.error(f"Error getting goals: {str(e)}")
        return f"Error getting goals: {str(e)}"

@tool
def get_goals_by_category(category: str, user_id: str = None) -> str:
    """Get goals filtered by category."""
    return f"Retrieved goals in category: {category}"

@tool
def clear_goals(user_id: str = None) -> str:
    """Clear all goals for the user."""
    return "Cleared all goals"

@tool
def generate_routine(goal: str, days: int, milestones: List[str] = None) -> List[str]:
    """Generate a daily routine for achieving a goal."""
    try:
        # Create milestone context if milestones are provided
        milestone_context = ""
        if milestones:
            milestone_context = "\nMilestones to achieve:\n"
            for i, milestone in enumerate(milestones, 1):
                milestone_context += f"{i}. {milestone}\n"
            
            # Calculate days per milestone
            days_per_milestone = max(1, days // len(milestones))
            milestone_context += f"\nEach milestone should be achieved within approximately {days_per_milestone} days. It is important to add milestones in activities that are mentioned\n"

        # Create a prompt for the LLM
        prompt = f"""Generate a detailed learning schedule for achieving the goal: {goal}
        Time frame: {days} days
        {milestone_context}
        
        Guidelines:
        1. Break down the goal into daily topics and concepts
        2. Focus on progressive learning (basics to advanced)
        3. Include practical exercises and projects
        4. Allocate time for review and practice
        5. Consider the total number of days available
        6. If milestones are provided, ensure they are distributed evenly across the schedule
        7. Each milestone should have sufficient time for practice and mastery
        8. Include specific activities that directly contribute to achieving each milestone
        9. Add review days before milestone completion
        10. Include practical projects that demonstrate milestone achievement
        
        Format: Return a JSON array of objects with 'day', 'topic', 'activities', 'milestone', and 'focus' fields.
        Example: [
            {{
                "day": 1,
                "topic": "Introduction to Basics",
                "activities": ["Overview of concepts", "Basic syntax practice"],
                "milestone": "Complete initial assessment",
                "focus": "Foundation building"
            }},
            {{
                "day": 2,
                "topic": "Core Concepts",
                "activities": ["Deep dive into fundamentals", "Hands-on exercises"],
                "milestone": null,
                "focus": "Skill development"
            }}
        ]
        
        Make the schedule realistic and focused on topic progression, ensuring milestones are achievable.
        Each milestone should have dedicated days for learning, practice, and assessment."""

        # Get response from LLM
        response = llm.invoke(prompt)
        # logger.info(f"LLM response: {response.content}")
        
        # Parse the response
        try:
            cleaned_llm_response = clean_llm_json(response.content)
            # logger.info(f"Routine: {cleaned_llm_response}")
            routine = json.loads(cleaned_llm_response)
            if isinstance(routine, list):
                # Format each day's schedule
                formatted_routine = []
                for item in routine:
                    day = item.get('day', 1)
                    topic = item.get('topic', '')
                    activities = item.get('activities', [])
                    milestone = item.get('milestone')
                    focus = item.get('focus', '')
                    
                    # Format the day's schedule
                    day_schedule = f"Day {day}: {topic}\n  • Focus: {focus}\n  • " + "\n  • ".join(activities)
                    
                    # Add milestone if present
                    if milestone:
                        day_schedule += f"\n  🎯 Milestone: {milestone}"
                    
                    formatted_routine.append(day_schedule)
                return formatted_routine
            return [f"Day 1: Introduction to {goal}\n  • Basic concepts\n  • Initial practice"]
        except json.JSONDecodeError:
            logger.error("Failed to parse LLM response as JSON")
            return [f"Day 1: Introduction to {goal}\n  • Basic concepts\n  • Initial practice"]
            
    except Exception as e:
        logger.error(f"Error generating routine: {str(e)}")
        return [f"Day 1: Introduction to {goal}\n  • Basic concepts\n  • Initial practice"]

@tool
def list_goal_tables() -> list[str]:
    """List all database tables related to goals."""
    cursor = get_cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = cursor.fetchall()
    return [t[0] for t in tables]

@tool
def describe_goal_table(table_name: str) -> list[tuple[str, str]]:
    """Get the schema of a table by name."""
    cursor = get_cursor()
    cursor.execute(f"PRAGMA table_info({table_name});")
    return [(row[1], row[2]) for row in cursor.fetchall()]

@tool
def execute_goal_query(sql: str) -> list[list[str]]:
    """Execute a custom SQL query on the goal DB."""
    cursor = get_cursor()
    cursor.execute(sql)
    return cursor.fetchall()

@tool
def get_goal_progress(goal_id: int) -> str:
    """Get detailed progress information for a goal including elapsed days and completion status."""
    try:
        progress = get_goal_progress_query(goal_id)
        
        if not progress:
            return "Goal not found."
            
        elapsed_days = progress['elapsed_days']
        completed_days = progress['completed_days']
        total_days = progress['days']
        
        # Calculate completion percentage
        completion_pct = (completed_days / total_days * 100) if total_days > 0 else 0
        
        return f"""
Goal: {progress['title']}
Days Elapsed: {elapsed_days}
Days Completed: {completed_days} out of {total_days}
Completion: {completion_pct:.1f}%
Status: {'On Track' if elapsed_days <= total_days else 'Overdue'}
"""
    except Exception as e:
        return f"Error getting goal progress: {str(e)}"

@tool
def get_user_goals(user_id: str) -> str:
    """Return all goals and their progress for a given user."""
    try:
        cursor = get_cursor()
        cursor.execute("""
            SELECT g.*, 
                   DATEDIFF(CURRENT_TIMESTAMP, g.created_at) as elapsed_days,
                   DATEDIFF(g.deadline, CURRENT_DATE) as days_remaining,
                   COUNT(DISTINCT l.day_number) as completed_days
            FROM goals g
            LEFT JOIN logs l ON g.goal_id = l.goal_id
            WHERE g.user_id = %s
            GROUP BY g.goal_id
        """, (user_id,))
        goals = cursor.fetchall()
        
        if not goals:
            return "No goals found."
            
        result = []
        for goal in goals:
            elapsed = goal['elapsed_days']
            completed = goal['completed_days']
            total = goal['days']
            remaining = goal['days_remaining']
            status = "On Track" if remaining > 0 else "Overdue"
            
            # Parse milestones and email preferences
            milestones = json.loads(goal['milestones'] or '[]')
            email_updates = json.loads(goal['email_updates'] or '{}')
            
            # Format milestones
            milestones_text = "\n  Milestones:"
            for milestone in milestones:
                completed_status = "✓" if milestone.get('completed', False) else "○"
                milestones_text += f"\n    {completed_status} {milestone['title']} - {milestone['target_date']}"
            
            # Format email preferences
            email_prefs = "\n  Email Updates:"
            if email_updates.get('daily'): email_prefs += "\n    • Daily updates"
            if email_updates.get('weekly'): email_prefs += "\n    • Weekly reports"
            if email_updates.get('aiSuggestions'): email_prefs += "\n    • AI suggestions"
            if email_updates.get('adaptive'): email_prefs += "\n    • Adaptive plans"
            
            result.append(
                f"Category: {goal['category']}\n"
                f"Title: {goal['title']}\n"
                f"Description: {goal['description']}\n"
                f"  - Started: {goal['created_at'].strftime('%Y-%m-%d')}\n"
                f"  - Deadline: {goal['deadline'].strftime('%Y-%m-%d')}\n"
                f"  - Days Remaining: {remaining}\n"
                f"  - Elapsed: {elapsed} days\n"
                f"  - Completed: {completed}/{total} days\n"
                f"  - Status: {status}"
                f"{milestones_text}"
                f"{email_prefs}"
            )
            
        return "\n\n".join(result)
    except Exception as e:
        print(f"Error in get_user_goals: {str(e)}")  # Debug print
        return f"Error getting user goals: {str(e)}"

@tool
def get_routine_for_goal(goal_id: int) -> list[str]:
    """Must call generate_routine tool then use this tool. Return daily routine for a given goal ID."""
    cursor = get_cursor
    cursor.execute("""SELECT day_number, description FROM routines
                      WHERE goal_id = ? ORDER BY day_number""", (goal_id,))
    return [f"Day {day}: {desc}" for day, desc in cursor.fetchall()]

# Tool collections
goal_auto_tools = [
    add_goal,
    get_goals,
    generate_routine,
    get_goal_progress,
    get_user_goals,
    get_routine_for_goal,
    list_goal_tables,
    describe_goal_table,
    execute_goal_query
]

goal_action_tools = [
    add_goal,
    get_goals,
    generate_routine,
]

# Bind tools to LLM
llm_with_tools = llm.bind_tools(goal_auto_tools)
