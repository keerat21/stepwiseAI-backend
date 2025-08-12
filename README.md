# Goal Tracker API - Simplified

A simplified FastAPI application that provides authentication and goal management functionality.

## Features

- **Google OAuth Authentication**: Secure user authentication using Google OAuth
- **Add Goals**: Create and store user goals with routines

## Setup

1. **Install dependencies**:
   ```bash
   pip install fastapi uvicorn python-dotenv mysql-connector-python google-auth
   ```

2. **Database setup**:
   - Install MySQL server
   - Create database: `CREATE DATABASE goal_achiever;`

3. **Environment variables**:
   Create a `.env` file with:
   ```
   GOOGLE_CLIENT_ID=your_google_oauth_client_id
   ```

4. **Run the application**:
   ```bash
   python -m uvicorn main:app --reload
   ```

## API Endpoints

### WebSocket: `/ws`

#### Authentication
```json
{
  "type": "auth",
  "args": {
    "token": "google_oauth_token"
  }
}
```

#### Add Goal
```json
{
  "type": "add_goal",
  "args": {
    "user": "user_id",
    "title": "Goal Title",
    "category": "Category",
    "description": "Goal description",
    "deadline": "2024-12-31",
    "emailUpdates": "weekly",
    "milestones": ["Milestone 1", "Milestone 2"]
  }
}
```

## File Structure

```
├── main.py                 # FastAPI application entry point
├── config.py              # Configuration settings
├── app/
│   ├── __init__.py
│   ├── auth.py            # Google OAuth authentication
│   ├── db_conn.py         # Database connection and setup
│   ├── schema.py          # Data models
│   ├── tools.py           # Goal management tools
│   └── websocket_handler.py # WebSocket message handling
└── Requirements           # Dependencies list
``` 