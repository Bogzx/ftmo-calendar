import google.generativeai as genai
import os
from dotenv import load_dotenv

# --- CONFIGURATION ---
# Load environment variables
load_dotenv()
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')

if not GEMINI_API_KEY:
    print("Error: GEMINI_API_KEY not found in environment variables.")
    exit(1)

genai.configure(api_key=GEMINI_API_KEY)

print("Available Gemini Models:")
for m in genai.list_models():
  # The 'generateContent' method is what our script uses.
  if 'generateContent' in m.supported_generation_methods:
    print(f"- {m.name}")