@echo off
REM Azure SRE Agent Evaluation Framework - Windows Launcher
echo Starting Azure SRE Agent Evaluation Framework on Windows...

IF NOT EXIST .venv (
    echo Creating Python virtual environment...
    python -m venv .venv
    call .venv\Scripts\activate
    echo Installing required packages...
    pip install -r requirements.txt
) ELSE (
    call .venv\Scripts\activate
)

echo Starting FastAPI server at http://127.0.0.1:8000 ...
uvicorn main:app --host 127.0.0.1 --port 8000 --reload
pause
