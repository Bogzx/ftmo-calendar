# main.py
import requests
from bs4 import BeautifulSoup
import datetime
import os
import json
import re
import logging
import google.generativeai as genai
from dotenv import load_dotenv
from dateutil.parser import parse as date_parse

try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo

# Added for timezone-aware datetime objects
from datetime import timezone

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google.auth.exceptions import RefreshError
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

import time
from functools import wraps

# --- LOGGING CONFIGURATION ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("app.log"),
        logging.StreamHandler()
    ]
)

def retry_operation(max_retries=3, delay=5):
    """Decorator to retry a function call upon failure."""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    logging.warning(f"Attempt {attempt + 1}/{max_retries} failed for {func.__name__}: {e}")
                    if attempt < max_retries - 1:
                        time.sleep(delay)
            logging.error(f"All {max_retries} attempts failed for {func.__name__}.")
            return None # Or raise the exception if you prefer
        return wrapper
    return decorator

# --- CRON JOB FIX: Use absolute paths to find files ---
# Get the absolute path of the directory where the script is located
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# Construct absolute paths for required files
ENV_PATH = os.path.join(SCRIPT_DIR, '.env')
CREDENTIALS_PATH = os.path.join(SCRIPT_DIR, 'credentials.json')
TOKEN_PATH = os.path.join(SCRIPT_DIR, 'token.json')

# Load environment variables from the .env file using its absolute path
load_dotenv(dotenv_path=ENV_PATH)

# --- CONFIGURATION ---
# Get the API key from the .env file
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')

# If modifying these scopes, delete the file token.json.
SCOPES = ['https://www.googleapis.com/auth/calendar']
FTMO_URL = os.getenv('FTMO_URL', 'https://ftmo.com/en/trading-updates/')
KEYWORDS = os.getenv('KEYWORDS', 'maintenance,crypto market is closed,ctrader').split(',')
EVENT_SUMMARY = os.getenv('EVENT_SUMMARY', 'cTrader Maintenance/Crypto Market Closure')
CALENDAR_NAME = os.getenv('CALENDAR_NAME', 'Trading') # The name of the sub-calendar to use

class FTMOScraper:
    """
    Scrapes the FTMO trading updates page for relevant information using BeautifulSoup.
    """
    def __init__(self, url: str):
        self.url = url

    @retry_operation(max_retries=3, delay=10)
    def get_latest_update(self) -> str | None:
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            }
            # Added timeout to prevent hanging
            response = requests.get(self.url, headers=headers, timeout=30)
            response.raise_for_status()
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Primary method: Look for the specific container
            latest_update_container = soup.find('div', class_='trup-primary')
            if latest_update_container:
                return latest_update_container.get_text(separator=' ', strip=True)
            
            # Fallback method: Look for the first article or generic container if class changed
            logging.warning("Primary container 'trup-primary' not found. Attempting fallback.")
            fallback_container = soup.find('article') or soup.find('div', class_='entry-content')
            if fallback_container:
                 return fallback_container.get_text(separator=' ', strip=True)

            logging.error("Error: Could not find the trading update container.")
            return None
        except requests.exceptions.RequestException as e:
            logging.error(f"Error fetching the URL: {e}")
            return None

class GeminiEventParser:
    """
    Uses the Gemini AI to parse event details from text.
    """
    def __init__(self, api_key):
        genai.configure(api_key=api_key)
        # Priority list of models to try. 
        # 1. gemini-2.5-flash: Best balance of intelligence, speed, and stability.
        # 2. gemini-2.0-flash: Excellent previous generation.
        # 3. gemini-1.5-flash: Most reliable fallback for quotas.
        self.models_to_try = [
            'gemini-pro-latest',
            'gemini-2.5-flash',
            'gemini-2.5-flash'
        ]
        self.current_model = None

    @retry_operation(max_retries=3, delay=5)
    def parse_event_details(self, text):
        """
        Sends text to the Gemini API to extract a list of event start and end times.
        Iterates through available models if one fails.
        """
        prompt = f"""
        Analyze the following text from a trading update. Your task is to identify all scheduled maintenance or market closures related to cTrader or cryptocurrencies.

        If you find one or more events, extract the exact start date/time and end date/time for each.
        The text explicitly states times are in "GMT+3". Please ensure your output reflects this.
        
        Provide the output ONLY as a JSON array of objects. Each object must have "start_time" and "end_time" keys.
        The values should be in the ISO 8601 format (YYYY-MM-DDTHH:MM:SS).

        If no events are found, return an empty array [].

        Text to analyze:
        ---
        {text}
        ---
        """

        last_exception = None

        for model_name in self.models_to_try:
            try:
                logging.info(f"Attempting to parse with model: {model_name}")
                model = genai.GenerativeModel(
                    model_name,
                    generation_config={"response_mime_type": "application/json"}
                )
                
                response = model.generate_content(prompt)
                
                # With JSON mode, we can directly load the text
                event_list = json.loads(response.text)
                parsed_events = []
                
                if not isinstance(event_list, list):
                    logging.warning(f"Model {model_name} response was not a list.")
                    continue # Try next model

                for event in event_list:
                    start_str = event.get("start_time")
                    end_str = event.get("end_time")
                    if start_str and end_str:
                        # Parse string to a naive datetime object first
                        start_time = datetime.datetime.fromisoformat(start_str)
                        end_time = datetime.datetime.fromisoformat(end_str)
                        parsed_events.append((start_time, end_time))
                
                if parsed_events:
                    logging.info(f"AI identified {len(parsed_events)} event(s) using {model_name}.")
                else:
                    logging.info(f"AI ({model_name}) did not find any specific event times in the text.")

                return parsed_events

            except (json.JSONDecodeError, ValueError, TypeError) as e:
                logging.error(f"Parsing error with {model_name}: {e}")
                last_exception = e
            except Exception as e:
                logging.warning(f"Model {model_name} failed: {e}")
                last_exception = e
                # If it's a quota error (429), trying another model MIGHT help if quotas are per-model,
                # but usually it's per-project. We continue anyway just in case.
                continue
        
        # If we exhaust all models
        logging.error("All AI models failed to parse the text.")
        if last_exception:
            raise last_exception
        return []

class GoogleCalendarManager:
    """
    Manages events on a Google Calendar.
    """
    def __init__(self, credentials_file=CREDENTIALS_PATH, token_file=TOKEN_PATH):
        self.creds = None
        if os.path.exists(token_file):
            self.creds = Credentials.from_authorized_user_file(token_file, SCOPES)
        
        if not self.creds or not self.creds.valid:
            if self.creds and self.creds.expired and self.creds.refresh_token:
                try:
                    self.creds.refresh(Request())
                except RefreshError:
                    logging.warning("Token refresh failed (likely expired or revoked). Initiating new login flow.")
                    self.creds = None

            if not self.creds:
                flow = InstalledAppFlow.from_client_secrets_file(credentials_file, SCOPES)
                # Request offline access to get a refresh token
                # 'prompt="consent"' forces the consent screen to ensure we get a refresh token
                self.creds = flow.run_local_server(port=0, access_type='offline', prompt='consent')
            
            with open(token_file, 'w') as token:
                token.write(self.creds.to_json())
        
        self.service = build('calendar', 'v3', credentials=self.creds)
        self.calendar_id = self._get_or_create_calendar_by_name(CALENDAR_NAME)

    def _get_or_create_calendar_by_name(self, calendar_name):
        """
        Checks if a calendar exists. If not, creates it.
        Returns:
            str: The ID of the calendar.
        """
        try:
            logging.info(f"Checking for calendar named '{calendar_name}'...")
            calendar_list = self.service.calendarList().list().execute()
            for calendar_list_entry in calendar_list.get('items', []):
                if calendar_list_entry['summary'] == calendar_name:
                    logging.info(f"Found existing calendar.")
                    return calendar_list_entry['id']
            
            logging.info(f"Calendar not found. Creating a new one...")
            # BEST PRACTICE: Use IANA timezone for auto Daylight Saving adjustments
            calendar_body = {
                'summary': calendar_name,
                'timeZone': 'Europe/Bucharest' 
            }
            created_calendar = self.service.calendars().insert(body=calendar_body).execute()
            logging.info(f"Successfully created calendar '{calendar_name}'.")
            return created_calendar['id']
        except HttpError as error:
            logging.error(f"An error occurred with the calendar list: {error}")
            return 'primary'

    def get_upcoming_events(self):
        """
        Fetches events for the next 7 days from the specific calendar to check for duplicates.
        """
        now = datetime.datetime.now(datetime.timezone.utc)
        time_min = now.isoformat()
        time_max = (now + datetime.timedelta(days=7)).isoformat()
        
        try:
            events_result = self.service.events().list(
                calendarId=self.calendar_id, 
                timeMin=time_min,
                timeMax=time_max,
                singleEvents=True,
                orderBy='startTime'
            ).execute()
            events = events_result.get('items', [])
            
            existing_events = set()
            for event in events:
                start = event['start'].get('dateTime', event['start'].get('date'))
                start_dt = date_parse(start) # dateutil.parser handles timezone conversion
                existing_events.add((event['summary'], start_dt))
            return existing_events
        except HttpError as error:
            logging.error(f"An error occurred while fetching calendar events: {error}")
            return set()

    def create_event(self, summary, description, start_time, end_time):
        """
        Creates an event on the specified calendar, but only if it's in the future.
        """
        # --- NEW FEATURE: Check if the event is in the past ---
        # Compare the event's end time with the current UTC time.
        if end_time < datetime.datetime.now(timezone.utc):
            logging.info(f"Skipping past event: '{summary}' scheduled to end at {end_time}")
            return # Exit the function, skipping the creation

        try:
            event = {
                'summary': summary,
                'description': description,
                # The start_time and end_time are already timezone-aware
                'start': {'dateTime': start_time.isoformat(), 'timeZone': 'Europe/Bucharest'},
                'end': {'dateTime': end_time.isoformat(), 'timeZone': 'Europe/Bucharest'},
            }
            created_event = self.service.events().insert(calendarId=self.calendar_id, body=event).execute()
            logging.info(f"Event created successfully: {created_event.get('htmlLink')}")
        except HttpError as error:
            logging.error(f'An error occurred while creating the calendar event: {error}')

class TradingUpdateScheduler:
    """
    Orchestrates scraping, parsing, and scheduling.
    """
    def __init__(self, scraper, calendar_manager, parser):
        self.scraper = scraper
        self.calendar_manager = calendar_manager
        self.parser = parser

    def run(self):
        logging.info(f"--- Running FTMO Update Check ---")
        latest_update_text = self.scraper.get_latest_update()
        
        if not latest_update_text:
            logging.info("Process finished: Could not retrieve update text.")
            return

        if any(keyword in latest_update_text.lower() for keyword in KEYWORDS):
            logging.info("Relevant update found. Parsing details with AI...")
            parsed_events = self.parser.parse_event_details(latest_update_text)

            if not parsed_events:
                logging.info("No events to schedule.")
                return
            
            logging.info("Checking for duplicate events in calendar...")
            existing_events = self.calendar_manager.get_upcoming_events()
            
            # Use ZoneInfo for correct DST handling in Bucharest
            bucharest_tz = ZoneInfo("Europe/Bucharest")

            for start_time, end_time in parsed_events:
                # Attach the timezone info to the parsed times
                # If the time is naive, we assume it's in the target timezone (or source if fixed)
                # Since the prompt says "GMT+3", we can either use fixed offset or map to Bucharest.
                # Mapping to Bucharest is safer for calendar display if we want it to align with the calendar settings.
                if start_time.tzinfo is None:
                    aware_start_time = start_time.replace(tzinfo=bucharest_tz)
                else:
                    aware_start_time = start_time.astimezone(bucharest_tz)
                
                if end_time.tzinfo is None:
                    aware_end_time = end_time.replace(tzinfo=bucharest_tz)
                else:
                    aware_end_time = end_time.astimezone(bucharest_tz)
                
                # Use the aware time for the duplicate check
                event_tuple = (EVENT_SUMMARY, aware_start_time)

                if event_tuple in existing_events:
                    logging.info(f"Skipping duplicate event: '{EVENT_SUMMARY}' at {start_time}")
                else:
                    logging.info(f"Found new event to schedule: '{EVENT_SUMMARY}' at {start_time}")
                    self.calendar_manager.create_event(
                        summary=EVENT_SUMMARY,
                        description=latest_update_text,
                        start_time=aware_start_time,
                        end_time=aware_end_time
                    )
        else:
            logging.info("No relevant updates found containing the specified keywords.")
        
        logging.info("--- Check Finished ---")

if __name__ == '__main__':
    if not GEMINI_API_KEY:
        logging.critical("FATAL ERROR: GEMINI_API_KEY not found. Please create a .env file and add your key.")
    else:
        try:
            ftmo_scraper = FTMOScraper(FTMO_URL)
            gcal_manager = GoogleCalendarManager()
            gemini_parser = GeminiEventParser(api_key=GEMINI_API_KEY)
            
            scheduler = TradingUpdateScheduler(ftmo_scraper, gcal_manager, gemini_parser)
            scheduler.run()
        except Exception as e:
            logging.critical(f"An unexpected error occurred during execution: {e}", exc_info=True)