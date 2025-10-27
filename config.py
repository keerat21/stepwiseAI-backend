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
    model="gemini-2.0-flash-lite",
    google_api_key=GOOGLE_API_KEY,
    temperature=0.1
)

# Database configuration

DB_CONFIG = {
    "host":     os.environ["DB_HOST"],
    "user":     os.environ["DB_USER"],
    "password": os.environ["DB_PASSWORD"],
    "database": os.environ["DB_NAME"],
    "port":     int(os.environ.get("DB_PORT", "3306")),
    "connection_timeout": 5,
}