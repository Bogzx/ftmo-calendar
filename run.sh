#!/bin/bash

# 1. Navigate to the script's directory (so it finds .env, token.json, etc.)
cd "$(dirname "$0")"

# 2. Activate the virtual environment
# Change 'venv' if you named your environment something else
if [ -f "venv/bin/activate" ]; then
    source venv/bin/activate
else
    echo "Error: Virtual environment 'venv' not found."
    echo "Please run: python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt"
    exit 1
fi

# 3. Run the Python script
# Output is already logged to app.log by the Python script itself, 
# but we can capture standard output/error here if needed.
python3 main.py
