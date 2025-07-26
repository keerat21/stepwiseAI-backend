# db.py

import mysql.connector
from mysql.connector import Error
from config import configDB
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Global connection
db_conn = None

def init_tables():
    """Initialize database tables if they don't exist."""
    try:
        cursor = get_cursor()
        
        # Create goals table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS goals (
                goal_id INT AUTO_INCREMENT PRIMARY KEY,
                user_id VARCHAR(255) NOT NULL,
                title VARCHAR(255) NOT NULL,
                category VARCHAR(100) NOT NULL,
                description TEXT,
                deadline DATE NOT NULL,
                days INT NOT NULL,
                milestones JSON,
                email_updates VARCHAR(50) DEFAULT 'never',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Create routines table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS routines (
                routine_id INT AUTO_INCREMENT PRIMARY KEY,
                goal_id INT NOT NULL,
                day_number INT NOT NULL,
                description TEXT NOT NULL,
                FOREIGN KEY (goal_id) REFERENCES goals(goal_id)
            )
        """)
        
        commit()
        logger.info("Database tables initialized successfully")
    except Error as e:
        logger.error(f"Error initializing tables: {e}")
        raise

def get_cursor():
    """Get a database cursor, ensuring connection is active."""
    global db_conn
    try:
        if db_conn is None or not db_conn.is_connected():
            logger.info("Establishing new database connection...")
            db_conn = mysql.connector.connect(
                host=configDB["host"],
                user=configDB["user"],
                password=configDB["password"],
                database=configDB["database"]
            )
            logger.info("Database connection established successfully")
            # Initialize tables on first connection
            init_tables()
        return db_conn.cursor(dictionary=True)
    except Error as e:
        logger.error(f"Error connecting to MySQL: {e}")
        raise

def commit():
    """Commit the current transaction."""
    global db_conn
    try:
        if db_conn and db_conn.is_connected():
            db_conn.commit()
            logger.info("Transaction committed successfully")
        else:
            logger.error("No active database connection for commit")
            raise Error("No active database connection")
    except Error as e:
        logger.error(f"Error committing transaction: {e}")
        raise

def close_connection():
    """Close the database connection."""
    global db_conn
    try:
        if db_conn and db_conn.is_connected():
            db_conn.close()
            logger.info("Database connection closed")
    except Error as e:
        logger.error(f"Error closing database connection: {e}")
        raise
