# main.py
import requests
from bs4 import BeautifulSoup
import datetime
import os
import json
import re
import google.generativeai as genai
from dotenv import load_dotenv
from dateutil.parser import parse as date_parse

# Added for timezone-aware datetime objects
from datetime import timezone

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

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
FTMO_URL = 'https://ftmo.com/en/trading-updates/'
KEYWORDS = ['maintenance', 'crypto market is closed', 'ctrader']
EVENT_SUMMARY = 'cTrader Maintenance/Crypto Market Closure'
CALENDAR_NAME = 'Trading' # The name of the sub-calendar to use

class FTMOScraper:
    """
    Scrapes the FTMO trading updates page for relevant information using BeautifulSoup.
    """
    def __init__(self, url):
        self.url = url

    def get_latest_update(self):
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            }
            response = requests.get(self.url, headers=headers)
            response.raise_for_status()
            soup = BeautifulSoup(response.content, 'html.parser')
            latest_update_container = soup.find('div', class_='trup-primary')
            if latest_update_container:
                return latest_update_container.get_text(separator=' ', strip=True)
            else:
                print("Error: Could not find the trading update container (div with class 'trup-primary').")
                return None
        except requests.exceptions.RequestException as e:
            print(f"Error fetching the URL: {e}")
            return None

class GeminiEventParser:
    """
    Uses the Gemini AI to parse event details from text.
    """
    def __init__(self, api_key):
        genai.configure(api_key=api_key)
        # NOTE: Consider using a more recent or specific model if available
        self.model = genai.GenerativeModel('gemini-2.5-pro') 

    def parse_event_details(self, text):
        """
        Sends text to the Gemini API to extract a list of event start and end times.
        Returns:
            list: A list of tuples, where each tuple contains (start_time, end_time) as datetime objects.
        """
        prompt = f"""
        Analyze the following text from a trading update. Your task is to identify all scheduled maintenance or market closures related to cTrader or cryptocurrencies.

        If you find one or more events, extract the exact start date/time and end date/time for each.
        The text explicitly states times are in "GMT+3". Please ensure your output reflects this.
        
        Provide the output ONLY as a single, minified JSON array of objects. Each object must have "start_time" and "end_time" keys.
        The values should be in the ISO 8601 format (YYYY-MM-DDTHH:MM:SS).

        If no events are found, return an empty array [].

        Text to analyze:
        ---
        {text}
        ---
        """
        try:
            response = self.model.generate_content(prompt)
            
            clean_text = re.sub(r'```(json)?', '', response.text).strip()

            event_list = json.loads(clean_text)
            parsed_events = []
            
            if not isinstance(event_list, list):
                print("AI response was not a list as expected.")
                return []

            for event in event_list:
                start_str = event.get("start_time")
                end_str = event.get("end_time")
                if start_str and end_str:
                    # Parse string to a naive datetime object first
                    start_time = datetime.datetime.fromisoformat(start_str)
                    end_time = datetime.datetime.fromisoformat(end_str)
                    parsed_events.append((start_time, end_time))
            
            if parsed_events:
                print(f"AI identified {len(parsed_events)} event(s).")
            else:
                print("AI did not find any specific event times in the text.")

            return parsed_events
        except (json.JSONDecodeError, ValueError, TypeError, Exception) as e:
            print(f"An error occurred while parsing the AI response: {e}")
            print(f"Raw AI response was: {response.text if 'response' in locals() else 'No response from AI.'}")
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
                self.creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(credentials_file, SCOPES)
                self.creds = flow.run_local_server(port=0)
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
            print(f"Checking for calendar named '{calendar_name}'...")
            calendar_list = self.service.calendarList().list().execute()
            for calendar_list_entry in calendar_list.get('items', []):
                if calendar_list_entry['summary'] == calendar_name:
                    print(f"Found existing calendar.")
                    return calendar_list_entry['id']
            
            print(f"Calendar not found. Creating a new one...")
            # BEST PRACTICE: Use IANA timezone for auto Daylight Saving adjustments
            calendar_body = {
                'summary': calendar_name,
                'timeZone': 'Europe/Bucharest' 
            }
            created_calendar = self.service.calendars().insert(body=calendar_body).execute()
            print(f"Successfully created calendar '{calendar_name}'.")
            return created_calendar['id']
        except HttpError as error:
            print(f"An error occurred with the calendar list: {error}")
            return 'primary'

    def get_upcoming_events(self):
        """
        Fetches events for the next 7 days from the specific calendar to check for duplicates.
        """
        now = datetime.datetime.utcnow()
        time_min = now.isoformat() + 'Z'
        time_max = (now + datetime.timedelta(days=7)).isoformat() + 'Z'
        
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
            print(f"An error occurred while fetching calendar events: {error}")
            return set()

    def create_event(self, summary, description, start_time, end_time):
        """
        Creates an event on the specified calendar, but only if it's in the future.
        """
        # --- NEW FEATURE: Check if the event is in the past ---
        # Compare the event's end time with the current UTC time.
        if end_time < datetime.datetime.now(timezone.utc):
            print(f"Skipping past event: '{summary}' scheduled to end at {end_time}")
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
            print(f"Event created successfully: {created_event.get('htmlLink')}")
        except HttpError as error:
            print(f'An error occurred while creating the calendar event: {error}')

class TradingUpdateScheduler:
    """
    Orchestrates scraping, parsing, and scheduling.
    """
    def __init__(self, scraper, calendar_manager, parser):
        self.scraper = scraper
        self.calendar_manager = calendar_manager
        self.parser = parser

    def run(self):
        print(f"--- Running FTMO Update Check: {datetime.datetime.now()} ---")
        latest_update_text = self.scraper.get_latest_update()
        
        if not latest_update_text:
            print("Process finished: Could not retrieve update text.")
            return

        if any(keyword in latest_update_text.lower() for keyword in KEYWORDS):
            print("Relevant update found. Parsing details with AI...")
            parsed_events = self.parser.parse_event_details(latest_update_text)

            if not parsed_events:
                print("No events to schedule.")
                return
            
            print("Checking for duplicate events in calendar...")
            existing_events = self.calendar_manager.get_upcoming_events()
            
            # Define the GMT+3 timezone for making naive datetimes aware
            gmt_plus_3 = datetime.timezone(datetime.timedelta(hours=3))

            for start_time, end_time in parsed_events:
                # Attach the GMT+3 timezone info to the parsed times
                aware_start_time = start_time.replace(tzinfo=gmt_plus_3)
                aware_end_time = end_time.replace(tzinfo=gmt_plus_3)
                
                # Use the aware time for the duplicate check
                event_tuple = (EVENT_SUMMARY, aware_start_time)

                if event_tuple in existing_events:
                    print(f"Skipping duplicate event: '{EVENT_SUMMARY}' at {start_time}")
                else:
                    print(f"Found new event to schedule: '{EVENT_SUMMARY}' at {start_time}")
                    self.calendar_manager.create_event(
                        summary=EVENT_SUMMARY,
                        description=latest_update_text,
                        start_time=aware_start_time,
                        end_time=aware_end_time
                    )
        else:
            print("No relevant updates found containing the specified keywords.")
        
        print("--- Check Finished ---")

if __name__ == '__main__':
    if not GEMINI_API_KEY:
        print("FATAL ERROR: GEMINI_API_KEY not found. Please create a .env file and add your key.")
    else:
        try:
            ftmo_scraper = FTMOScraper(FTMO_URL)
            gcal_manager = GoogleCalendarManager()
            gemini_parser = GeminiEventParser(api_key=GEMINI_API_KEY)
            
            scheduler = TradingUpdateScheduler(ftmo_scraper, gcal_manager, gemini_parser)
            scheduler.run()
        except Exception as e:
            print(f"An unexpected error occurred during execution: {e}")