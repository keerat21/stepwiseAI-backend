import json
import logging
from datetime import datetime
from typing import List
from langchain.tools import tool
from app.db_conn import get_cursor, commit
import re

logger = logging.getLogger(__name__)

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
        
        return json.dumps(response)
        
    except Exception as e:
        logger.error(f"Error adding goal: {e}")
        error_response = {
            "status": "error",
            "message": f"Failed to add goal: {str(e)}"
        }
        return json.dumps(error_response)
    finally:
        if cursor:
            cursor.close()

@tool
def generate_routine(goal: str, days: int, milestones: List[str] = None) -> List[str]:
    """Generate a daily routine for achieving a goal."""
    try:
        from config import llm
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