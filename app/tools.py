from collections.abc import Iterable
from langchain_core.tools import tool
from config import llm
from .db_conn import get_cursor, commit
import json

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
def add_goal(user_id: int, title: str, days: int, description: str = "") -> str:
    """
    Add a new goal for a user and create a structured daily routine using the LLM.
    """
    try:
        print(f"Adding goal: {title} for user {user_id}")
        cursor = get_cursor()
        
        # First insert the goal
        cursor.execute("""
            INSERT INTO goals (user_id, title, days, description)
            VALUES (%s, %s, %s, %s);
        """, (user_id, title, days, description))

        goal_id = cursor.lastrowid

        # Generate structured routine using the LLM
        routine = generate_routine.invoke({"goal": title, "days": days})
        
        # Insert each day's tasks into the routines table
        for day_data in routine:
            day_number = day_data["day"]
            tasks = day_data["tasks"]
            
            # Store the structured data as JSON
            routine_json = json.dumps({
                "title": day_data["title"],
                "tasks": tasks
            })
            
            cursor.execute("""
                INSERT INTO routines (goal_id, day_number, description)
                VALUES (%s, %s, %s);
            """, (goal_id, day_number, routine_json))

        commit()
        return f"✅ Goal '{title}' added with a {days}-day structured routine."

    except Exception as e:
        print(f"Error in add_goal: {str(e)}")
        return f"❌ Failed to add goal: {str(e)}"

@tool
def generate_routine(goal: str, days: int) -> list[dict]:
    """Ask the LLM to generate a study routine for the goal over given days."""
    prompt = f"""
    You are a goal planning assistant.

    Please generate a {days}-day structured daily learning routine to help someone achieve the following goal: "{goal}".

    Output the routine as a JSON array of objects, where each object represents a day with the following structure:
    {{
        "day": number,
        "title": "Day title",
        "tasks": ["task1", "task2", "task3"]
    }}

    Each day should have a clear title followed by 2-3 specific tasks. Be concise and practical.
    Only generate content in valid JSON format. No markdown formatting or code blocks.
    """

    try:
        response = llm.invoke(prompt)
        print(f"Raw LLM Response: {response.content}")  # Debug print

        # Clean the response - remove markdown code blocks if present
        content = response.content
        if content.startswith('```'):
            # Remove markdown code block markers and language specifier
            content = content.split('\n', 1)[1]  # Remove first line
            content = content.rsplit('\n', 1)[0]  # Remove last line
            content = content.strip()

        # Try to parse the response as JSON
        routine = json.loads(content)
        
        # Validate and clean the routine
        if not isinstance(routine, list):
            raise ValueError("Response is not a list")
            
        # Ensure each day has the required structure
        cleaned_routine = []
        for i, day in enumerate(routine):
            if not isinstance(day, dict):
                day = {"day": i + 1, "title": f"Day {i + 1}", "tasks": [str(day)]}
            
            # Ensure required fields exist
            day_data = {
                "day": day.get("day", i + 1),
                "title": day.get("title", f"Day {i + 1}"),
                "tasks": day.get("tasks", [f"Work on {goal}"])
            }
            cleaned_routine.append(day_data)
            
        print(f"Cleaned Routine: {cleaned_routine}")  # Debug print
        return cleaned_routine

    except json.JSONDecodeError as e:
        print(f"JSON Decode Error: {e}")  # Debug print
        # Fallback: If JSON parsing fails, create a simple structured routine
        return [
            {
                "day": i + 1,
                "title": f"Day {i + 1}",
                "tasks": [f"Work on {goal}"]
            }
            for i in range(days)
        ]
    except Exception as e:
        print(f"Error in generate_routine: {e}")  # Debug print
        # Fallback routine
        return [
            {
                "day": i + 1,
                "title": f"Day {i + 1}",
                "tasks": [f"Work on {goal}"]
            }
            for i in range(days)
        ]

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
def get_user_goals(user_id: int) -> str:
    """Return all goals and their progress for a given user."""
    try:
        cursor = get_cursor()
        cursor.execute("""
            SELECT g.*, 
                   DATEDIFF(CURRENT_TIMESTAMP, g.created_at) as elapsed_days,
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
            status = "On Track" if elapsed <= total else "Overdue"
            
            result.append(
                f"{goal['title']} ({total} days)\n"
                f"  - Started: {goal['created_at'].strftime('%Y-%m-%d')}\n"
                f"  - Elapsed: {elapsed} days\n"
                f"  - Completed: {completed}/{total} days\n"
                f"  - Status: {status}"
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

@tool
def log_progress(goal_id: int, day: int, note: str) -> str:
    """Log user progress for a specific day of a goal."""
    try:
        elapsed_days = get_elapsed_days(goal_id)
        
        if day > elapsed_days:
            return f"Cannot log progress for day {day} as only {elapsed_days} days have elapsed."
            
        cursor = get_cursor()
        cursor.execute("""INSERT INTO logs (goal_id, day_number, note, timestamp)
                         VALUES (%s, %s, %s, CURRENT_TIMESTAMP)""", 
                      (goal_id, day, note))
        commit()
        return f"Progress for Day {day} logged successfully."
    except Exception as e:
        return f"Error logging progress: {str(e)}"

goal_action_tools = [add_goal, generate_routine]
goal_auto_tools = [get_user_goals, get_routine_for_goal, log_progress, get_goal_progress]

llm_with_tools = llm.bind_tools(goal_auto_tools + goal_action_tools)
