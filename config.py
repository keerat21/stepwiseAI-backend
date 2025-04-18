from dotenv import load_dotenv
import os
from langchain_google_genai import ChatGoogleGenerativeAI

# Load variables from .env file
load_dotenv()

# Access the key from the environment
google_api_key = os.getenv("GOOGLE_API_KEY")

# Setup Gemini LLM
llm = ChatGoogleGenerativeAI(
    model="gemini-2.0-flash",
    google_api_key=google_api_key
)

# Config for LangGraph
config = {"recursion_limit": 100}
