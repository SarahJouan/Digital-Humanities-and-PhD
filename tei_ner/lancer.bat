@echo off
REM Lance l'application en local sous Windows.
cd /d "%~dp0"
if not exist ".venv" (
  echo Creation de l'environnement virtuel...
  python -m venv .venv
  .venv\Scripts\python -m pip install --upgrade pip
  .venv\Scripts\pip install -r requirements.txt
)
.venv\Scripts\streamlit run app.py
