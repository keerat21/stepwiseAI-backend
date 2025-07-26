from google.oauth2 import id_token
from google.auth.transport import requests as grequests

def verify_google_token(token: str, audience: str):
    try:
        idinfo = id_token.verify_oauth2_token(token, grequests.Request(), audience)
        return idinfo  # contains: sub, email, name, picture, etc.
    except Exception as e:
        print(f"❌ Token verification failed: {e}")
        return None
