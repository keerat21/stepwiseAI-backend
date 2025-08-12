from dotenv import load_dotenv
import os
from langchain_google_genai import ChatGoogleGenerativeAI

# Load variables from .env file
load_dotenv()

# Access the key from the environment
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")

# Gemini LLM setup
llm = ChatGoogleGenerativeAI(
    model="gemini-1.5-flash",
    google_api_key=GOOGLE_API_KEY,
    temperature=0.1
)

# Database configuration
DB_CONFIG = {
    "host": "localhost",
    "user": "root",
    "password": "rootroot",
    "database": "goal_achiever"
}