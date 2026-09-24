#!/bin/bash
# NSE Swing Scanner — Start Web Server
cd "$(dirname "$0")"

# Kill anything already on port 5000
lsof -ti:5000 | xargs kill -9 2>/dev/null

# Always use the venv Python (Flask + openpyxl are installed here)
.venv/bin/python app.py
