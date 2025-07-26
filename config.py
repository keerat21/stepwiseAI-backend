from dotenv import load_dotenv
import os
from langchain_google_genai import ChatGoogleGenerativeAI

# Load variables from .env file
load_dotenv()

# Access the key from the environment
google_api_key = os.getenv("GOOGLE_API_KEY")
google_client_id = os.getenv("GOOGLE_CLIENT_ID")
print(google_api_key)

# Setup Gemini LLM
llm = ChatGoogleGenerativeAI(
    model="gemini-1.5-flash",
    google_api_key=google_api_key,
    temperature=0.1
)

# Config for LangGraph
configAuth = {
    "GOOGLE_CLIENT_ID": google_client_id,  # Replace with your actual Google Client ID
}

configDB = {
    "host": "localhost",
    "user": "root",
    "password": "rootroot",
    "database": "goal_achiever"
}

config = {"recursion_limit": 100}