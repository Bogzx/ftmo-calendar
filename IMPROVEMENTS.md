# Future Improvements

## 1. 🧠 Smart Caching (Save Money & Quota)
**The Problem:** The script asks the AI to analyze the text *every single day*, even if the FTMO website hasn't changed. This wastes Gemini API quota.
**The Fix:**
*   Calculate a "fingerprint" (hash) of the website text.
*   Save it to a file (`last_state.txt`).
*   Next time the script runs, compare the new text with the saved one.
*   **If it's the same:** Stop immediately. (0 API calls used).
*   **If it's different:** Run the AI.

## 2. 🔔 Notifications (Discord/Telegram)
**The Problem:** You only know if it works by checking the calendar or the log file. If the token expires or the script crashes, you won't know until you miss a trade.
**The Fix:**
*   Add a **Discord Webhook** (or Telegram bot).
*   The script sends a ping: *"✅ Added new maintenance event for Oct 12"* or *"❌ Error: Token expired"*.

## 3. 🐳 Docker Support (Solve Dependency Hell)
**The Problem:** Setting up Python versions, `venv`, and dependencies like `grpcio` on different servers (Linux/ARM) can be difficult.
**The Fix:**
*   Wrap the whole app in **Docker**.
*   Run with `docker-compose up -d`.
*   Ensures the app works exactly the same on Windows, Linux, Mac, or Raspberry Pi without installing Python manually.
