# db.py

import mysql.connector
from mysql.connector import Error
import json

# Configuration
DB_CONFIG = {
    "host": "localhost",        # or your RDS endpoint
    "user": "root",
    "password": "rootroot",
    "database": "goal_achiever"
}

# Global connection
db_conn = None

def ensure_connection():
    """Ensure database connection is active."""
    global db_conn
    try:
        if not db_conn or not db_conn.is_connected():
            db_conn = mysql.connector.connect(**DB_CONFIG)
            if db_conn.is_connected():
                print("✅ Connected to MySQL")
    except Error as e:
        print("❌ MySQL connection error:", e)
        raise ConnectionError(f"Failed to connect to MySQL: {str(e)}")

# Get a cursor
def get_cursor():
    ensure_connection()
    return db_conn.cursor(dictionary=True)  # returns rows as dicts

# Commit changes
def commit():
    if db_conn and db_conn.is_connected():
        db_conn.commit()

# Close connection
def close():
    if db_conn and db_conn.is_connected():
        db_conn.close()
