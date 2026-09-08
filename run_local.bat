@echo off
cd /d %~dp0
python -m pip install -r requirements.txt
python update_data.py
start http://localhost:8000
python -m http.server 8000
